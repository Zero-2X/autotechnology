from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import traceback
from urllib.parse import urljoin
from uuid import uuid4

import pytest
import yaml

from infra.foundation.event_validation import EventSchemaRegistry, EventValidationError
from infra.foundation.outbox import EventEnvelope

ROOT = Path(__file__).resolve().parents[2]


def fixture():
    schema = json.loads((ROOT / "packages/contracts/events/topic-opportunity-scored.schema.json").read_text(encoding="utf-8"))
    envelope = json.loads((ROOT / "packages/contracts/events/event-envelope.schema.json").read_text(encoding="utf-8"))
    resources = {urljoin(schema["$id"], "./event-envelope.schema.json"): envelope}
    aggregate_id = str(uuid4())
    event = EventEnvelope.create(
        event_type="topic.opportunity.scored", event_schema_version=1,
        occurred_at=datetime.now(timezone.utc), org_id=str(uuid4()),
        trace_id="synthetic-trace", aggregate_type="TopicOpportunity", aggregate_id=aggregate_id,
        aggregate_version=1, actor_type="service", idempotency_key="synthetic-event",
        payload={"aggregate_id": aggregate_id, "aggregate_version": 1},
    ).as_contract()
    return schema, resources, event


def test_versions_select_independent_immutable_schema_and_dependency_snapshots():
    schema, resources, event = fixture()
    registry = EventSchemaRegistry()
    registry.register(event["event_type"], 1, schema, resources=resources)
    v2 = deepcopy(schema)
    v2["$id"] = v2["$id"].replace(".schema", "-v2.schema")
    props = v2["allOf"][1]["properties"]
    props["event_schema_version"]["const"] = 2
    props["payload"]["required"].append("score")
    props["payload"]["properties"]["score"] = {"type": "number", "minimum": 0}
    registry.register(event["event_type"], 2, v2, resources=resources)
    assert registry.validate(event) == event
    with pytest.raises(EventValidationError):
        registry.validate({**event, "event_schema_version": 2})
    event2 = {**event, "event_schema_version": 2, "payload": {**event["payload"], "score": 0.5}}
    assert registry.validate(event2) == event2
    schema["allOf"] = []
    next(iter(resources.values()))["properties"]["org_id"] = True
    assert registry.validate(event) == event
    with pytest.raises(EventValidationError):
        registry.validate({**event, "org_id": "bad"})
    with pytest.raises(EventValidationError, match="immutable"):
        registry.register(event["event_type"], 1, v2, resources=resources)
    returned = registry.validate(event)
    returned["payload"]["aggregate_version"] = 9
    assert event["payload"]["aggregate_version"] == 1


@pytest.mark.parametrize("version", [True, 0, -1, 1.0, "1", 3, None])
def test_invalid_or_unknown_versions_never_fall_back(version):
    schema, resources, event = fixture()
    registry = EventSchemaRegistry()
    registry.register(event["event_type"], 1, schema, resources=resources)
    with pytest.raises(EventValidationError):
        registry.validate({**event, "event_schema_version": version})


def test_all_registered_events_are_parsed_by_type_and_version():
    _, resources, event = fixture()
    entries = yaml.safe_load((ROOT / "docs/contracts/event-registry.yaml").read_text(encoding="utf-8"))["events"]
    registry = EventSchemaRegistry()
    for entry in entries:
        schema = json.loads((ROOT / entry["schema_ref"]).read_text(encoding="utf-8"))
        registry.register(entry["event_type"], 1, schema, resources=resources)
    for entry in entries:
        value = {**event, "event_type": entry["event_type"]}
        if entry["event_type"] == "topic_signal.rejected":
            payload = {**event["payload"], "line_number": 1,
                       "reason_code": "INVALID_CONFIDENCE", "input_hash": "a" * 64}
            payload_hash = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            value = {**value, "payload": payload, "payload_hash": payload_hash}
        assert registry.validate(value) == value
        with pytest.raises(EventValidationError):
            registry.validate({**value, "payload": {"aggregate_id": "bad"}})


def test_dependencies_resolve_offline_including_nested_id_and_recursive_refs():
    schema, resources, event = fixture()
    uri = urljoin(schema["$id"], "tree.schema.json")
    resources[uri] = {"$schema": schema["$schema"], "$id": uri, "type": "object",
                      "properties": {"value": {"type": "integer"}, "child": {"$ref": "#"}}}
    payload = schema["allOf"][1]["properties"]["payload"]
    payload["properties"]["tree"] = {"$id": "nested/child.schema.json", "$ref": "../tree.schema.json"}
    registry = EventSchemaRegistry()
    registry.register(event["event_type"], 1, schema, resources=resources)
    event["payload"]["tree"] = {"value": 1, "child": {"value": 2}}
    assert registry.validate(event) == event
    event["payload"]["tree"]["child"]["value"] = "bad"
    with pytest.raises(EventValidationError):
        registry.validate(event)


@pytest.mark.parametrize("ref", ["https://not-allowed.invalid/schema", "./missing.json", "#/$defs/missing"])
def test_unresolved_refs_are_rejected_even_in_absent_optional_fields(ref):
    schema, resources, event = fixture()
    schema["allOf"][1]["properties"]["payload"]["properties"]["optional"] = {"$ref": ref}
    registry = EventSchemaRegistry()
    with pytest.raises(EventValidationError, match="offline"):
        registry.register(event["event_type"], 1, schema, resources=resources)
    with pytest.raises(EventValidationError, match="unsupported"):
        registry.validate(event)


def test_payload_errors_do_not_leak_values_in_traceback():
    schema, resources, event = fixture()
    registry = EventSchemaRegistry()
    registry.register(event["event_type"], 1, schema, resources=resources)
    event["org_id"] = "SYNTHETIC_PRIVATE_MARKER"
    try:
        registry.validate(event)
    except EventValidationError:
        assert "SYNTHETIC_PRIVATE_MARKER" not in traceback.format_exc()
    else:
        pytest.fail("invalid UUID accepted")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_json_numbers_rejected(value):
    schema, resources, event = fixture()
    registry = EventSchemaRegistry()
    registry.register(event["event_type"], 1, schema, resources=resources)
    event["payload"]["score"] = value
    with pytest.raises(EventValidationError):
        registry.validate(event)
