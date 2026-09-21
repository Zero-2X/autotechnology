from __future__ import annotations

import sqlite3
from datetime import timedelta
from uuid import uuid4

import pytest

from modules.knowledge import KnowledgeError, KnowledgeService
from modules.provenance import SourceService


def _source_fixture() -> tuple[SourceService, object, object, str]:
    source = SourceService()
    org_id, actor_id = uuid4(), uuid4()
    captured = source.ingest(
        org_id=org_id,
        actor_id=actor_id,
        trace_id="knowledge-trace",
        idempotency_key="knowledge-source-1",
        source_type="url",
        canonical_url="https://knowledge.example/source",
        content={"body": "A source for a knowledge fact."},
    )
    snapshot_id = captured["snapshot"]["id"]
    source.transition_snapshot(
        org_id=org_id,
        snapshot_id=snapshot_id,
        actor_id=actor_id,
        trace_id="knowledge-trace",
        idempotency_key="knowledge-source-2",
        action="quarantine",
        expected_version=0,
    )
    source.transition_snapshot(
        org_id=org_id,
        snapshot_id=snapshot_id,
        actor_id=actor_id,
        trace_id="knowledge-trace",
        idempotency_key="knowledge-source-3",
        action="mark_usable",
        expected_version=1,
    )
    return source, org_id, actor_id, snapshot_id


def test_entity_claim_evidence_lifecycle_is_idempotent_and_tenant_scoped() -> None:
    source, org_id, actor_id, snapshot_id = _source_fixture()
    knowledge = KnowledgeService(connection=source._connection)
    try:
        entity_request = {
            "org_id": org_id,
            "actor_id": actor_id,
            "trace_id": "knowledge-trace",
            "idempotency_key": "knowledge-entity-1",
            "canonical_name": "OpenAI",
            "aliases": ["OpenAI", "OpenAI, Inc."],
            "entity_type": "organization",
        }
        created_entity = knowledge.create_entity(**entity_request)
        assert knowledge.create_entity(**entity_request) == created_entity
        entity = created_entity["entity"]
        assert entity["status"] == "draft"
        assert entity["entity_type"] == "organization"

        claim = knowledge.create_claim(
            org_id=org_id,
            actor_id=actor_id,
            trace_id="knowledge-trace",
            idempotency_key="knowledge-claim-1",
            entity_ids=[entity["id"]],
            statement="The source describes an organization.",
            fact_type="identity",
            applicable_versions=["2026.09"],
            applicable_regions=["US", "EU"],
            applicable_locales=["en-US"],
            valid_from="2026-01-01T00:00:00Z",
            valid_to="2026-12-31T00:00:00Z",
            review_due_at="2026-10-01T00:00:00Z",
        )
        claim_value = claim["claim"]
        assert claim_value["fact_type"] == "identity"
        assert knowledge.list_claims(org_id=org_id, entity_id=entity["id"])[0]["id"] == claim_value["id"]

        evidence_request = {
            "org_id": org_id,
            "actor_id": actor_id,
            "trace_id": "knowledge-trace",
            "idempotency_key": "knowledge-evidence-1",
            "source_snapshot_id": snapshot_id,
            "claim_id": claim_value["id"],
            "quote": "A source for a knowledge fact.",
            "locator": "paragraph:1",
            "evidence_type": "quote",
            "applicable_versions": ["2026.09"],
            "applicable_regions": ["US"],
            "applicable_locales": ["en-US"],
            "valid_from": "2026-01-01T00:00:00Z",
            "valid_to": "2026-12-31T00:00:00Z",
        }
        evidence = knowledge.create_evidence(**evidence_request)
        assert knowledge.create_evidence(**{**evidence_request, "trace_id": "different-trace"}) == evidence

        with pytest.raises(KnowledgeError, match="valid evidence") as verify_error:
            knowledge.verify_claim(
                org_id=org_id,
                claim_id=claim_value["id"],
                actor_id=actor_id,
                trace_id="knowledge-trace",
                idempotency_key="knowledge-claim-verify-before-evidence",
                expected_version=0,
            )
        assert verify_error.value.code == "CLAIM_EVIDENCE_REQUIRED"

        validated = knowledge.validate_evidence(
            org_id=org_id,
            evidence_id=evidence["evidence"]["id"],
            actor_id=actor_id,
            trace_id="knowledge-trace",
            idempotency_key="knowledge-evidence-validate",
            expected_version=0,
        )
        assert validated["evidence"]["status"] == "valid"
        verified = knowledge.verify_claim(
            org_id=org_id,
            claim_id=claim_value["id"],
            actor_id=actor_id,
            trace_id="knowledge-trace",
            idempotency_key="knowledge-claim-verify",
            expected_version=0,
        )
        assert verified["claim"]["status"] == "verified"
        freshened = knowledge.mark_claim_freshness(
            org_id=org_id,
            claim_id=claim_value["id"],
            actor_id=actor_id,
            trace_id="knowledge-trace",
            idempotency_key="knowledge-claim-freshness",
            freshness_status="review_due",
            expected_version=1,
            reason="scheduled review",
        )
        assert freshened["claim"]["freshness_status"] == "review_due"
        assert freshened["claim"]["version"] == 2
        assert [event["event_type"] for event in knowledge.events(org_id=org_id, aggregate_id=claim_value["id"])] == [
            "claim.created",
            "claim.verified",
            "claim.freshness.changed",
        ]

        with pytest.raises(KnowledgeError) as cross_tenant:
            knowledge.get_claim(org_id=uuid4(), claim_id=claim_value["id"])
        assert cross_tenant.value.code == "TENANT_SCOPE_VIOLATION"
        with pytest.raises(KnowledgeError) as reused:
            knowledge.create_entity(**{**entity_request, "canonical_name": "A different name"})
        assert reused.value.code == "IDEMPOTENCY_KEY_REUSED"

        with pytest.raises(sqlite3.DatabaseError):
            knowledge.connection.execute(
                "DELETE FROM claim_evidences WHERE org_id = ? AND claim_id = ?",
                (str(org_id), claim_value["id"]),
            )
        knowledge.connection.rollback()
    finally:
        source.close()


