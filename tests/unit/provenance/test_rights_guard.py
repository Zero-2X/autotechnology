import json
import sqlite3
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from modules.provenance import RightsGuardError, RightsGuardService, RightsService, SourceService


def _setup():
    source = SourceService()
    rights = RightsService(connection=source._connection)
    guard = RightsGuardService(rights_service=rights)
    org_id, actor_id = uuid4(), uuid4()
    captured = source.ingest(
        org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key="guard-source-1",
        source_type="url", canonical_url="https://guard.example/source", content="source",
    )
    snapshot_id = captured["snapshot"]["id"]
    source.transition_snapshot(org_id=org_id, snapshot_id=snapshot_id, actor_id=actor_id, trace_id="trace",
                               idempotency_key="guard-source-2", action="quarantine", expected_version=0)
    source.transition_snapshot(org_id=org_id, snapshot_id=snapshot_id, actor_id=actor_id, trace_id="trace",
                               idempotency_key="guard-source-3", action="mark_usable", expected_version=1)
    now = datetime.now(timezone.utc)
    valid_to = (now + timedelta(days=2)).isoformat().replace("+00:00", "Z")
    record_id = uuid4()
    created = rights.create_version(
        org_id=org_id, rights_record_id=record_id, actor_id=actor_id, trace_id="trace",
        idempotency_key="guard-rights-1", source_snapshot_ids=[snapshot_id], license_ref="license:guard",
        rights_holder="Guard Holder", permitted_regions=["US"], permitted_locales=["en-US"],
        permitted_media=["text"], permitted_use="commercial", terms_snapshot_hash="a" * 64,
        policy_rule_version="rights-policy-v1", valid_to=valid_to,
    )
    verified = rights.verify_version(
        org_id=org_id, rights_record_id=record_id, version_id=created["version"]["id"], actor_id=actor_id,
        trace_id="trace", idempotency_key="guard-rights-2", expected_version=1, verification_reason="reviewed",
    )
    return source, rights, guard, org_id, actor_id, verified["version"], valid_to


def test_authorization_gate_allows_matching_scope_and_blocks_unauthorized_scope() -> None:
    source, rights, guard, org_id, actor_id, version, _ = _setup()
    allowed = guard.check_authorization(
        org_id=org_id, rights_record_version_id=version["id"], actor_id=actor_id,
        trace_id="trace", idempotency_key="guard-check-1", region="US", locale="en-US", media="text", use="commercial",
        as_of="2026-09-18T12:00:00Z",
    )
    blocked = guard.check_authorization(
        org_id=org_id, rights_record_version_id=version["id"], actor_id=actor_id,
        trace_id="trace", idempotency_key="guard-check-2", region="DE", locale="de-DE", media="video", use="commercial",
        as_of="2026-09-18T12:00:00Z",
    )
    assert allowed["allowed"] is True and allowed["decision"] == "allowed"
    assert blocked["allowed"] is False
    assert {"REGION_NOT_PERMITTED", "LOCALE_NOT_PERMITTED", "MEDIA_NOT_PERMITTED"} <= set(blocked["reason_codes"])
    assert guard.check_authorization(
        org_id=org_id, rights_record_version_id=version["id"], actor_id=actor_id,
        trace_id="other", idempotency_key="guard-check-1", region="US", locale="en-US", media="text", use="commercial",
        as_of="2026-09-18T12:00:00Z",
    ) == allowed
    source.close()


def test_expiry_scan_is_idempotent_and_lineage_blocks_propagate() -> None:
    source, rights, guard, org_id, actor_id, version, valid_to = _setup()
    reminders = guard.schedule_expiry_reminders(
        org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key="guard-reminder-1",
        horizon_seconds=5 * 24 * 60 * 60, lead_seconds=24 * 60 * 60, as_of="2026-09-18T12:00:00Z",
    )
    assert len(reminders["reminders"]) == 1
    assert reminders["reminders"][0]["valid_to"] == valid_to
    assert guard.schedule_expiry_reminders(
        org_id=org_id, actor_id=actor_id, trace_id="other", idempotency_key="guard-reminder-1",
        horizon_seconds=5 * 24 * 60 * 60, lead_seconds=24 * 60 * 60, as_of="2026-09-18T12:00:00Z",
    ) == reminders
    first = guard.register_lineage(
        org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key="guard-lineage-1",
        rights_record_version_id=version["id"], derived_type="canonical", derived_id=uuid4(),
    )["edge"]
    second = guard.register_lineage(
        org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key="guard-lineage-2",
        rights_record_version_id=version["id"], derived_type="variant", derived_id=uuid4(),
        parent_derived_type="canonical", parent_derived_id=first["derived_id"],
    )["edge"]
    assert {edge["edge_id"] for edge in guard.trace_lineage(org_id=org_id, rights_record_version_id=version["id"])} == {first["edge_id"], second["edge_id"]}
    blocked = guard.block_derivatives(
        org_id=org_id, rights_record_version_id=version["id"], actor_id=actor_id, trace_id="trace",
        idempotency_key="guard-block-1", reason="rights withdrawn",
    )
    assert {item["derived_id"] for item in blocked["blocks"]} == {first["derived_id"], second["derived_id"]}
    source.close()


def test_complaint_freeze_transitions_rights_and_blocks_registered_derivatives() -> None:
    source, rights, guard, org_id, actor_id, version, _ = _setup()
    derived_id = uuid4()
    guard.register_lineage(
        org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key="guard-complaint-lineage",
        rights_record_version_id=version["id"], derived_type="canonical", derived_id=derived_id,
    )
    frozen = guard.freeze_complaint(
        org_id=org_id, rights_record_id=version["rights_record_id"], version_id=version["id"],
        actor_id=actor_id, trace_id="trace", idempotency_key="guard-complaint-1", expected_version=1,
        reason="copyright complaint",
    )
    assert frozen["version"]["status"] == "complaint_hold"
    assert frozen["blocks"][0]["derived_id"] == str(derived_id)
    denied = guard.check_authorization(
        org_id=org_id, rights_record_version_id=version["id"], actor_id=actor_id,
        trace_id="trace", idempotency_key="guard-complaint-check", region="US", locale="en-US", media="text", use="commercial",
        as_of="2026-09-18T12:00:00Z",
    )
    assert denied["allowed"] is False and "RIGHTS_STATUS_COMPLAINT_HOLD" in denied["reason_codes"]
    with pytest.raises(sqlite3.DatabaseError):
        guard._connection.execute("DELETE FROM rights_lineage_edges WHERE edge_id = ?", (frozen["blocks"][0]["edge_id"],))
    guard._connection.rollback()
    source.close()


def test_guard_cross_tenant_and_unverified_lineage_are_rejected() -> None:
    source, rights, guard, org_id, actor_id, version, _ = _setup()
    with pytest.raises(RightsGuardError) as error:
        guard.check_authorization(
            org_id=uuid4(), rights_record_version_id=version["id"], actor_id=actor_id,
            trace_id="trace", idempotency_key="guard-cross-1", region="US", locale="en-US", media="text", use="commercial",
        )
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    with pytest.raises(RightsGuardError) as error:
        guard.register_lineage(
            org_id=uuid4(), actor_id=actor_id, trace_id="trace", idempotency_key="guard-cross-2",
            rights_record_version_id=version["id"], derived_type="canonical", derived_id=uuid4(),
        )
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    source.close()
