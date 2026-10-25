"""Controlled ElevenLabs HTTP endpoint; never contacts the paid service.

The adapter's real HTTP code runs against httpx.MockTransport. Each response is
known-valid MP3 audio whose ID3 tag carries a digest of the received text, so a
test can prove which recorded text produced the bytes a client fetched.
"""

import asyncio
import hashlib
import json
import struct
import threading
from collections import deque
from pathlib import Path

import httpx

from app.narration.config import NarrationConfig
from app.narration.transport import ElevenLabsTransport

TONE = (Path(__file__).parent / "fixtures" / "narration" / "tone.mp3").read_bytes()
API_KEY = "test-elevenlabs-key-must-never-leave-the-server"


def marker(text):
    return "agentcity-narration:" + hashlib.sha256(text.encode()).hexdigest()[:32]


def marked_audio(text):
    body = b"\x03agentcity\x00" + marker(text).encode()
    frame = b"TXXX" + struct.pack(">I", len(body)) + b"\x00\x00" + body
    size = len(frame)
    synchsafe = bytes([(size >> 21) & 0x7F, (size >> 14) & 0x7F, (size >> 7) & 0x7F, size & 0x7F])
    return b"ID3\x03\x00\x00" + synchsafe + frame + TONE


def config(**overrides):
    values = dict(
        enabled=True,
        api_key=API_KEY,
        voice_id="TestVoice01",
        character_voice_ids=tuple(f"CitizenVoice{i:03}" for i in range(100)),
        model_id="eleven_test_model",
        deadline=5,
        attempt_timeout=2,
        retry_backoff=0.01,
        requests_per_minute=100,
    )
    return NarrationConfig(**(values | overrides))


class ElevenLabsFake:
    def __init__(self):
        self.requests = []
        self.script = deque()
        self.gate = threading.Event()
        self.gate.set()
        self.lock = threading.Lock()

    @property
    def texts(self):
        return [r["body"]["text"] for r in self.requests]

    def fail(self, *actions):
        self.script.extend(actions)

    async def handle(self, request):
        record = dict(
            method=request.method,
            host=request.url.host,
            path=request.url.path,
            query=dict(request.url.params),
            api_key=request.headers.get("xi-api-key"),
            accept=request.headers.get("accept"),
            body=json.loads(request.content),
        )
        with self.lock:
            self.requests.append(record)
            action = self.script.popleft() if self.script else "ok"
        while not self.gate.is_set():
            await asyncio.sleep(0.005)
        kind, *args = action if isinstance(action, tuple) else (action,)
        if kind == "ok":
            return httpx.Response(
                200, headers={"content-type": "audio/mpeg"}, content=marked_audio(record["body"]["text"])
            )
        if kind == "status":
            status, headers = args[0], args[1] if len(args) > 1 else {}
            return httpx.Response(
                status, headers=headers, json={"detail": {"message": "vendor secret detail " + API_KEY}}
            )
        if kind == "connect":
            raise httpx.ConnectError("connection refused to vendor", request=request)
        if kind == "read_timeout":
            raise httpx.ReadTimeout("vendor read timed out", request=request)
        if kind == "hang":
            await asyncio.sleep(args[0])
            return httpx.Response(200, headers={"content-type": "audio/mpeg"}, content=TONE)
        if kind == "malformed":
            return httpx.Response(200, headers={"content-type": "audio/mpeg"}, content=b"\x00" * 4096)
        if kind == "json":
            return httpx.Response(200, json={"audio": "not audio"})
        if kind == "oversized":
            return httpx.Response(200, headers={"content-type": "audio/mpeg"}, content=TONE * args[0])
        if kind == "oversized_stream":

            async def chunks():
                for _ in range(args[0]):
                    yield TONE

            return httpx.Response(200, headers={"content-type": "audio/mpeg"}, content=chunks())
        raise AssertionError(f"unknown fake action {action}")

    def transport(self, narration_config, **kwargs):
        client = httpx.AsyncClient(transport=httpx.MockTransport(self.handle))
        return ElevenLabsTransport(narration_config, client, **kwargs)
