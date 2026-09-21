from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

from modules.agent import ResearchAgent, ResearchModelRequest
from modules.agent.research import OUTPUT_REF, OUTPUT_SCHEMA
from modules.model_gateway import FakeModelProvider
from modules.provenance import SourceService


STAMP = "2026-09-19T00:00:00Z"


class SourceMaterials:
    def __init__(self, service: SourceService, excerpts: list[dict]) -> None:
        self.service = service
        self.excerpts = excerpts

    def get(self, *, org_id, source_snapshot_id):
        return {**self.service.get_snapshot(org_id=org_id, snapshot_id=source_snapshot_id),
                "excerpts": deepcopy(self.excerpts)}


def test_research_agent_uses_real_usable_source_snapshot_without_creating_knowledge() -> None:
    tenant, actor, request_id = (uuid4() for _ in range(3))
    source_service = SourceService()
    ingested = source_service.ingest(
        org_id=tenant, actor_id=actor, trace_id="source", idempotency_key="source-ingest",
        source_type="manual", fetch_method="manual", content="Controlled evidence text",
        confidence=0.9, captured_at=STAMP,
    )
    snapshot_id = ingested["snapshot"]["id"]
    source_service.transition_snapshot(
        org_id=tenant, snapshot_id=snapshot_id, actor_id=actor, trace_id="source",
        idempotency_key="source-quarantine", action="quarantine", expected_version=0,
    )
    usable = source_service.transition_snapshot(
        org_id=tenant, snapshot_id=snapshot_id, actor_id=actor, trace_id="source",
        idempotency_key="source-usable", action="mark_usable", expected_version=1,
    )["snapshot"]
    excerpts = [{"locator": "manual:1", "quote": "Controlled evidence text"}]
    values = {
        "research_request_id": str(request_id), "question": "What does the source state?",
        "sources": [{"source_snapshot_id": snapshot_id, "content_hash": usable["content_hash"],
                     "excerpts": excerpts}], "tool_calls": [],
    }
    output = {
        "candidate_facts": [{
            "candidate_key": "controlled_text", "statement": "The source contains controlled evidence text.",
            "fact_type": "source.content", "confidence": 0.9,
            "citations": [{"source_snapshot_id": snapshot_id, "locator": "manual:1",
                           "quote": "Controlled evidence text"}],
        }],
        "verification_items": [], "confidence": 0.9, "needs_review": True,
    }
    request = ResearchModelRequest("fake", "research/v1", values, OUTPUT_REF, 2000, 20, "trace", str(tenant))
    provider = FakeModelProvider(fixtures={request.request_hash: output}, schema_registry={OUTPUT_REF: OUTPUT_SCHEMA})
    agent = ResearchAgent(sources=SourceMaterials(source_service, excerpts), model_port=provider)

    result = agent.research(
        org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="research",
        research_request_id=request_id, question=values["question"], source_snapshot_ids=[snapshot_id],
    )

    assert result["candidate_facts"][0]["citations"][0]["source_snapshot_id"] == snapshot_id
    assert result["claims_created"] is False and result["knowledge_core_mutated"] is False
    assert source_service.get_snapshot(org_id=tenant, snapshot_id=snapshot_id)["status"] == "usable"
    source_service.close()
