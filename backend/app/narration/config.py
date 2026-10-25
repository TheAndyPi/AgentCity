import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

MIB = 1024 * 1024


def _number(name, default, kind=float):
    return kind(os.getenv(name, str(default)))


@dataclass(frozen=True)
class NarrationConfig:
    disaster_effects: bool = False
    disaster_music: bool = False
    disaster_reactions: bool = False
    effects_model: str = "eleven_text_to_sound_v2"
    music_model: str = "music_v1"
    reactions_model: str = "eleven_v3"
    sound_deadline: float = 60
    enabled: bool = False
    api_key: str = field(default="", repr=False)
    voice_id: str = ""
    character_voice_ids: tuple[str, ...] = ()
    model_id: str = ""
    output_format: str = "mp3_44100_128"
    base_url: str = "https://api.elevenlabs.io"
    public_origin: str = ""
    deadline: float = 20
    attempt_timeout: float = 15
    max_attempts: int = 3
    retry_backoff: float = 0.5
    concurrency: int = 2
    queue_limit: int = 8
    requests_per_minute: int = 120
    max_characters: int = 2500
    max_audio_bytes: int = 4 * MIB
    cache_max_bytes: int = 64 * MIB
    cache_max_entries: int = 256
    cache_ttl: float = 86400
    url_ttl: float = 900

    @classmethod
    def from_env(cls):
        return cls(
            disaster_effects=os.getenv("ENABLE_DISASTER_EFFECTS", "false").lower() == "true",
            disaster_music=os.getenv("ENABLE_DISASTER_MUSIC", "false").lower() == "true",
            disaster_reactions=os.getenv("ENABLE_DISASTER_REACTIONS", "false").lower() == "true",
            effects_model=os.getenv("ELEVENLABS_EFFECTS_MODEL", "eleven_text_to_sound_v2"),
            music_model=os.getenv("ELEVENLABS_MUSIC_MODEL", "music_v1"),
            reactions_model=os.getenv("ELEVENLABS_REACTIONS_MODEL", "eleven_v3"),
            sound_deadline=_number("DISASTER_AUDIO_DEADLINE_SECONDS", 60),
            enabled=os.getenv("ENABLE_NARRATION", "false").lower() == "true",
            api_key=os.getenv("ELEVENLABS_API_KEY", ""),
            voice_id=os.getenv("ELEVENLABS_VOICE_ID", ""),
            character_voice_ids=tuple(
                v.strip() for v in os.getenv("ELEVENLABS_CHARACTER_VOICE_IDS", "").split(",") if v.strip()
            ),
            model_id=os.getenv("ELEVENLABS_MODEL_ID", ""),
            output_format=os.getenv("ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_128"),
            public_origin=os.getenv("NARRATION_PUBLIC_ORIGIN", "").rstrip("/"),
            deadline=_number("NARRATION_DEADLINE_SECONDS", 20),
            concurrency=_number("NARRATION_MAX_CONCURRENCY", 2, int),
            requests_per_minute=_number("NARRATION_REQUESTS_PER_MINUTE", 120, int),
            max_characters=_number("NARRATION_MAX_CHARACTERS", 2500, int),
            max_audio_bytes=_number("NARRATION_MAX_AUDIO_BYTES", 4 * MIB, int),
            cache_max_bytes=_number("NARRATION_CACHE_MAX_BYTES", 64 * MIB, int),
            cache_max_entries=_number("NARRATION_CACHE_MAX_ENTRIES", 256, int),
            cache_ttl=_number("NARRATION_CACHE_TTL_SECONDS", 86400),
            url_ttl=_number("NARRATION_URL_TTL_SECONDS", 900),
        )

    def validate(self):
        # Messages name settings, never values: the API key must not reach logs.
        if not self.enabled:
            return
        if not self.api_key or len(self.api_key) > 256 or not self.api_key.isprintable():
            raise ValueError("ENABLE_NARRATION=true requires ELEVENLABS_API_KEY")
        if not re.fullmatch(r"[A-Za-z0-9]{1,64}", self.voice_id):
            raise ValueError("ENABLE_NARRATION=true requires an alphanumeric ELEVENLABS_VOICE_ID")
        if (
            len(self.character_voice_ids) > 1000
            or len(set(self.character_voice_ids)) != len(self.character_voice_ids)
            or any(not re.fullmatch(r"[A-Za-z0-9]{1,64}", voice) for voice in self.character_voice_ids)
        ):
            raise ValueError("ELEVENLABS_CHARACTER_VOICE_IDS must contain distinct alphanumeric voice IDs")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", self.model_id):
            raise ValueError("ENABLE_NARRATION=true requires ELEVENLABS_MODEL_ID from your account")
        if not re.fullmatch(r"mp3_\d{4,5}_\d{2,3}", self.output_format):
            raise ValueError("ELEVENLABS_OUTPUT_FORMAT must be an mp3_<rate>_<kbps> format")
        base = urlsplit(self.base_url)
        if base.scheme != "https" or not base.hostname or base.path not in {"", "/"}:
            raise ValueError("ElevenLabs base URL must be an https origin")
        if self.public_origin:
            origin = urlsplit(self.public_origin)
            if origin.scheme not in {"http", "https"} or not origin.hostname or origin.path:
                raise ValueError("NARRATION_PUBLIC_ORIGIN must be an absolute origin without a path")
        if not (
            0 < self.deadline <= 60
            and 0 < self.attempt_timeout
            and 1 <= self.max_attempts <= 5
            and 0 <= self.retry_backoff <= 10
            and 1 <= self.concurrency <= 8
            and 0 <= self.queue_limit <= 64
            and 1 <= self.requests_per_minute <= 600
            and 1 <= self.max_characters <= 5000
            and 1024 <= self.max_audio_bytes <= 32 * MIB
            and self.max_audio_bytes <= self.cache_max_bytes <= 4096 * MIB
            and 1 <= self.cache_max_entries <= 100000
            and 60 <= self.url_ttl <= self.cache_ttl <= 30 * 86400
        ):
            raise ValueError("Narration limits are outside the supported ranges")
