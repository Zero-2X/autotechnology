import json
import sqlite3
from uuid import uuid4

import pytest

from modules.provenance import RightsError, RightsService, SourceService


def _setup():
    source = SourceService()
    rights = RightsService(connection=source._connection)
    org_id, actor_id = uuid4(), uuid4()
    created = source.ingest(
        org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key="rights-source-1",
        source_type="url", canonical_url="https://rights.example/source", content="terms",
    )
    snapshot_id = created["snapshot"]["id"]
    source.transition_snapshot(org_id=org_id, snapshot_id=snapshot_id, actor_id=actor_id,
                               trace_id="trace", idempotency_key="rights-source-2",
                               action="quarantine", expected_version=0)
    source.transition_snapshot(org_id=org_id, snapshot_id=snapshot_id, actor_id=actor_id,
                               trace_id="trace", idempotency_key="rights-source-3",
                               action="mark_usable", expected_version=1)
    return source, rights, org_id, actor_id, snapshot_id


def _create(rights, org_id, actor_id, snapshot_id, key="rights-create-1", record_id=None):
    return rights.create_version(
        org_id=org_id, rights_record_id=record_id or uuid4(), actor_id=actor_id,
        trace_id="trace-rights", idempotency_key=key, source_snapshot_ids=[snapshot_id],
        license_ref="license:one", rights_holder="Example Holder", permitted_regions=["US"],
        permitted_locales=["en-US"], permitted_media=["text", "code"], permitted_use="commercial",
        terms_snapshot_hash="a" * 64, policy_rule_version="rights-policy-v1",
    )


def test_create_rights_version_hashes_scope_and_replays() -> None:
    source, rights, org_id, actor_id, snapshot_id = _setup()
    record_id = uuid4()
    first = _create(rights, org_id, actor_id, snapshot_id, record_id=record_id)
    replay = _create(rights, org_id, actor_id, snapshot_id, record_id=record_id)
    assert replay == first
    version = first["version"]
    assert version["status"] == "pending"
    assert version["snapshot_hash"] == rights.recompute_snapshot_hash(version)
    assert first["rights_record"]["status"] == "pending"
    with pytest.raises(RightsError) as error:
        rights.create_version(
            org_id=org_id, rights_record_id=version["rights_record_id"], actor_id=actor_id,
            trace_id="trace-rights", idempotency_key="rights-create-1", source_snapshot_ids=[snapshot_id],
            license_ref="license:one", rights_holder="Changed Holder", permitted_regions=["US"],
            permitted_locales=["en-US"], permitted_media=["text", "code"], permitted_use="commercial",
            terms_snapshot_hash="a" * 64, policy_rule_version="rights-policy-v1",
        )
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"
    source.close()


def test_verify_requires_usable_snapshot_and_projects_parent_state() -> None:
    source, rights, org_id, actor_id, snapshot_id = _setup()
    created = _create(rights, org_id, actor_id, snapshot_id)
    version = created["version"]
    with pytest.raises(RightsError) as error:
        rights.verify_version(org_id=org_id, rights_record_id=version["rights_record_id"], version_id=version["id"],
                              actor_id=actor_id, trace_id="trace", idempotency_key="rights-verify-no-reason",
                              expected_version=1)
    assert error.value.code == "REASON_REQUIRED"
    verified = rights.verify_version(
        org_id=org_id, rights_record_id=version["rights_record_id"], version_id=version["id"], actor_id=actor_id,
        trace_id="trace", idempotency_key="rights-verify-1", expected_version=1, verification_reason="terms checked",
    )
    assert verified["version"]["status"] == "verified"
    assert verified["rights_record"]["status"] == "verified"
    replay = rights.verify_version(
        org_id=org_id, rights_record_id=version["rights_record_id"], version_id=version["id"], actor_id=actor_id,
        trace_id="other-trace", idempotency_key="rights-verify-1", expected_version=1, verification_reason="terms checked",
    )
    assert replay == verified
    source.close()


