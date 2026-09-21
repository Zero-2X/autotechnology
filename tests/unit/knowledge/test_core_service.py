from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from modules.knowledge import KnowledgeCoreService, KnowledgeError, KnowledgeService
from modules.provenance import RightsService, SourceService


def _fixture():
    source = SourceService()
    rights = RightsService(connection=source._connection)
    org_id, actor_id = uuid4(), uuid4()
    captured = source.ingest(
        org_id=org_id, actor_id=actor_id, trace_id="core-trace", idempotency_key="core-source-1",
        source_type="url", canonical_url="https://core.example/source", content="core source",
    )
    snapshot_id = captured["snapshot"]["id"]
    source.transition_snapshot(org_id=org_id, snapshot_id=snapshot_id, actor_id=actor_id, trace_id="core-trace", idempotency_key="core-source-2", action="quarantine", expected_version=0)
    source.transition_snapshot(org_id=org_id, snapshot_id=snapshot_id, actor_id=actor_id, trace_id="core-trace", idempotency_key="core-source-3", action="mark_usable", expected_version=1)
    rights_record_id = uuid4()
    created_rights = rights.create_version(
        org_id=org_id, rights_record_id=rights_record_id, actor_id=actor_id, trace_id="core-trace", idempotency_key="core-rights-1",
        source_snapshot_ids=[snapshot_id], license_ref="license:core", rights_holder="Core Holder",
        permitted_regions=["US"], permitted_locales=["en-US"], permitted_media=["text"], permitted_use="commercial",
        terms_snapshot_hash="a" * 64, policy_rule_version="rights-v1",
        valid_to=(datetime.now(timezone.utc) + timedelta(days=2)).isoformat().replace("+00:00", "Z"),
    )
    verified_rights = rights.verify_version(
        org_id=org_id, rights_record_id=rights_record_id, version_id=created_rights["version"]["id"],
        actor_id=actor_id, trace_id="core-trace", idempotency_key="core-rights-2",
        expected_version=1, verification_reason="reviewed",
    )
    knowledge = KnowledgeService(connection=source._connection)
    entity = knowledge.create_entity(org_id=org_id, actor_id=actor_id, trace_id="core-trace", idempotency_key="core-entity-1", canonical_name="Core subject")
    claim = knowledge.create_claim(org_id=org_id, actor_id=actor_id, trace_id="core-trace", idempotency_key="core-claim-1", entity_ids=[entity["entity"]["id"]], statement="The subject is documented.", fact_type="identity")
    evidence = knowledge.create_evidence(
        org_id=org_id, actor_id=actor_id, trace_id="core-trace", idempotency_key="core-evidence-1",
        source_snapshot_id=snapshot_id, claim_id=claim["claim"]["id"], rights_record_version_id=verified_rights["version"]["id"],
        quote="core source", locator="paragraph:1",
    )
    knowledge.validate_evidence(org_id=org_id, evidence_id=evidence["evidence"]["id"], actor_id=actor_id, trace_id="core-trace", idempotency_key="core-evidence-2", expected_version=0)
    knowledge.verify_claim(org_id=org_id, claim_id=claim["claim"]["id"], actor_id=actor_id, trace_id="core-trace", idempotency_key="core-claim-2", expected_version=0)
    core = KnowledgeCoreService(connection=source._connection)
    return source, knowledge, core, org_id, actor_id, entity["entity"], claim["claim"], evidence["evidence"], verified_rights["version"]


def test_core_validation_requires_rights_and_keeps_versions_immutable() -> None:
    source, knowledge, core, org_id, actor_id, entity, claim, evidence, rights = _fixture()
    try:
        created = core.create_core(
            org_id=org_id, actor_id=actor_id, trace_id="core-trace", idempotency_key="core-create-1",
            entity_ids=[entity["id"]], claim_ids=[claim["id"]], evidence_ids=[evidence["id"]],
        )
        assert created["version"]["status"] == "draft"
        assert core.create_core(
            org_id=org_id, actor_id=actor_id, trace_id="different", idempotency_key="core-create-1",
            entity_ids=[entity["id"]], claim_ids=[claim["id"]], evidence_ids=[evidence["id"]],
        ) == created
        validated = core.validate_core(
            org_id=org_id, core_id=created["core"]["id"], actor_id=actor_id, trace_id="core-trace",
            idempotency_key="core-validate-1", expected_version=1,
        )
        assert validated["core"]["status"] == "validated"
        assert validated["version"]["status"] == "verified"
        assert validated["version"]["version_no"] == 2
        assert validated["core"]["current_version_id"] == validated["version"]["id"]
        assert core.get_version(org_id=org_id, version_id=created["version"]["id"])["status"] == "draft"
        with pytest.raises(sqlite3.DatabaseError):
            core.connection.execute("UPDATE knowledge_core_versions SET status = 'verified' WHERE id = ?", (created["version"]["id"],))
        core.connection.rollback()
        with pytest.raises(sqlite3.DatabaseError):
            core.connection.execute("DELETE FROM knowledge_core_versions WHERE id = ?", (created["version"]["id"],))
        core.connection.rollback()

        refreshed = core.refresh_core(
            org_id=org_id, core_id=created["core"]["id"], actor_id=actor_id, trace_id="core-trace",
            idempotency_key="core-refresh-1", expected_version=2,
        )
        assert refreshed["core"]["status"] == "stale"
        assert refreshed["version"]["version_no"] == 3
        assert refreshed["version"]["status"] == "draft"
        assert refreshed["version"]["supersedes_version_id"] == validated["version"]["id"]
        assert core.get_core(org_id=org_id, core_id=created["core"]["id"])["current_version_id"] == refreshed["version"]["id"]
    finally:
        source.close()


def test_conflicting_claims_create_review_set_and_validation_fails_closed() -> None:
    source = SourceService()
    knowledge = KnowledgeService(connection=source._connection)
    org_id, actor_id = uuid4(), uuid4()
    core = KnowledgeCoreService(connection=source._connection)
    try:
        entity = knowledge.create_entity(org_id=org_id, actor_id=actor_id, trace_id="conflict", idempotency_key="conflict-entity", canonical_name="Conflict subject")
        first = knowledge.create_claim(org_id=org_id, actor_id=actor_id, trace_id="conflict", idempotency_key="conflict-claim-1", entity_ids=[entity["entity"]["id"]], statement="The value is one.", fact_type="value")
        second = knowledge.create_claim(org_id=org_id, actor_id=actor_id, trace_id="conflict", idempotency_key="conflict-claim-2", entity_ids=[entity["entity"]["id"]], statement="The value is two.", fact_type="value")
        created = core.create_core(org_id=org_id, actor_id=actor_id, trace_id="conflict", idempotency_key="conflict-core", claim_ids=[first["claim"]["id"], second["claim"]["id"]])
        assert created["core"]["needs_review"] is True
        assert created["version"]["status"] == "needs_review"
        assert len(created["conflict_set_ids"]) == 1
        with pytest.raises(KnowledgeError) as error:
            core.validate_core(org_id=org_id, core_id=created["core"]["id"], actor_id=actor_id, trace_id="conflict", idempotency_key="conflict-validate", expected_version=1)
        assert error.value.code == "KNOWLEDGE_CONFLICT_REVIEW"
        with pytest.raises(KnowledgeError) as tenant_error:
            core.get_core(org_id=uuid4(), core_id=created["core"]["id"])
        assert tenant_error.value.code == "TENANT_SCOPE_VIOLATION"
    finally:
        source.close()

