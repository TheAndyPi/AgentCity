"""Opt-in original disaster media. --live admits up to four paid generations."""

import argparse
import hashlib
import json
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.contracts import Vec2
from app.disasters.models import Parameters
from app.infrastructure.config import AppConfig
from app.main import create_app
from app.narration.config import NarrationConfig
from app.narration.disaster import mp3_seconds
from app.narration.transport import valid_mp3
from scripts.narration_smoke import write


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--live",
        action="store_true",
        help="May bill for one effect, one music bed and two assigned-voice reactions",
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts/disaster-audio"))
    args = parser.parse_args()
    cfg = NarrationConfig.from_env()
    configured = bool(cfg.enabled and cfg.api_key and cfg.voice_id and cfg.model_id)
    flags = {k: getattr(cfg, f"disaster_{k}") for k in ("effects", "music", "reactions")}
    if not args.live or not configured:
        print(
            json.dumps(
                dict(
                    status="unverified",
                    configured=configured,
                    categories=flags,
                    configured_voice_count=len(cfg.character_voice_ids),
                    reason="Explicit --live and configured categories/authorized voices required; no paid calls made",
                )
            )
        )
        return 2
    args.output.mkdir(parents=True, exist_ok=True)
    evidence = []
    with tempfile.TemporaryDirectory(prefix="disaster-audio-smoke-") as directory:
        app = create_app(AppConfig(data_dir=Path(directory), base_tps=0.01), cfg)
        with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
            client.headers["X-CSRF-Token"] = client.get("/api/v1/session").json()["data"]["csrf_token"]
            sid = write(
                client,
                "/simulations",
                dict(config=dict(name="Disaster media verification", population=10, seed=42)),
            ).json()["data"]["id"]
            deadline = time.monotonic() + 20
            while app.state.service.heads[sid].simulation.status == "initializing":
                if time.monotonic() > deadline:
                    raise RuntimeError("Verification city initialization timed out")
                time.sleep(0.02)

            def current():
                return app.state.service.heads[sid]

            hold = write(
                client,
                f"/simulations/{sid}/interventions",
                dict(expected_control_version=current().simulation.control_version),
            ).json()["data"]
            p = Parameters(
                kind="fire",
                intensity=100.0,
                extent_m=150.0,
                origin=Vec2(x=64, y=64),
                duration_ticks=100,
                seed=42,
            )
            base = f"/integrations/disasters/v2/simulations/{sid}"
            preview = write(
                client, base + "/previews", dict(intervention_id=hold["id"], parameters=p.model_dump())
            ).json()["data"]
            committed = write(
                client,
                base + "/commits",
                dict(
                    intervention_id=hold["id"],
                    preview_id=preview["preview"]["id"],
                    expected_control_version=hold["control_version"],
                ),
            )
            if committed.status_code != 201:
                raise RuntimeError("Verification disaster could not commit")
            for kind in ("step", "play"):
                body = dict(
                    request_id=str(uuid4()),
                    expected_control_version=current().simulation.control_version,
                    command=dict(type=kind, **({"count": 1} if kind == "step" else {})),
                )
                result = write(client, f"/simulations/{sid}/commands", body)
                if result.status_code != 200:
                    raise RuntimeError("Verification disaster could not activate")
            event = next(r for r in current().events.values() if r.physical)
            sources = [("effects", event.summary.id), ("music", event.summary.id)]
            sources += [("reactions", r.id) for r in current().reactions[:2]]
            for index, (category, source) in enumerate(sources):
                if not flags[category]:
                    evidence.append(dict(category=category, status="unconfigured"))
                    continue
                started = time.monotonic()
                result = write(
                    client,
                    f"/integrations/narration/v2/simulations/{sid}/disaster-audio",
                    dict(source_id=source, category=category, revision=current().simulation.revision),
                )
                if result.status_code != 200:
                    evidence.append(
                        dict(category=category, status="unavailable", http_status=result.status_code)
                    )
                    continue
                data = result.json()["data"]
                media = client.get(data["audio_url"])
                valid = media.status_code == 200 and valid_mp3(media.content)
                path = args.output / f"{index}-{category}.mp3"
                if valid:
                    path.write_bytes(media.content)
                evidence.append(
                    dict(
                        category=category,
                        status="audition_required" if valid else "invalid",
                        seconds=mp3_seconds(media.content) if valid else None,
                        latency_seconds=round(time.monotonic() - started, 3),
                        sha256=hashlib.sha256(media.content).hexdigest() if valid else None,
                        path=str(path) if valid else None,
                        manifest=data["manifest"],
                    )
                )
    report = dict(
        status="audition_required",
        samples=evidence,
        note="Listen for related effects, scary instrumental music, expressive distinct voices, no spoken tags, and acceptable levels. Valid bytes alone do not verify sound quality.",
    )
    (args.output / "provenance.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