def test_knowledge_rejects_invalid_terms_and_unusable_sources() -> None:
    source = SourceService()
    org_id, actor_id = uuid4(), uuid4()
    captured = source.ingest(
        org_id=org_id,
        actor_id=actor_id,
        trace_id="knowledge-invalid",
        idempotency_key="knowledge-invalid-source",
        source_type="url",
        canonical_url="https://knowledge.example/unusable",
        content="captured but not reviewed",
    )
    knowledge = KnowledgeService(connection=source._connection)
    try:
        with pytest.raises(KnowledgeError) as range_error:
            knowledge.create_claim(
                org_id=org_id,
                actor_id=actor_id,
                trace_id="knowledge-invalid",
                idempotency_key="knowledge-invalid-claim",
                entity_ids=None,
                statement="bad validity",
                valid_from="2026-02-01T00:00:00Z",
                valid_to="2026-01-01T00:00:00Z",
            )
        assert range_error.value.code == "INVALID_KNOWLEDGE_TERM"

        evidence = knowledge.create_evidence(
            org_id=org_id,
            actor_id=actor_id,
            trace_id="knowledge-invalid",
            idempotency_key="knowledge-invalid-evidence",
            source_snapshot_id=captured["snapshot"]["id"],
            quote="unreviewed source",
            locator="paragraph:1",
        )
        with pytest.raises(KnowledgeError) as source_error:
            knowledge.validate_evidence(
                org_id=org_id,
                evidence_id=evidence["evidence"]["id"],
                actor_id=actor_id,
                trace_id="knowledge-invalid",
                idempotency_key="knowledge-invalid-validate",
                expected_version=0,
            )
        assert source_error.value.code == "SOURCE_SNAPSHOT_NOT_USABLE"
    finally:
        source.close()
