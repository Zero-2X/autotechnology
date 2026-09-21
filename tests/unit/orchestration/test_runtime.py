from datetime import datetime, timezone
import sqlite3
from uuid import uuid4

import pytest

from orchestration import (
    Checkpoint, GraphDefinition, GraphError, GraphInterrupt, GraphRegistry, GraphRunner,
    InMemoryCheckpointer, SQLiteCheckpointer, StateMigration, StateViolation, merge_state,
    migrate_state, validate_state,
)
from orchestration.human import HumanTaskService


def _runner(nodes=()):
    registry = GraphRegistry()
    registry.register(GraphDefinition("content", 1, entrypoint=None, nodes=tuple(nodes)))
    org, actor = uuid4(), uuid4()
    return GraphRunner(registry), org, actor


def test_graph_run_is_idempotent_and_checkpointed():
    def node(state):
        return {"result_refs": {"content": "private://content/1"}}

    runner, org, actor = _runner((node,))
    result = runner.run(org_id=org, actor_id=actor, graph_key="content", input_refs={"signal": "ref://signal/1"},
                        idempotency_key="run-1", trace_id="trace-1")
    assert result["status"] == "succeeded"
    assert runner.run(org_id=org, actor_id=actor, graph_key="content", input_refs={"signal": "ref://signal/1"},
                      idempotency_key="run-1", trace_id="trace-1")["id"] == result["id"]
    assert len(runner.checkpointer.list(org_id=str(org), run_id=result["id"])) == 3
    assert runner.replay(org_id=org, actor_id=actor, run_id=result["id"])["side_effect_replayed"] is False


def test_graph_rejects_sensitive_state_and_keeps_tenant_boundary():
    runner, org, actor = _runner((lambda state: {},))
    with pytest.raises(GraphError) as error:
        runner.run(org_id=org, actor_id=actor, graph_key="content", input_refs={"token": "secret"},
                   idempotency_key="bad", trace_id="t")
    assert error.value.code == "SENSITIVE_STATE_REJECTED"
    good = runner.run(org_id=org, actor_id=actor, graph_key="content", input_refs={}, idempotency_key="good", trace_id="t")
    with pytest.raises(GraphError) as error:
        runner.replay(org_id=uuid4(), actor_id=actor, run_id=good["id"])
    assert error.value.code == "GRAPH_RUN_NOT_FOUND"


def test_interrupt_pause_resume_and_unknown_error_are_structured():
    stateful = {"calls": 0}

    def node(state):
        stateful["calls"] += 1
        if stateful["calls"] == 1:
            raise GraphInterrupt("human://approval/1")
        return {"result_refs": {"approved": "ref://yes"}}

    runner, org, actor = _runner((node,))
    waiting = runner.run(org_id=org, actor_id=actor, graph_key="content", input_refs={}, idempotency_key="wait", trace_id="t")
    assert waiting["status"] == "waiting"
    resumed = runner.resume(org_id=org, actor_id=actor, run_id=waiting["id"], idempotency_key="resume", trace_id="t")
    assert resumed["status"] == "succeeded"

    failing, org2, actor2 = _runner((lambda state: (_ for _ in ()).throw(TimeoutError("slow")),))
    result = failing.run(org_id=org2, actor_id=actor2, graph_key="content", input_refs={}, idempotency_key="timeout", trace_id="t")
    assert result["status"] == "failed"
    assert failing.audit[-1]["payload"]["category"] == "transient"


def test_checkpoint_sqlite_and_state_migration_are_append_only():
    connection = sqlite3.connect(":memory:")
    store = SQLiteCheckpointer(connection)
    run_id, org_id = str(uuid4()), str(uuid4())
    checkpoint = Checkpoint(run_id, org_id, 1, {"run_id": run_id, "org_id": org_id, "workflow_key": "x", "workflow_version": 1, "trace_id": "t", "state_version": 1}, None, "")
    store.save(checkpoint)
    assert store.latest(org_id=org_id, run_id=run_id).sequence == 1
    with pytest.raises(StateViolation): store.save(checkpoint)
    migrated = migrate_state(checkpoint.state, target_version=2, migrations=(StateMigration(1, 2, lambda state: {**state, "status": "running"}),))
    assert migrated["state_version"] == 2
    with pytest.raises(StateViolation): validate_state({"token": "bad"})


def test_parallel_merge_conflict_and_human_task_tenant_isolation():
    base = {"workflow_key": "x", "workflow_version": 1, "state_version": 1}
    with pytest.raises(StateViolation): merge_state(base, {"status": "running"}, {"status": "failed"})
    service = HumanTaskService()
    task = service.interrupt(org_id="org-a", run_id="run-a", task_type="approval", input_refs={"artifact": "ref://a"})
    with pytest.raises(GraphError): service.claim(org_id="org-b", task_id=task.id, actor_id="actor")
    claimed = service.claim(org_id="org-a", task_id=task.id, actor_id="actor")
    assert service.resolve(org_id="org-a", task_id=task.id, actor_id="actor", result_refs={"decision": "ref://approved"}).status == "resolved"


def test_worker_lease_claim_renew_and_conflict():
    runner, org, actor = _runner((lambda state: {},))
    result = runner.run(org_id=org, actor_id=actor, graph_key="content", input_refs={}, idempotency_key="lease", trace_id="t")
    claim = runner.claim(org_id=org, run_id=result["id"], worker_id="worker-a")
    assert claim["worker_id"] == "worker-a"
    with pytest.raises(GraphError) as error:
        runner.claim(org_id=org, run_id=result["id"], worker_id="worker-b")
    assert error.value.code == "LEASE_CONFLICT"
    assert runner.renew(org_id=org, run_id=result["id"], worker_id="worker-a")["worker_id"] == "worker-a"
    runner.release(org_id=org, run_id=result["id"], worker_id="worker-a")
