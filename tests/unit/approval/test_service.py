from __future__ import annotations

from uuid import uuid4

import pytest

from modules.approval import ApprovalDeskService, ApprovalError


STAMP = "2026-09-19T00:00:00Z"
LATER = "2026-09-20T00:00:00Z"


def _request(service: ApprovalDeskService, *, tenant: str | None = None, actor: str | None = None,
             key: str = "request", quorum: int = 1, **kwargs):
    org_id, actor_id = tenant or str(uuid4()), actor or str(uuid4())
    result = service.request(
        org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key=key,
        aggregate_type="variant", aggregate_id=str(uuid4()), aggregate_version=1,
        approval_type="content", policy_snapshot_id=str(uuid4()), evidence_refs=[str(uuid4())],
        input_snapshot={"title": "New"}, previous_snapshot={"title": "Old"},
        current_snapshot={"title": "New"}, risk_reasons=["R2_REVIEW"],
        evidence_panel=[{"kind": "claim", "summary": "verified"}], comments=["Please check"],
        quorum_required=quorum, expires_at=LATER, created_at=STAMP, **kwargs,
    )
    return org_id, actor_id, result


def test_approval_request_view_and_single_reviewer_decision() -> None:
    service = ApprovalDeskService()
    tenant, requester, approval = _request(service)
    view = service.view(org_id=tenant, approval_id=approval["id"], at=STAMP)
    assert view["diff"] == [{"path": "/title", "operation": "replace", "before": "Old", "after": "New"}]
    assert view["risk_reasons"] == ["R2_REVIEW"]
    assert view["evidence_panel"][0]["kind"] == "claim"
    assert view["comments"][0]["body"] == "Please check"
    assert view["approval_version"] == 1
    reviewer = str(uuid4())
    decided = service.decide(org_id=tenant, actor_id=reviewer, reviewer_id=reviewer, trace_id="trace",
                            idempotency_key="decide", approval_id=approval["id"], decision="approved",
                            reason=None, expected_version=1, decided_at=STAMP)
    assert decided["status"] == "approved"
    assert decided["quorum_reached"] == 1
    assert len(decided["decision_ids"]) == 1
    assert service.audit[-1]["decision_record"]["reviewer_id"] == reviewer


def test_two_person_quorum_and_duplicate_reviewer_rejected() -> None:
    service = ApprovalDeskService()
    tenant, requester, approval = _request(service, quorum=2)
    reviewer_one, reviewer_two = str(uuid4()), str(uuid4())
    first = service.decide(org_id=tenant, actor_id=reviewer_one, reviewer_id=reviewer_one,
                           trace_id="trace", idempotency_key="first", approval_id=approval["id"],
                           decision="approved", reason=None, expected_version=1, decided_at=STAMP)
    assert first["status"] == "pending"
    assert first["quorum_reached"] == 1
    with pytest.raises(ApprovalError) as error:
        service.decide(org_id=tenant, actor_id=reviewer_one, reviewer_id=reviewer_one,
                       trace_id="trace", idempotency_key="duplicate", approval_id=approval["id"],
                       decision="approved", reason=None, expected_version=2, decided_at=STAMP)
    assert error.value.code == "REVIEWER_ALREADY_DECIDED"
    second = service.decide(org_id=tenant, actor_id=reviewer_two, reviewer_id=reviewer_two,
                            trace_id="trace", idempotency_key="second", approval_id=approval["id"],
                            decision="approved", reason=None, expected_version=2, decided_at=STAMP)
    assert second["status"] == "approved"
    assert second["quorum_reached"] == 2


def test_rejection_stale_version_tenant_scope_and_expiry() -> None:
    service = ApprovalDeskService()
    tenant, requester, approval = _request(service)
    with pytest.raises(ApprovalError) as error:
        service.view(org_id=str(uuid4()), approval_id=approval["id"], at=STAMP)
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    reviewer = str(uuid4())
    with pytest.raises(ApprovalError) as error:
        service.decide(org_id=tenant, actor_id=reviewer, reviewer_id=reviewer, trace_id="trace",
                       idempotency_key="stale", approval_id=approval["id"], decision="approved",
                       reason=None, expected_version=2, decided_at=STAMP)
    assert error.value.code == "STALE_APPROVAL_VERSION"
    rejected = service.decide(org_id=tenant, actor_id=reviewer, reviewer_id=reviewer, trace_id="trace",
                              idempotency_key="reject", approval_id=approval["id"], decision="rejected",
                              reason="facts incomplete", expected_version=1, decided_at=STAMP)
    assert rejected["status"] == "rejected"
    tenant2, actor2, approval2 = _request(service, key="expire")
    expired = service.expire(org_id=tenant2, actor_id=actor2, trace_id="trace", idempotency_key="tick",
                             approval_id=approval2["id"], at=LATER)
    assert expired["status"] == "expired"


