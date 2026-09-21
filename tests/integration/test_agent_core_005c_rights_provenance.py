from __future__ import annotations

from uuid import UUID, uuid4

from modules.agent import RightsProvenanceAgent, RightsProvenanceModelRequest
from modules.agent.rights_provenance import OUTPUT_REF, OUTPUT_SCHEMA
from modules.model_gateway import FakeModelProvider
from modules.provenance import RightsService, SourceService


STAMP = "2026-09-19T00:00:00Z"


def test_rights_provenance_agent_reads_real_immutable_version_without_authorizing_it() -> None:
    tenant, actor, request_id, record_id = (uuid4() for _ in range(4))
    source = SourceService()
    rights = RightsService(connection=source._connection)
    ingested = source.ingest(
        org_id=tenant, actor_id=actor, trace_id="source", idempotency_key="rights-agent-source",
        source_type="manual", fetch_method="manual", content="Controlled license terms",
        confidence=0.9, captured_at=STAMP,
    )
    snapshot_id = ingested["snapshot"]["id"]
    source.transition_snapshot(
        org_id=tenant, snapshot_id=snapshot_id, actor_id=actor, trace_id="source",
        idempotency_key="rights-agent-quarantine", action="quarantine", expected_version=0,
    )
    source.transition_snapshot(
        org_id=tenant, snapshot_id=snapshot_id, actor_id=actor, trace_id="source",
        idempotency_key="rights-agent-usable", action="mark_usable", expected_version=1,
    )
    created = rights.create_version(
        org_id=tenant, rights_record_id=record_id, actor_id=actor, trace_id="rights",
        idempotency_key="rights-agent-version", source_snapshot_ids=[snapshot_id],
        license_ref="license:controlled", evidence_object_refs=["evidence:owner-email"],
        rights_holder="Example Holder", permitted_regions=["US"], permitted_locales=["en-US"],
        permitted_media=["text"], permitted_use="commercial", terms_snapshot_hash="a" * 64,
        policy_rule_version="rights-policy-v1",
    )
    version = created["version"]
    excerpts = [{
        "evidence_ref": "license:controlled", "locator": "terms:2",
        "quote": "Commercial text use is permitted in the United States.",
    }]
    context, _ = RightsProvenanceAgent._rights_context(
        tenant, record_id, UUID(version["id"]), version,
    )
    values = {
        "analysis_request_id": str(request_id), "rights_context": context,
        "evidence_excerpts": excerpts, "tool_calls": [],
    }
    output = {
        "permission_clues": [{
            "clue_key": "commercial_use", "evidence_ref": "license:controlled",
            "locator": "terms:2", "quote": "Commercial text use is permitted in the United States.",
            "signal": "permit", "normalized_value": "commercial text use; region US", "confidence": 0.9,
        }],
        "scope_candidates": [{
            "scope_key": "region_us", "dimension": "region", "value": "US",
            "evidence_clue_keys": ["commercial_use"], "confidence": 0.9,
        }],
        "gaps": [{
            "gap_key": "missing_expiry", "dimension": "validity",
            "description": "No expiry date appears in the excerpt.", "severity": "high",
            "related_clue_keys": [],
        }],
        "confidence": 0.85, "needs_review": True, "final_rights_decision": "deferred",
    }
    request = RightsProvenanceModelRequest(
        "fake", "rights-provenance/v1", values, OUTPUT_REF, 2000, 20, "trace", str(tenant),
    )
    provider = FakeModelProvider(
        fixtures={request.request_hash: output}, schema_registry={OUTPUT_REF: OUTPUT_SCHEMA},
    )
    agent = RightsProvenanceAgent(rights=rights, model_port=provider)

    result = agent.analyze(
        org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="rights-analysis",
        analysis_request_id=request_id, rights_record_id=record_id,
        rights_record_version_id=version["id"], evidence_excerpts=excerpts,
    )

    persisted = rights.get_version(
        org_id=tenant, rights_record_id=record_id, version_id=version["id"],
    )
    assert result["final_rights_decision"] == "deferred"
    assert result["rights_record_written"] is False and result["rights_status_mutated"] is False
    assert persisted == version and persisted["status"] == "pending"
    assert len(rights.list_versions(org_id=tenant, rights_record_id=record_id)) == 1
    source.close()
