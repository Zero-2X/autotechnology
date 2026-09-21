from __future__ import annotations

from uuid import uuid4

import pytest

from orchestration import Checkpoint, GraphDefinition, GraphError, GraphRegistry, GraphRunner, PostgresCheckpointer
from orchestration.state import StateViolation, validate_state


class _Cursor:
    def __init__(self, connection: "_Connection") -> None:
        self.connection = connection
        self.rows = []

    def execute(self, sql: str, params=()):
        normalized = " ".join(sql.split()).lower()
        if normalized.startswith("create table"):
            self.rows = []
        elif normalized.startswith("select sequence from"):
            org_id, run_id = params
            matches = [row for row in self.connection.rows if row[0] == org_id and row[1] == run_id]
            self.rows = [(max((row[2] for row in matches), default=None),)] if matches else []
        elif normalized.startswith("select sequence, state_json"):
            org_id, run_id = params
            matches = [row for row in self.connection.rows if row[0] == org_id and row[1] == run_id]
            matches.sort(key=lambda row: row[2], reverse="desc" in normalized)
            self.rows = [(row[2], row[3], row[4], row[5]) for row in matches[:1]] if "limit 1" in normalized else [
                (row[2], row[3], row[4], row[5]) for row in matches
            ]
        elif normalized.startswith("insert into"):
            org_id, run_id, sequence, state_json, node, created_at = params
            if any(row[:3] == (org_id, run_id, sequence) for row in self.connection.rows):
                raise RuntimeError("duplicate checkpoint")
            self.connection.rows.append((org_id, run_id, sequence, state_json, node, created_at))
        else:
            raise AssertionError(f"unexpected SQL: {sql}")

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)

    def close(self):
        return None


class _Connection:
    def __init__(self) -> None:
        self.rows = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return _Cursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _checkpoint(org_id: str, run_id: str, sequence: int) -> Checkpoint:
    return Checkpoint(
        run_id, org_id, sequence,
        {"run_id": run_id, "org_id": org_id, "workflow_key": "content", "workflow_version": 1,
         "trace_id": "trace", "state_version": 1},
        "node", "2026-09-21T00:00:00Z",
    )


def test_postgres_checkpointer_is_append_only_and_tenant_scoped():
    connection = _Connection()
    store = PostgresCheckpointer(connection)
    org_id, run_id = str(uuid4()), str(uuid4())
    store.save(_checkpoint(org_id, run_id, 1))
    store.save(_checkpoint(org_id, run_id, 2))
    assert store.latest(org_id=org_id, run_id=run_id).sequence == 2
    assert len(store.list(org_id=org_id, run_id=run_id)) == 2
    assert store.latest(org_id=str(uuid4()), run_id=run_id) is None
    with pytest.raises(StateViolation):
        store.save(_checkpoint(org_id, run_id, 2))
    assert connection.rollbacks == 1


def test_graph_runner_honours_injected_kill_switch_before_node_side_effect():
    calls = []
    registry = GraphRegistry()
    registry.register(GraphDefinition("content", 1, nodes=(lambda state: calls.append("called") or {},)))
    runner = GraphRunner(registry, kill_switch=lambda **kwargs: True)
    result = runner.run(org_id=uuid4(), actor_id=uuid4(), graph_key="content", input_refs={},
                        idempotency_key="kill-1", trace_id="trace")
    assert result["status"] == "failed"
    assert result["error_ref"].startswith("error://KILL_SWITCH_ACTIVE/")
    assert calls == []


def test_graph_state_rejects_nested_sensitive_values_and_non_reference_scalars():
    with pytest.raises(StateViolation):
        validate_state({"workflow_key": "x", "workflow_version": 1, "state_version": 1,
                        "retry_context": {"nested": {"token": "secret"}}})
    with pytest.raises(StateViolation):
        validate_state({"workflow_key": "x", "workflow_version": 1, "state_version": 1,
                        "policy_decision_ref": "full-policy-body"})
