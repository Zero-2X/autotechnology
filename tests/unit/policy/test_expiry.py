from __future__ import annotations

from uuid import uuid4

import pytest

from modules.policy import PolicyExpiryService
from modules.policy.gate import QAError

from .test_gate import STAMP, _snapshot


def test_current_snapshot_allows_without_review_task() -> None:
    tenant, actor, subject = str(uuid4()), str(uuid4()), str(uuid4())
    service = PolicyExpiryService()
    decision = service.check_snapshot(
        org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="current",
        subject_type="variant", subject_id=subject, policy_snapshot=_snapshot(tenant, subject), evaluated_at=STAMP,
    )
    assert decision["final_decision"] == "allow"
    assert service.human_tasks == []
    assert service.audit[-1]["side_effect_blocked"] is False


def test_review_due_switches_to_manual_and_creates_schema_valid_human_task() -> None:
    tenant, actor, subject = str(uuid4()), str(uuid4()), str(uuid4())
    snapshot = _snapshot(tenant, subject)
    snapshot["review_due_at"] = "2026-09-18T00:00:00Z"
    service = PolicyExpiryService()
    decision = service.check_snapshot(
        org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="due",
        subject_type="variant", subject_id=subject, policy_snapshot=snapshot, evaluated_at=STAMP,
    )
    assert decision["final_decision"] == "manual_review"
    assert decision["reasons"] == ["POLICY_SNAPSHOT_REVIEW_DUE"]
    assert len(service.human_tasks) == 1
    assert service.human_tasks[0]["task_type"] == "policy_review"
    assert service.audit[-1]["side_effect_blocked"] is True
    assert service.check_snapshot(
        org_id=tenant, actor_id=actor, trace_id="other", idempotency_key="due",
        subject_type="variant", subject_id=subject, policy_snapshot=snapshot, evaluated_at=STAMP,
    ) == decision
    assert len(service.human_tasks) == 1


def test_expired_or_revoked_snapshot_denies_without_creating_duplicate_task() -> None:
    tenant, actor, subject = str(uuid4()), str(uuid4()), str(uuid4())
    snapshot = _snapshot(tenant, subject)
    snapshot["expires_at"] = "2026-09-18T00:00:00Z"
    service = PolicyExpiryService()
    expired = service.check_snapshot(
        org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="expired",
        subject_type="variant", subject_id=subject, policy_snapshot=snapshot, evaluated_at=STAMP,
    )
    assert expired["final_decision"] == "deny"
    assert expired["reasons"] == ["POLICY_SNAPSHOT_EXPIRED"]
    snapshot["status"] = "revoked"
    revoked = service.check_snapshot(
        org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="revoked",
        subject_type="variant", subject_id=subject, policy_snapshot=snapshot, evaluated_at=STAMP,
    )
    assert revoked["final_decision"] == "deny"
    assert revoked["reasons"] == ["POLICY_SNAPSHOT_REVOKED"]
    with pytest.raises(QAError) as error:
        service.check_snapshot(
            org_id=str(uuid4()), actor_id=actor, trace_id="trace", idempotency_key="foreign",
            subject_type="variant", subject_id=subject, policy_snapshot=snapshot, evaluated_at=STAMP,
        )
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
