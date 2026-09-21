from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest

from modules.agent import AgentError, PlannerAgent, PlannerModelRequest
from modules.agent.planner import OUTPUT_REF, OUTPUT_SCHEMA
from modules.model_gateway import FakeModelProvider


class Briefs:
    def __init__(self, brief: dict) -> None:
        self.brief = brief
        self.calls = 0

    def get(self, *, org_id, brief_id):
        self.calls += 1
        return deepcopy(self.brief)


def _setup(output: dict | None = None):
    tenant, actor, brief_id = (uuid4() for _ in range(3))
    brief = {
        "id": str(brief_id), "org_id": str(tenant), "status": "locked",
        "input_snapshot_hash": "a" * 64, "audience": {"role": "engineer"},
        "problem": "Review a retrieval architecture",
    }
    values = {
        "topic_brief_id": str(brief_id), "brief_hash": "a" * 64,
        "goal": "Plan an evidence-backed article", "audience": "engineer",
        "problem": brief["problem"], "tool_calls": [],
    }
    request = PlannerModelRequest("fake", "planner/v1", values, OUTPUT_REF, 1000, 10, "trace", str(tenant))
    result = output or {
        "topic_plan": {"topic_brief_id": str(brief_id), "angle": "Trade-offs in retrieval",
                       "key_questions": ["How is evidence checked?"]},
        "workflow_plan": {"workflow_key": "canonical_content_draft", "steps": [
            {"step_key": "evidence_review", "purpose": "Review evidence", "depends_on": []},
            {"step_key": "outline", "purpose": "Prepare an outline", "depends_on": ["evidence_review"]},
            {"step_key": "human_review", "purpose": "Review the draft", "depends_on": ["outline"]},
        ]},
        "confidence": 0.9, "needs_review": False,
    }
    provider = FakeModelProvider(fixtures={request.request_hash: result}, schema_registry={OUTPUT_REF: OUTPUT_SCHEMA})
    briefs = Briefs(brief)
    planner = PlannerAgent(topic_briefs=briefs, model_port=provider)
    args = dict(org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="plan",
                topic_brief_id=brief_id, goal=values["goal"])
    return planner, briefs, provider, args


def test_planner_emits_only_structured_plan_and_replays_without_model_call() -> None:
    planner, briefs, provider, args = _setup()
    result = planner.plan(**args)
    assert result["status"] == "succeeded"
    assert result["workflow_plan"]["workflow_key"] == "canonical_content_draft"
    assert planner.registry.get(org_id=args["org_id"], key="planner").tool_allowlist == ()
    assert provider.call_count == 1
    assert len(planner.ledger.agent_runs) == len(planner.ledger.model_calls) == 1
    assert planner.audit[0]["actor_id"] == str(args["actor_id"])
    assert "prompt" not in vars(next(iter(planner.ledger.model_calls.values())))
    result["topic_plan"]["angle"] = "mutated"
    assert planner.plan(**args)["topic_plan"]["angle"] == "Trade-offs in retrieval"
    assert provider.call_count == 1
    with pytest.raises(AgentError) as error:
        planner.plan(**{**args, "goal": "A different goal"})
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"
    assert provider.call_count == 1


def test_planner_rejects_foreign_or_unlocked_brief_before_model() -> None:
    planner, briefs, provider, args = _setup()
    briefs.brief["org_id"] = str(uuid4())
    with pytest.raises(AgentError) as error:
        planner.plan(**args)
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    briefs.brief["org_id"] = str(args["org_id"])
    briefs.brief["status"] = "draft"
    with pytest.raises(AgentError) as error:
        planner.plan(**args)
    assert error.value.code == "PLANNER_BRIEF_NOT_LOCKED"
    assert provider.call_count == 0


def test_planner_rejects_duplicate_or_unavailable_dependency() -> None:
    planner, briefs, provider, args = _setup()
    request_hash = next(iter(provider.fixtures))
    bad = deepcopy(provider.fixtures[request_hash])
    bad["workflow_plan"]["steps"][1]["depends_on"] = ["human_review"]
    provider.fixtures[request_hash] = bad
    with pytest.raises(AgentError) as error:
        planner.plan(**args)
    assert error.value.code == "PLANNER_DEPENDENCY_INVALID"
    assert next(iter(planner.runner.runs.values())).status == "failed"
    assert not planner.audit


def test_planner_rejects_action_fields_and_marks_low_confidence_for_review() -> None:
    planner, briefs, provider, args = _setup()
    request_hash = next(iter(provider.fixtures))
    bad = deepcopy(provider.fixtures[request_hash])
    bad["publish_now"] = True
    provider.fixtures[request_hash] = bad
    with pytest.raises(ValueError) as error:
        planner.plan(**args)
    assert getattr(error.value, "code", None) == "MODEL_OUTPUT_SCHEMA_INVALID"
    provider.fixtures[request_hash] = deepcopy(bad)
    del provider.fixtures[request_hash]["publish_now"]
    provider.fixtures[request_hash]["confidence"] = 0.3
    result = planner.plan(**args)
    assert result["status"] == "needs_review"
    assert result["needs_review"] is True
