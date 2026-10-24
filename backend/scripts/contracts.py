"""Mechanical initial contract bootstrap, followed by immutable comparison checks.

Normal use: python -m scripts.contracts --check
Bootstrap is intentionally refused once manifest.json exists. Changes after the
baseline require a coordinated contract version update, not automatic regeneration.
"""

import argparse
import hashlib
import inspect
import json
from pathlib import Path

import yaml
from pydantic import TypeAdapter
from pydantic.json_schema import models_json_schema

from app import contracts as c
from app.main import app

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "contracts" / "v1"


def schema_bundle():
    models = sorted(
        {
            value
            for name, value in vars(c).items()
            if inspect.isclass(value)
            and issubclass(value, c.Model)
            and value not in {c.Model, c.Success, c.Page}
        },
        key=lambda model: model.__name__,
    )
    mapping, bundle = models_json_schema(
        [(model, "validation") for model in models], ref_template="#/$defs/{model}"
    )
    bundle["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    bundle["x-contract-version"] = "1.0.0"
    bundle["x-contract-revision"] = 2
    bundle["x-types"] = {model.__name__: mapping[(model, "validation")] for model in models}
    return bundle


def stream_schema():
    schema = TypeAdapter(c.ServerMessage).json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["x-contract-version"] = "1.0.0"
    schema["x-contract-revision"] = 2
    return schema


def json_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")


def check():
    manifest = json.loads((TARGET / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["contract_version"] == "1.0.0"
    assert manifest["snapshot_revision"] == 2
    for name, digest in manifest["sha256"].items():
        assert hashlib.sha256((TARGET / name).read_bytes()).hexdigest() == digest, (
            f"Frozen shared file changed: {name}"
        )
    assert json.loads((TARGET / "schemas.json").read_text(encoding="utf-8")) == schema_bundle(), (
        "DTO schemas drifted from the baseline"
    )
    assert json.loads((TARGET / "stream.schema.json").read_text(encoding="utf-8")) == stream_schema(), (
        "Stream schemas drifted"
    )
    assert yaml.safe_load((TARGET / "openapi.yaml").read_text(encoding="utf-8")) == app.openapi(), (
        "HTTP OpenAPI drifted"
    )
    print(
        f"Contract 1.0.0: {len(manifest['sha256'])} shared file hashes, DTO, OpenAPI and stream snapshots match"
    )


def bootstrap(source):
    if (TARGET / "manifest.json").exists():
        raise SystemExit("Contract baseline already frozen. Request a coordinated version update.")
    TARGET.mkdir(parents=True, exist_ok=True)
    # Preserve the supplied contract verbatim, including its markers and whitespace.
    (TARGET / "CONTRACT.md").write_bytes(Path(source).read_bytes())
    json_write(TARGET / "schemas.json", schema_bundle())
    json_write(TARGET / "stream.schema.json", stream_schema())
    (TARGET / "openapi.yaml").write_text(
        yaml.safe_dump(app.openapi(), sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    from scripts.fixtures import generate

    generate(TARGET / "fixtures")
    hashes = {
        str(path.relative_to(TARGET)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(TARGET.rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    }
    json_write(
        TARGET / "manifest.json",
        dict(
            contract_version="1.0.0",
            snapshot_revision=2,
            schema_draft="2020-12",
            status="frozen",
            sha256=hashes,
        ),
    )
    check()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--bootstrap", metavar="SHARED_CONTRACT_PATH")
    args = parser.parse_args()
    bootstrap(args.bootstrap) if args.bootstrap else check()
