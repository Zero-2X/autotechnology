import pytest

from orchestration.errors import GraphError
from orchestration.feedback import observation_to_feedback
from orchestration.task_bridge import TaskJobGraphMapper
from orchestration.topology import validate_topology


def test_task_job_mapping_preserves_context_and_tenant():
    task = {"id": "task-1", "org_id": "org-a", "status": "queued", "graph_key": "content_pipeline", "workflow_version": 1, "idempotency_key": "job-1", "trace_id": "trace-1", "input_refs": {"signal": "private://signal"}}
    mapped = TaskJobGraphMapper().command(task, org_id="org-a", actor_id="actor-a")
    assert mapped["graph_key"] == "content_pipeline" and mapped["input_refs"]["signal"].startswith("private://")
    with pytest.raises(GraphError): TaskJobGraphMapper().map(task, org_id="org-b")


def test_feedback_graph_requires_account_evidence_for_platform_observation():
    state = {"artifact_refs": {"observation": "private://observation/1"}}
    with pytest.raises(GraphError) as error:
        observation_to_feedback(observation_port=lambda **kwargs: {"source": "platform"}, recommendation_port=lambda **kwargs: {}, state=state, context={"org_id": "org"})
    assert error.value.code == "EXT_ACCOUNT_UNAVAILABLE"
    result = observation_to_feedback(observation_port=lambda **kwargs: {"source": "manual"}, recommendation_port=lambda **kwargs: {"recommendation": "ref://r"}, state=state, context={"org_id": "org"})
    assert result["result_refs"]["recommendation"] == "ref://r"


def test_topology_rejects_cycles_and_has_stable_fingerprint():
    topology = validate_topology({"signal": ["brief"], "brief": ["qa"], "qa": []}, required_nodes=("signal", "qa"))
    assert len(topology["fingerprint"]) == 64
    with pytest.raises(GraphError) as error: validate_topology({"a": ["b"], "b": ["a"]})
    assert error.value.code == "TOPOLOGY_CYCLE"