def test_rights_terminal_transition_is_reasoned_and_versioned() -> None:
    source, rights, org_id, actor_id, snapshot_id = _setup()
    created = _create(rights, org_id, actor_id, snapshot_id)
    version = created["version"]
    rights.verify_version(org_id=org_id, rights_record_id=version["rights_record_id"], version_id=version["id"],
                          actor_id=actor_id, trace_id="trace", idempotency_key="rights-verify-2",
                          expected_version=1, verification_reason="reviewed")
    revoked = rights.transition_version(
        org_id=org_id, rights_record_id=version["rights_record_id"], version_id=version["id"], actor_id=actor_id,
        trace_id="trace", idempotency_key="rights-revoke-1", action="revoke", expected_version=1,
        reason="holder withdrew permission",
    )
    assert revoked["version"]["status"] == "revoked"
    assert revoked["rights_record"]["current_version_id"] is None
    with pytest.raises(RightsError) as error:
        rights.transition_version(
            org_id=org_id, rights_record_id=version["rights_record_id"], version_id=version["id"], actor_id=actor_id,
            trace_id="trace", idempotency_key="rights-revoke-stale", action="revoke", expected_version=1,
            reason="again",
        )
    assert error.value.code == "INVALID_RIGHTS_STATE"
    with pytest.raises(sqlite3.DatabaseError):
        rights._connection.execute(
            "UPDATE rights_record_versions SET rights_holder = ? WHERE id = ?", ("tampered", version["id"])
        )
    rights._connection.rollback()
    with pytest.raises(sqlite3.DatabaseError):
        rights._connection.execute(
            "UPDATE rights_record_versions SET payload = ? WHERE id = ?",
            (json.dumps({**version, "rights_holder": "payload tamper"}), version["id"]),
        )
    rights._connection.rollback()
    with pytest.raises(sqlite3.DatabaseError):
        rights._connection.execute("DELETE FROM rights_record_versions WHERE id = ?", (version["id"],))
    rights._connection.rollback()
    source.close()


def test_rights_cross_tenant_and_source_snapshot_scope_are_rejected() -> None:
    source, rights, org_id, actor_id, snapshot_id = _setup()
    with pytest.raises(RightsError) as error:
        _create(rights, uuid4(), actor_id, snapshot_id, key="rights-cross-tenant")
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    created = _create(rights, org_id, actor_id, snapshot_id, key="rights-scope-1")
    with pytest.raises(RightsError) as error:
        rights.get_version(org_id=uuid4(), rights_record_id=created["version"]["rights_record_id"], version_id=created["version"]["id"])
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    source.close()


def test_pending_revision_preserves_verified_pointer_and_old_revoke_cannot_clear_new_pointer() -> None:
    source, rights, org_id, actor_id, snapshot_id = _setup()
    first = _create(rights, org_id, actor_id, snapshot_id, key="rights-revision-1")
    record_id = first["version"]["rights_record_id"]
    first_id = first["version"]["id"]
    rights.verify_version(
        org_id=org_id, rights_record_id=record_id, version_id=first_id, actor_id=actor_id,
        trace_id="trace", idempotency_key="rights-revision-verify-1", expected_version=1,
        verification_reason="reviewed first",
    )
    second = rights.create_version(
        org_id=org_id, rights_record_id=record_id, actor_id=actor_id,
        trace_id="trace", idempotency_key="rights-revision-2", source_snapshot_ids=[snapshot_id],
        license_ref="license:two", rights_holder="Example Holder", permitted_regions=["US", "CA"],
        permitted_locales=["en-US"], permitted_media=["text"], permitted_use="commercial",
        terms_snapshot_hash="a" * 64, policy_rule_version="rights-policy-v1", expected_version=1,
    )
    assert second["version"]["version_no"] == 2
    assert second["version"]["supersedes_version_id"] == first_id
    assert second["rights_record"]["current_version_id"] == first_id
    assert second["rights_record"]["status"] == "verified"
    second_id = second["version"]["id"]
    rights.verify_version(
        org_id=org_id, rights_record_id=record_id, version_id=second_id, actor_id=actor_id,
        trace_id="trace", idempotency_key="rights-revision-verify-2", expected_version=2,
        verification_reason="reviewed second",
    )
    old_revoked = rights.transition_version(
        org_id=org_id, rights_record_id=record_id, version_id=first_id, actor_id=actor_id,
        trace_id="trace", idempotency_key="rights-revision-revoke-old", action="revoke",
        expected_version=1, reason="superseded terms",
    )
    assert old_revoked["rights_record"]["current_version_id"] == second_id
    assert old_revoked["rights_record"]["status"] == "verified"
    source.close()
