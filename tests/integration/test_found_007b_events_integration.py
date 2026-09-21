from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
import json
from urllib.parse import urljoin

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource

import yaml

from infra.foundation.outbox import EventEnvelope

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "docs/contracts/event-registry.yaml"


def test_event_envelope_matches_registered_event_boundary() -> None:
    registry = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    event_type = registry["events"][0]["event_type"]
    aggregate_id = str(uuid4())
    envelope = EventEnvelope.create(
        event_type=event_type,
        event_schema_version=1,
        occurred_at=datetime.now(timezone.utc),
        org_id=str(uuid4()),
        trace_id="trace-found-007b",
        aggregate_type="TopicOpportunity",
        aggregate_id=aggregate_id,
        aggregate_version=1,
        actor_type="service",
        idempotency_key="found-007b-event",
        payload={"aggregate_id": aggregate_id, "aggregate_version": 1},
    )
    contract = envelope.as_contract()
    assert contract["event_type"] == event_type
    assert contract["event_schema_version"] == 1
    assert len(contract["payload_hash"]) == 64
    assert contract["org_id"]
    envelope_schema = json.loads((ROOT / "packages/contracts/events/event-envelope.schema.json").read_text(encoding="utf-8"))
    for entry in registry["events"]:
        schema = json.loads((ROOT / entry["schema_ref"]).read_text(encoding="utf-8"))
        resolver = Registry().with_resource(
            urljoin(schema["$id"], "./event-envelope.schema.json"), Resource.from_contents(envelope_schema)
        )
        validator = Draft202012Validator(schema, registry=resolver, format_checker=FormatChecker())
        fixture = {**contract, "event_type": entry["event_type"]}
        if entry["event_type"] == "topic_signal.rejected":
            payload = {**contract["payload"], "line_number": 1,
                       "reason_code": "INVALID_CONFIDENCE", "input_hash": "a" * 64}
            fixture = {**fixture, "payload": payload,
                       "payload_hash": sha256(json.dumps(payload, sort_keys=True,
                                                         separators=(",", ":")).encode()).hexdigest()}
        validator.validate(fixture)
        with pytest.raises(ValidationError):
            validator.validate({**fixture, "org_id": "invalid-uuid"})
        with pytest.raises(ValidationError):
            validator.validate({**fixture, "payload": {"aggregate_id": aggregate_id, "aggregate_version": "1"}})
