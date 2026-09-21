from copy import deepcopy
import traceback

import pytest

from infra.foundation.observation_contract import ObservationContractError, validate_observation

ORG = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-000000000002"


def records(kind="number", value=1, rules=None):
    definition = {
        "id": ORG, "org_id": ORG, "key": "synthetic", "version_no": 1,
        "metric_type": kind, "unit": "count", "formula": "identity",
        "dimensions": [], "window": "daily", "data_source": "fake",
        "dedupe_rule": "id", "quality_rules": rules or {}, "owner_actor_id": None,
        "status": "active", "effective_at": None, "retired_at": None, "snapshot_hash": "a" * 64,
    }
    observation = {
        "id": ORG, "org_id": ORG, "source": "fake", "subject_type": "topic",
        "subject_id": ORG, "metric_definition_id": ORG, "metric_definition_version_no": 1,
        "metric_name": "synthetic", "metric_type": kind, "metric_value": value,
        "observed_at": "2026-09-16T00:00:00Z", "locale": None, "region": None,
        "data_quality": "estimated", "dedupe_key": "synthetic", "source_snapshot_ref": None,
        "observation_version": 1,
    }
    return observation, definition


def test_tenant_and_global_definitions():
    observation, definition = records()
    assert validate_observation(observation, definition, org_id=ORG) == observation
    definition["org_id"] = None
    assert validate_observation(observation, definition, org_id=ORG) == observation


@pytest.mark.parametrize("record,field,value", [
    (0, "org_id", OTHER), (1, "org_id", OTHER), (1, "id", OTHER),
    (1, "version_no", 2), (1, "key", "wrong"), (1, "metric_type", "string"),
    (0, "metric_value", float("nan")), (0, "metric_value", float("inf")),
])
def test_rejects_wrong_binding_and_non_json_values(record, field, value):
    pair = records()
    pair[record][field] = value
    with pytest.raises(ObservationContractError):
        validate_observation(*pair, org_id=ORG)


def test_json_value_schema_validates_nested_values_and_returns_copy():
    schema = {"type": "object", "properties": {"count": {"type": "integer", "minimum": 0}},
              "required": ["count"], "additionalProperties": False}
    observation, definition = records("json", {"count": 3}, {"value_schema": schema})
    original = deepcopy(observation)
    result = validate_observation(observation, definition, org_id=ORG)
    result["metric_value"]["count"] = 5
    assert observation == original
    for value in ({"count": -1}, {"count": True}, {"extra": 1}, {"count": 2, "extra": 1}):
        observation["metric_value"] = value
        with pytest.raises(ObservationContractError):
            validate_observation(observation, definition, org_id=ORG)


@pytest.mark.parametrize("schema", [None, {}, {"description": "unconstrained"},
    {"type": "not-a-type"}, {"$ref": "https://invalid.example/schema"}])
def test_json_requires_usable_offline_value_schema(schema):
    pair = records("json", {}, {"value_schema": schema} if schema is not None else {})
    with pytest.raises(ObservationContractError):
        validate_observation(*pair, org_id=ORG)


def test_enum_membership_is_enforced():
    observation, definition = records("enum", "good", {"value_schema": {"enum": ["good", "bad"]}})
    validate_observation(observation, definition, org_id=ORG)
    observation["metric_value"] = "unlisted"
    with pytest.raises(ObservationContractError):
        validate_observation(observation, definition, org_id=ORG)


def test_rejection_traceback_does_not_echo_metric_value():
    observation, definition = records(value="private-fixture-value")
    with pytest.raises(ObservationContractError) as caught:
        validate_observation(observation, definition, org_id=ORG)
    assert "private-fixture-value" not in "".join(traceback.format_exception(caught.value))
