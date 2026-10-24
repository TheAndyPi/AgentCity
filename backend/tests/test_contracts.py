import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import TypeAdapter, ValidationError

from app import contracts as c
from app.prompts.outputs import OUTPUTS

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts" / "v1"
FIXTURES = sorted((CONTRACT / "fixtures").glob("*.json"))


def validator_for(name):
    if name == "ServerMessage":
        return TypeAdapter(c.ServerMessage)
    if name.startswith("Page["):
        return c.Page[getattr(c, name[5:-1])]
    return getattr(c, name)


@pytest.mark.parametrize("path", FIXTURES, ids=lambda path: path.stem)
def test_shared_fixture_python_and_jsonschema_parity(path):
    fixture = json.loads(path.read_text(encoding="utf-8"))
    model = validator_for(fixture["model"])
    schema = model.json_schema() if isinstance(model, TypeAdapter) else model.model_json_schema()
    json_validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    json_accepts = not list(json_validator.iter_errors(fixture["data"]))
    try:
        if isinstance(model, TypeAdapter):
            model.validate_python(fixture["data"])
        else:
            model.model_validate(fixture["data"])
        python_accepts = True
    except ValidationError:
        python_accepts = False
    assert python_accepts == fixture["valid"]
    assert json_accepts == fixture["valid"]


def test_shared_contract_hashes_and_openapi_snapshot():
    from scripts.contracts import check

    check()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), "50", True])
def test_finite_numeric_scalars_and_types(value):
    with pytest.raises(ValidationError):
        c.Metrics(happiness=value, safety=50, trust=50, resources=50, stress=50)


def test_internal_prompt_fixtures():
    fixtures = json.loads((Path(__file__).parent / "fixtures" / "prompts.json").read_text(encoding="utf-8"))
    assert set(fixtures) == set(OUTPUTS)
    for name, payload in fixtures.items():
        OUTPUTS[name].model_validate(payload)
        jsonschema.Draft202012Validator(OUTPUTS[name].model_json_schema()).validate(payload)


def test_all_normative_http_operations_are_present_without_substitutes():
    import re

    from app.main import app

    text = (CONTRACT / "CONTRACT.md").read_text(encoding="utf-8")

    def normalize(path):
        return re.sub(r"\{[^}]+\}", "{}", path)

    expected = {
        (method.lower(), normalize("/api/v1" + path))
        for method, path in re.findall(r"^\| (GET|POST|PUT|DELETE) `([^`]+)`", text, re.MULTILINE)
    }
    actual = {
        (method, normalize(path))
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/api/v1/")
        for method in operations
        if method in {"get", "post", "put", "delete"}
    }
    assert expected == actual
