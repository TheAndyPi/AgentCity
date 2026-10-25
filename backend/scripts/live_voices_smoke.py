"""Opt-in real dialogue voice verification; default invocation never contacts vendors."""

import argparse
import json
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.infrastructure.config import AppConfig
from app.main import create_app
from app.narration.config import NarrationConfig
from app.narration.transport import valid_mp3
from scripts.narration_smoke import write


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="May bill for two short recorded utterances")
    args = parser.parse_args()
    config = NarrationConfig.from_env()
    configured = bool(
        config.enabled
        and config.api_key
        and config.voice_id
        and config.model_id
        and len(config.character_voice_ids) >= 2
    )
    if not args.live or not configured:
        print(
            json.dumps(
                dict(
                    status="unverified",
                    configured=configured,
                    reason="Explicit --live and two authorized character voices required",
                    configured_voice_count=len(config.character_voice_ids),
                )
            )
        )
        return 2
    with tempfile.TemporaryDirectory(prefix="live-voices-smoke-") as directory:
        app = create_app(AppConfig(data_dir=Path(directory)), config)
        with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
            client.headers["X-CSRF-Token"] = client.get("/api/v1/session").json()["data"]["csrf_token"]
            sid = write(
                client, "/simulations", dict(config=dict(name="Voice verification", population=10, seed=42))
            ).json()["data"]["id"]
            deadline = time.monotonic() + 20
            while app.state.service.heads[sid].simulation.status == "initializing":
                if time.monotonic() > deadline:
                    raise RuntimeError("Verification city initialization timed out")
                time.sleep(0.02)
            speakers = {}
            for _ in range(8):
                state = app.state.service.heads[sid]
                if len(speakers) >= 2:
                    break
                response = write(
                    client,
                    f"/simulations/{sid}/commands",
                    dict(
                        request_id=str(uuid4()),
                        expected_control_version=state.simulation.control_version,
                        command=dict(type="step", count=1),
                    ),
                )
                if response.status_code != 200:
                    raise RuntimeError("Verification city could not step")
                state = app.state.service.heads[sid]
                for line in state.dialogue:
                    speakers.setdefault(line.speaker_id, line)
            if len(speakers) < 2:
                print(json.dumps(dict(status="unverified", reason="Two committed speakers not available")))
                return 2
            evidence, voices = [], []
            for line in list(speakers.values())[:2]:
                voice = app.state.narration.voices.resolve(state, "dialogue", line.id, config)
                voices.append(voice)
                started = time.monotonic()
                path = f"/integrations/narration/v1/simulations/{sid}/dialogue"
                body = dict(source_id=line.id, revision=state.simulation.revision)
                response = write(client, path, body)
                seconds = round(time.monotonic() - started, 3)
                if response.status_code != 200:
                    print(json.dumps(dict(status="failed", error=response.json().get("error", {}))))
                    return 1
                audio = client.get(response.json()["data"]["audio_url"])
                repeat = write(client, path, body)
                evidence.append(
                    dict(
                        cold_seconds=seconds,
                        voice_suffix=voice[-4:],
                        media_status=audio.status_code,
                        valid_mp3=valid_mp3(audio.content),
                        repeat_status=repeat.status_code,
                    )
                )
            ok = len(set(voices)) == 2 and all(
                e["valid_mp3"] and e["media_status"] == e["repeat_status"] == 200 for e in evidence
            )
            print(
                json.dumps(
                    dict(
                        status="verified" if ok else "failed",
                        lines=evidence,
                        vendor_attempts=app.state.narration.transport.calls,
                    ),
                    indent=2,
                )
            )
            return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
