"""Opt-in paid ElevenLabs smoke test through the real application routes.

    python -m scripts.narration_smoke --live [--save PATH]

Uses ENABLE_NARRATION/ELEVENLABS_* from the environment, a disposable DATA_DIR and
one short recorded decision. Prints sanitized evidence only: never the API key,
request headers or vendor error bodies.
"""

import argparse
import hashlib
import json
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.infrastructure.config import AppConfig
from app.main import create_app
from app.narration.config import NarrationConfig
from app.narration.speech import recorded_text
from app.narration.transport import valid_mp3

REQUIRED = ("ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID", "ELEVENLABS_MODEL_ID")


def write(client, path, body, method="POST"):
    key = body.get("request_id", str(uuid4()))
    return client.request(method, "/api/v1" + path, json=body, headers={"Idempotency-Key": key})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Required: makes one paid synthesis request")
    parser.add_argument("--save", type=Path, help="Optionally save the synthesized MP3 for manual playback")
    args = parser.parse_args()
    if not args.live:
        sys.exit("Refusing to call ElevenLabs without --live")
    config = NarrationConfig.from_env()
    missing = [
        name for name, value in zip(REQUIRED, (config.api_key, config.voice_id, config.model_id)) if not value
    ]
    if not config.enabled or missing:
        print(
            json.dumps(
                dict(
                    status="unverified",
                    reason="configuration missing",
                    missing=["ENABLE_NARRATION=true", *missing],
                )
            )
        )
        sys.exit(2)
    evidence = dict(
        started_at=datetime.now(UTC).isoformat(),
        model_id=config.model_id,
        voice_id_suffix=config.voice_id[-4:],
        output_format=config.output_format,
    )
    with tempfile.TemporaryDirectory(prefix="narration-live-") as directory:
        app = create_app(AppConfig(data_dir=Path(directory)), config)
        with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
            client.headers["X-CSRF-Token"] = client.get("/api/v1/session").json()["data"]["csrf_token"]
            created = write(
                client, "/simulations", dict(config=dict(name="Narration smoke", seed=42, population=10))
            )
            sid = created.json()["data"]["id"]
            deadline = time.monotonic() + 30
            while client.get(f"/api/v1/simulations/{sid}").json()["data"]["status"] == "initializing":
                if time.monotonic() > deadline:
                    sys.exit("City initialization timed out")
                time.sleep(0.05)
            simulation = client.get(f"/api/v1/simulations/{sid}").json()["data"]
            stepped = write(
                client,
                f"/simulations/{sid}/commands",
                dict(
                    request_id=str(uuid4()),
                    expected_control_version=simulation["control_version"],
                    command=dict(type="step", count=1),
                ),
            )
            if stepped.status_code != 200:
                sys.exit("Smoke city could not step")
            state = app.state.service.heads[sid]
            decision = min(state.decisions, key=lambda d: len(d.concise_rationale + d.outcome_description))
            selected_voice = app.state.narration.voices.resolve(state, "decision", decision.id, config)
            evidence["voice_id_suffix"] = selected_voice[-4:]
            started = time.monotonic()
            response = write(
                client, f"/simulations/{sid}/narration", dict(source_type="decision", source_id=decision.id)
            )
            evidence["narration_status"] = response.status_code
            evidence["narration_seconds"] = round(time.monotonic() - started, 3)
            if response.status_code != 200:
                evidence.update(status="failed", error=response.json().get("error", {}))
                print(json.dumps(evidence, indent=2))
                sys.exit(1)
            data = response.json()["data"]
            audio = client.get(data["audio_url"])
            repeat = write(
                client, f"/simulations/{sid}/narration", dict(source_type="decision", source_id=decision.id)
            )
            transport = app.state.narration.transport
            evidence.update(
                expires_at=data["expires_at"],
                media_status=audio.status_code,
                media_type=audio.headers.get("content-type"),
                audio_bytes=len(audio.content),
                audio_sha256_prefix=hashlib.sha256(audio.content).hexdigest()[:16],
                valid_mp3=valid_mp3(audio.content),
                repeat_status=repeat.status_code,
                vendor_attempts=transport.calls,
                text_characters=len(recorded_text(state, "decision", decision.id, config.max_characters)),
            )
            if args.save and audio.status_code == 200:
                args.save.write_bytes(audio.content)
                evidence["saved_to"] = str(args.save)
    ok = (
        evidence["media_status"] == 200
        and evidence["media_type"] == "audio/mpeg"
        and evidence["valid_mp3"]
        and evidence["repeat_status"] == 200
        and evidence["vendor_attempts"] == 1
    )
    evidence["status"] = "verified" if ok else "failed"
    print(json.dumps(evidence, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
