import inspect
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from infra.foundation.platform_contracts import (
    ConnectionPort, InboxPort, MetricsPort, PublisherPort,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "packages/contracts/jsonschema"
ID = "00000000-0000-4000-8000-000000000001"


def validator(name: str) -> Draft202012Validator:
    registry = Registry()
    documents = {}
    for path in SCHEMAS.glob("*.schema.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        documents[path.name] = document
        registry = registry.with_resource(document["$id"], Resource.from_contents(document))
    return Draft202012Validator(documents[name], registry=registry, format_checker=FormatChecker())


def target_version(**changes):
    value = {
        "id": ID, "org_id": ID, "distribution_target_id": ID, "version_no": 1,
        "platform_id": ID, "market": "US", "locale": "en-US", "channel": "article",
        "environment": "dev", "region_profile_version_id": ID,
        "account_profile_id": None, "account_profile_snapshot": {},
        "account_connection_id": None, "account_connection_snapshot": {},
        "synthetic_target_id": "fake-official", "capability_snapshot": {},
        "policy_snapshot_id": ID, "eligible_delivery_modes": ["simulation"],
        "status": "draft", "snapshot_hash": "a" * 64, "etag": "v1",
        "created_by": ID, "created_at": "2026-09-18T00:00:00Z", "retired_at": None,
    }
    return {**value, **changes}


def test_synthetic_target_requires_policy_and_never_requires_connection():
    schema = validator("distribution-target-version.schema.json")
    schema.validate(target_version())
    assert not schema.is_valid(target_version(policy_snapshot_id=None))
    assert not schema.is_valid(target_version(account_connection_id=ID))
    assert not schema.is_valid(target_version(environment="prod"))


def test_planned_target_and_shared_delivery_mode_contracts_are_frozen():
    target = json.loads((SCHEMAS / "distribution-target.schema.json").read_text(encoding="utf-8"))
    assert "planned" in target["properties"]["status"]["enum"]
    intent = json.loads((SCHEMAS / "publication-intent.schema.json").read_text(encoding="utf-8"))
    assert intent["properties"]["delivery_mode"] == {"$ref": "./delivery-mode.schema.json"}


def test_delivery_attempt_bounds_attempts_idempotency_and_adapter_refs():
    schema = json.loads((SCHEMAS / "delivery-attempt.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["attempt_no"]["minimum"] == 1
    assert schema["properties"]["max_attempts"]["minimum"] == 1
    pattern = schema["properties"]["adapter_ref"]["pattern"]
    import re
    assert re.fullmatch(pattern, "manual:export")
    assert re.fullmatch(pattern, "fake:official@v1")
    assert not re.fullmatch(pattern, "fake:official@<version>")


def test_empty_ports_only_define_account_free_interface_shapes():
    expected = {
        ConnectionPort: "inspect",
        PublisherPort: "publish",
        InboxPort: "receive",
        MetricsPort: "emit",
    }
    for port, method in expected.items():
        assert list(port.__dict__).count(method) == 1
        assert "self" in inspect.signature(getattr(port, method)).parameters
