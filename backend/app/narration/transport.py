"""Server-only ElevenLabs text-to-speech client.

Every synthesis has one total deadline covering admission, attempts and backoff.
Errors carry a fixed reason; response bodies, URLs and credentials never leave here.
"""

import asyncio
import logging
import time
from collections import deque
from urllib.parse import quote

import httpx

log = logging.getLogger("agentcity.narration")

RETRY_STATUSES = {429, 500, 502, 503, 504}
MESSAGES = {
    "busy": "Narration capacity is busy; retry shortly",
    "rate_limited": "Narration request rate limit reached; retry shortly",
    "provider_rate_limited": "The speech provider is rate limiting requests; retry shortly",
    "timeout": "The speech provider did not respond in time",
    "unavailable": "The speech provider is unavailable",
    "rejected": "The speech provider rejected the configured narration request",
    "malformed": "The speech provider returned invalid audio",
    "oversized": "The speech provider returned audio larger than the configured limit",
    "voice_unavailable": "The assigned citizen voice is unauthorized or unavailable; restore ElevenLabs voice access",
}


class ProviderFailure(Exception):
    def __init__(self, reason, retry_after=None, retry=False):
        super().__init__(MESSAGES[reason])
        self.reason, self.retry_after, self.retry = reason, retry_after, retry


MPEG_BITRATES = {
    # (version is MPEG-1) -> Layer III kbps by index
    True: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
    False: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
}
MPEG_RATES = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}


def _frame_length(data, offset):
    if offset + 4 > len(data) or data[offset] != 0xFF or data[offset + 1] & 0xE0 != 0xE0:
        return None
    version = (data[offset + 1] >> 3) & 3
    layer = (data[offset + 1] >> 1) & 3
    bitrate_index = data[offset + 2] >> 4
    rate_index = (data[offset + 2] >> 2) & 3
    if version == 1 or layer != 1 or bitrate_index in {0, 15} or rate_index == 3:
        return None
    mpeg1 = version == 3
    bitrate = MPEG_BITRATES[mpeg1][bitrate_index] * 1000
    padding = (data[offset + 2] >> 1) & 1
    return (144 if mpeg1 else 72) * bitrate // MPEG_RATES[version][rate_index] + padding


def valid_mp3(data):
    """At least two consecutive MPEG Layer III frames after an optional ID3v2 tag."""
    offset = 0
    if data[:3] == b"ID3" and len(data) >= 10:
        size = 0
        for byte in data[6:10]:
            if byte & 0x80:
                return False
            size = size << 7 | byte
        offset = 10 + size + (10 if data[5] & 0x10 else 0)
    first = _frame_length(data, offset)
    if not first:
        return False
    second = _frame_length(data, offset + first)
    return bool(second) and offset + first + second <= len(data)


