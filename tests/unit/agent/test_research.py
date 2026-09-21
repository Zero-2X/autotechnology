from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest

from modules.agent import AgentError, ResearchAgent, ResearchModelRequest
from modules.agent.research import OUTPUT_REF, OUTPUT_SCHEMA
from modules.model_gateway import FakeModelProvider


class Sources:
    def __init__(self, tenant, snapshot_id) -> None:
        self.value = {
            "id": str(snapshot_id), "org_id": str(tenant), "status": "usable",
            "content_hash": "a" * 64,
            "excerpts": [
                {"locator": "section-1", "quote": "The system records an immutable evidence snapshot."},
                {"locator": "section-2", "quote": "A human reviewer verifies candidate facts."},
            ],
        }
        self.calls = 0

    def get(self, *, org_id, source_snapshot_id):
        self.calls += 1
        return deepcopy(self.value)


def _output(snapshot_id) -> dict:
    return {
        "candidate_facts": [{
            "candidate_key": "immutable_snapshot", "statement": "Evidence snapshots are immutable.",
            "fact_type": "system.behavior", "confidence": 0.86,
            "citations": [{"source_snapshot_id": str(snapshot_id), "locator": "section-1",
                           "quote": "The system records an immutable evidence snapshot."}],
        }],
        "verification_items": [{
            "item_key": "confirm_retention", "question": "How long are snapshots retained?",
            "reason": "The supplied excerpts do not state retention duration.", "priority": "medium",
            "related_candidate_keys": ["immutable_snapshot"],
        }],
        "confidence": 0.82, "needs_review": True,
    }


def _setup(output: dict | None = None):
    tenant, actor, request_id, snapshot_id = (uuid4() for _ in range(4))
    sources = Sources(tenant, snapshot_id)
    values = {
        "research_request_id": str(request_id), "question": "How is evidence handled?",
        "sources": [{"source_snapshot_id": str(snapshot_id), "content_hash": "a" * 64,
                     "excerpts": deepcopy(sources.value["excerpts"])}], "tool_calls": [],
    }
    request = ResearchModelRequest("fake", "research/v1", values, OUTPUT_REF, 2000, 20, "trace", str(tenant))
    provider = FakeModelProvider(fixtures={request.request_hash: output or _output(snapshot_id)},
                                 schema_registry={OUTPUT_REF: OUTPUT_SCHEMA})
    agent = ResearchAgent(sources=sources, model_port=provider)
    args = dict(org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="research",
                research_request_id=request_id, question=values["question"], source_snapshot_ids=[snapshot_id])
    return agent, sources, provider, args, snapshot_id


def test_research_returns_cited_candidates_and_replays_without_writes_or_model_call() -> None:
    agent, sources, provider, args, snapshot_id = _setup()
    result = agent.research(**args)

    assert result["status"] == "needs_review" and result["needs_review"] is True
    assert result["candidate_facts"][0]["citations"][0]["source_snapshot_id"] == str(snapshot_id)
    assert result["candidate_only"] is True
    assert result["claims_created"] is False and result["knowledge_core_mutated"] is False
    assert result["event"]["event_type"] == "agent_run.completed"
    definition = agent.registry.get(org_id=args["org_id"], key="research")
    assert definition.tool_allowlist == () and definition.permissions == ()
    assert provider.call_count == 1
    assert len(agent.ledger.agent_runs) == len(agent.ledger.model_calls) == 1

    result["candidate_facts"][0]["statement"] = "mutated"
    assert agent.research(**args)["candidate_facts"][0]["statement"] == "Evidence snapshots are immutable."
    assert provider.call_count == 1 and sources.calls == 1
    with pytest.raises(AgentError) as error:
        agent.research(**{**args, "question": "Another question"})
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"


def test_research_rejects_foreign_or_unusable_snapshot_before_model() -> None:
    agent, sources, provider, args, _ = _setup()
    sources.value["org_id"] = str(uuid4())
    with pytest.raises(AgentError) as error:
        agent.research(**args)
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    sources.value["org_id"] = str(args["org_id"])
    sources.value["status"] = "captured"
    with pytest.raises(AgentError) as error:
        agent.research(**args)
    assert error.value.code == "RESEARCH_SOURCE_NOT_USABLE"
    assert provider.call_count == 0


def test_research_rejects_citation_not_present_in_controlled_source() -> None:
    agent, sources, provider, args, _ = _setup()
    fixture = next(iter(provider.fixtures.values()))
    fixture["candidate_facts"][0]["citations"][0]["quote"] = "A fabricated quote."
    with pytest.raises(AgentError) as error:
        agent.research(**args)
    assert error.value.code == "RESEARCH_CITATION_INVALID"
    assert next(iter(agent.runner.runs.values())).status == "failed"
    assert not agent.audit and not agent.ledger.agent_runs


def test_research_rejects_claim_write_fields_duplicate_keys_and_unknown_links() -> None:
    agent, sources, provider, args, _ = _setup()
    fixture = next(iter(provider.fixtures.values()))
    fixture["candidate_facts"][0]["knowledge_core_id"] = str(uuid4())
    with pytest.raises(ValueError) as error:
        agent.research(**args)
    assert getattr(error.value, "code", None) == "MODEL_OUTPUT_SCHEMA_INVALID"

    del fixture["candidate_facts"][0]["knowledge_core_id"]
    fixture["candidate_facts"].append(deepcopy(fixture["candidate_facts"][0]))
    with pytest.raises(AgentError) as error:
        agent.research(**args)
    assert error.value.code == "RESEARCH_CANDIDATE_DUPLICATE"

    fixture["candidate_facts"].pop()
    fixture["verification_items"][0]["related_candidate_keys"] = ["missing_candidate"]
    with pytest.raises(AgentError) as error:
        agent.research(**args)
    assert error.value.code == "RESEARCH_ITEM_REFERENCE_INVALID"