def test_override_expiry_revokes_approved_result() -> None:
    service = ApprovalDeskService()
    tenant, requester, approval = _request(service)
    reviewer = str(uuid4())
    approved = service.decide(org_id=tenant, actor_id=reviewer, reviewer_id=reviewer, trace_id="trace",
                              idempotency_key="approve", approval_id=approval["id"], decision="approved",
                              reason=None, expected_version=1, override_expires_at="2026-09-19T12:00:00Z", decided_at=STAMP)
    assert approved["status"] == "approved"
    revoked = service.expire(org_id=tenant, actor_id=reviewer, trace_id="trace", idempotency_key="override-tick",
                             approval_id=approval["id"], at="2026-09-19T12:00:00Z")
    assert revoked["status"] == "revoked"
    assert revoked["reason"] == "OVERRIDE_EXPIRED"


def test_assignment_comment_and_decision_replays_do_not_duplicate_facts() -> None:
    service = ApprovalDeskService()
    tenant, requester, approval = _request(service)
    reviewer = str(uuid4())
    assigned = service.assign(org_id=tenant, actor_id=requester, trace_id="trace", idempotency_key="assign",
                              approval_id=approval["id"], assigned_to=reviewer, expected_version=1)
    assert service.assign(org_id=tenant, actor_id=requester, trace_id="replay", idempotency_key="assign",
                          approval_id=approval["id"], assigned_to=reviewer, expected_version=1) == assigned
    commented = service.comment(org_id=tenant, actor_id=requester, trace_id="trace", idempotency_key="comment",
                                approval_id=approval["id"], body="Check rights", expected_version=2)
    assert service.comment(org_id=tenant, actor_id=requester, trace_id="replay", idempotency_key="comment",
                           approval_id=approval["id"], body="Check rights", expected_version=2) == commented
    assert len(service.view(org_id=tenant, approval_id=approval["id"], at=STAMP)["comments"]) == 2
    decided = service.decide(org_id=tenant, actor_id=reviewer, reviewer_id=reviewer, trace_id="trace",
                             idempotency_key="decide", approval_id=approval["id"], decision="approved",
                             reason=None, expected_version=3, decided_at=STAMP)
    assert service.decide(org_id=tenant, actor_id=reviewer, reviewer_id=reviewer, trace_id="replay",
                          idempotency_key="decide", approval_id=approval["id"], decision="approved",
                          reason=None, expected_version=3, decided_at=STAMP) == decided
    assert len(service.view(org_id=tenant, approval_id=approval["id"], at=STAMP)["decisions"]) == 1
    with pytest.raises(ApprovalError) as error:
        service.comment(org_id=tenant, actor_id=requester, trace_id="trace", idempotency_key="comment",
                        approval_id=approval["id"], body="Different text", expected_version=2)
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"


class ReviewerAuth:
    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed

    def authorize(self, **kwargs):
        return self.allowed


def test_high_risk_request_forces_two_reviewers_and_authorization_port() -> None:
    service = ApprovalDeskService(reviewer_authorizer=ReviewerAuth(True))
    tenant, requester, approval = _request(service, key="high-risk", quorum=1, risk_level="R3")
    assert approval["quorum_required"] == 2
    first = str(uuid4())
    pending = service.decide(org_id=tenant, actor_id=first, reviewer_id=first, trace_id="trace",
                             idempotency_key="high-first", approval_id=approval["id"], decision="approved",
                             reason=None, expected_version=1, decided_at=STAMP)
    assert pending["status"] == "pending"
    denied_service = ApprovalDeskService(reviewer_authorizer=ReviewerAuth(False))
    tenant2, requester2, approval2 = _request(denied_service, key="forbidden")
    reviewer = str(uuid4())
    with pytest.raises(ApprovalError) as error:
        denied_service.decide(org_id=tenant2, actor_id=reviewer, reviewer_id=reviewer, trace_id="trace",
                              idempotency_key="forbidden-decision", approval_id=approval2["id"], decision="approved",
                              reason=None, expected_version=1, decided_at=STAMP)
    assert error.value.code == "FORBIDDEN"