class ElevenLabsTransport:
    def __init__(self, config, client=None, sleep=asyncio.sleep, clock=time.monotonic):
        self.config = config
        self.client = client or httpx.AsyncClient(follow_redirects=False)
        self.sleep, self.clock = sleep, clock
        self.slots = asyncio.Semaphore(config.concurrency)
        self.waiting = 0
        self.attempts = deque()
        self.calls = 0
        self.verified_voices = {}
        self.voice_checks = {}

    async def close(self):
        for task in self.voice_checks.values():
            task.cancel()
        await asyncio.gather(*self.voice_checks.values(), return_exceptions=True)
        await self.client.aclose()

    async def validate_voice(self, voice_id):
        """Bounded server-only authorization check; no cloning or catalog exposure."""
        if self.verified_voices.get(voice_id, 0) > self.clock():
            return
        task = self.voice_checks.get(voice_id)
        if task is None:
            if len(self.voice_checks) >= self.config.concurrency + self.config.queue_limit:
                raise ProviderFailure("busy")
            task = asyncio.create_task(self._check_voice(voice_id))
            self.voice_checks[voice_id] = task
            task.add_done_callback(lambda _: self.voice_checks.pop(voice_id, None))
        return await asyncio.shield(task)

    async def _check_voice(self, voice_id):
        try:
            async with asyncio.timeout(self.config.deadline):
                async with self.slots:
                    self._admit_attempt()
                    async with self.client.stream(
                        "GET",
                        f"{self.config.base_url.rstrip('/')}/v1/voices/{quote(voice_id, safe='')}",
                        headers={"xi-api-key": self.config.api_key},
                        timeout=httpx.Timeout(self.config.attempt_timeout),
                    ) as response:
                        if response.status_code != 200:
                            raise ProviderFailure("voice_unavailable")
                        # Status is sufficient for this voice-specific authorized
                        # endpoint. Do not read an unbounded provider catalog/body.
            if len(self.verified_voices) >= 1000:
                self.verified_voices.pop(next(iter(self.verified_voices)))
            self.verified_voices[voice_id] = self.clock() + 300
        except (TimeoutError, httpx.HTTPError):
            raise ProviderFailure("voice_unavailable") from None

    def _admit_attempt(self):
        now = self.clock()
        while self.attempts and self.attempts[0] <= now - 60:
            self.attempts.popleft()
        if len(self.attempts) >= self.config.requests_per_minute:
            raise ProviderFailure("rate_limited", max(1, int(self.attempts[0] + 60 - now) + 1))
        self.attempts.append(now)

    async def synthesize(self, text, voice_id=None):
        if self.waiting >= self.config.queue_limit + self.config.concurrency:
            raise ProviderFailure("busy", 2)
        self.waiting += 1
        started = self.clock()
        try:
            async with asyncio.timeout(self.config.deadline):
                async with self.slots:
                    return await self._attempts(text, started, voice_id or self.config.voice_id)
        except TimeoutError:
            log.warning("ElevenLabs synthesis exceeded its total deadline")
            raise ProviderFailure("timeout") from None
        finally:
            self.waiting -= 1

    async def _attempts(self, text, started, voice_id):
        for attempt in range(1, self.config.max_attempts + 1):
            self._admit_attempt()
            try:
                return await self._attempt(text, self.config.deadline - (self.clock() - started), voice_id)
            except ProviderFailure as failure:
                log.warning("ElevenLabs attempt %d failed: %s", attempt, failure.reason)
                if not failure.retry or attempt == self.config.max_attempts:
                    raise
                wait = failure.retry_after or self.config.retry_backoff * 2 ** (attempt - 1)
                if self.clock() - started + wait >= self.config.deadline:
                    raise
                await self.sleep(wait)
        raise ProviderFailure("unavailable")

    async def _attempt(self, text, remaining, voice_id):
        url = f"{self.config.base_url.rstrip('/')}/v1/text-to-speech/{quote(voice_id, safe='')}"
        timeout = httpx.Timeout(max(0.1, min(self.config.attempt_timeout, remaining)))
        self.calls += 1
        try:
            async with self.client.stream(
                "POST",
                url,
                params={"output_format": self.config.output_format},
                headers={
                    "xi-api-key": self.config.api_key,
                    "Accept": "audio/mpeg",
                    "Content-Type": "application/json",
                },
                json={"text": text, "model_id": self.config.model_id},
                timeout=timeout,
            ) as response:
                status = response.status_code
                if status != 200:
                    if status == 429:
                        raise ProviderFailure("provider_rate_limited", _retry_after(response), retry=True)
                    if status in RETRY_STATUSES:
                        raise ProviderFailure("unavailable", _retry_after(response), retry=True)
                    if 400 <= status < 500:
                        raise ProviderFailure("rejected")
                    raise ProviderFailure("unavailable")
                if not response.headers.get("content-type", "").lower().startswith("audio/mpeg"):
                    raise ProviderFailure("malformed")
                declared = response.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > self.config.max_audio_bytes:
                    raise ProviderFailure("oversized")
                audio = bytearray()
                async for chunk in response.aiter_bytes():
                    audio.extend(chunk)
                    if len(audio) > self.config.max_audio_bytes:
                        raise ProviderFailure("oversized")
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            # The request never reached the provider, so repeating it cannot double-bill.
            raise ProviderFailure("unavailable", retry=True) from None
        except httpx.TimeoutException:
            raise ProviderFailure("timeout") from None
        except httpx.HTTPError:
            raise ProviderFailure("unavailable") from None
        audio = bytes(audio)
        if not valid_mp3(audio):
            raise ProviderFailure("malformed")
        return audio


def _retry_after(response):
    value = response.headers.get("retry-after", "")
    return min(30, max(0.0, float(value))) if value.replace(".", "", 1).isdigit() else None
