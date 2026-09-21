import json
from pathlib import Path
from copy import deepcopy

import pytest

from infra.foundation.agent_output import AgentOutputError, AgentOutputRegistry


SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "packages/contracts/jsonschema/agent-output.schema.json").read_text())


def registry():
    result = AgentOutputRegistry()
    result.register("agent-output", 1, SCHEMA)
    return result


def valid():
    return {"schema_version": 1, "status": "draft", "result": {"summary": "Synthetic draft", "artifact_refs": []}, "issues": [], "metadata": {"limitations": []}}


@pytest.mark.parametrize("change", [
    lambda v: v.update(debug=True),
    lambda v: v["result"].update(debug=True),
    lambda v: v["metadata"].update(debug=True),
    lambda v: v.update(status="approved"),
    lambda v: v.update(status="published"),
    lambda v: v.update(schema_version=2),
    lambda v: v.update(issues=[12]),
    lambda v: v["result"].update(artifact_refs=[{}]),
    lambda v: v.pop("status"),
])
def test_invalid_output_is_rejected(change):
    value = valid()
    change(value)
    with pytest.raises(AgentOutputError):
        registry().validate("agent-output", value, 1)


def test_unknown_version_and_immutable_registration():
    r = registry()
    for version in (2, True, "1"):
        with pytest.raises(AgentOutputError):
            r.validate("agent-output", valid(), version)
    with pytest.raises(AgentOutputError, match="immutable"):
        r.register("agent-output", 1, SCHEMA)


def version_two(r):
    schema = deepcopy(SCHEMA)
    schema["properties"]["schema_version"]["const"] = 2
    r.register("agent-output", 2, schema)


def test_explicit_migration_validates_both_versions_without_mutation():
    r = registry()
    version_two(r)
    value = valid()
    r.register_migration("agent-output", 1, 2, lambda v: {**v, "schema_version": 2})
    assert r.migrate("agent-output", value, 1, 2)["schema_version"] == 2
    assert value == valid()
    value["debug"] = True
    with pytest.raises(AgentOutputError):
        r.migrate("agent-output", value, 1, 2)


def test_missing_invalid_and_downgrade_migrations():
    r = registry()
    version_two(r)
    with pytest.raises(AgentOutputError, match="missing"):
        r.migrate("agent-output", valid(), 1, 2)
    with pytest.raises(AgentOutputError, match="downgrade"):
        r.migrate("agent-output", valid(), 1, 0)
    r.register_migration("agent-output", 1, 2, lambda v: v)
    with pytest.raises(AgentOutputError, match="const"):
        r.migrate("agent-output", valid(), 1, 2)


def test_validated_output_is_detached():
    value = valid()
    result = registry().validate("agent-output", value, 1)
    result["result"]["artifact_refs"].append("synthetic")
    assert value == valid()


def test_schema_snapshot_is_detached_and_version_pinned():
    schema = deepcopy(SCHEMA)
    r = AgentOutputRegistry()
    with pytest.raises(AgentOutputError, match="pinned"):
        r.register("agent-output", 2, schema)
    r.register("agent-output", 1, schema)
    schema["properties"]["status"]["enum"].append("published")
    with pytest.raises(AgentOutputError):
        r.validate("agent-output", {**valid(), "status": "published"}, 1)


def test_external_refs_are_never_fetched_and_values_are_not_in_error():
    schema = deepcopy(SCHEMA)
    schema["properties"]["result"] = {"$ref": "https://invalid.example/output.json"}
    r = AgentOutputRegistry()
    r.register("agent-output", 1, schema)
    with pytest.raises(AgentOutputError, match="offline"):
        r.validate("agent-output", valid(), 1)
    with pytest.raises(AgentOutputError) as caught:
        registry().validate("agent-output", {**valid(), "status": "sensitive-content"}, 1)
    assert "sensitive-content" not in str(caught.value)


def test_full_path_checked_before_migration_and_duplicate_rejected():
    r = registry()
    version_two(r)
    calls = []
    def migrate(value):
        calls.append(True)
        return {**value, "schema_version": 2}
    r.register_migration("agent-output", 1, 2, migrate)
    with pytest.raises(AgentOutputError, match="missing"):
        r.migrate("agent-output", valid(), 1, 3)
    assert calls == []
    with pytest.raises(AgentOutputError, match="duplicate"):
        r.register_migration("agent-output", 1, 2, migrate)
    assert r.migrate("agent-output", valid(), 1, 1) == valid()
