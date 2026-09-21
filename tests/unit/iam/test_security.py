from uuid import UUID, uuid4

import pytest

from modules.iam import IamError, InMemoryIamService


def _seed() -> tuple[InMemoryIamService, object, object, object, object]:
    service = InMemoryIamService()
    org_id = uuid4()
    owner = service.create_identity(org_id=org_id, subject="owner", display_name="Owner", idempotency_key="owner", trace_id="t")
    reviewer = service.create_identity(org_id=org_id, subject="reviewer", display_name="Reviewer", idempotency_key="reviewer", trace_id="t")
    operator = service.create_identity(org_id=org_id, subject="operator", display_name="Operator", idempotency_key="operator", trace_id="t")
    owner_ctx = service.context(org_id=org_id, actor_id=owner.id, trace_id="t")
    service.bind_role(context=owner_ctx, actor_id=reviewer.id, role="reviewer")
    service.bind_role(context=owner_ctx, actor_id=operator.id, role="operator")
    return service, org_id, owner, reviewer, operator


def test_mfa_enrollment_stores_only_digest_and_requires_confirmation():
    service, org_id, owner, reviewer, _operator = _seed()
    owner_ctx = service.context(org_id=org_id, actor_id=owner.id, trace_id="t")
    enrolled = service.enroll_mfa(
        context=owner_ctx, actor_id=reviewer.id, factor_type="fixture",
        verification_code="fixture-code", idempotency_key="mfa-enroll",
    )
    assert enrolled["status"] == "pending"
    assert "fixture-code" not in repr(service.__dict__)
    reviewer_ctx = service.context(org_id=org_id, actor_id=reviewer.id, trace_id="t")
    with pytest.raises(IamError) as error:
        service.require_mfa(context=reviewer_ctx)
    assert error.value.code == "MFA_REQUIRED"
    with pytest.raises(IamError) as error:
        service.confirm_mfa(context=reviewer_ctx, factor_id=reviewer.id, verification_code="fixture-code")
    assert error.value.code == "MFA_NOT_FOUND"
    service.confirm_mfa(context=reviewer_ctx, factor_id=UUID(enrolled["id"]), verification_code="fixture-code")
    service.require_mfa(context=reviewer_ctx)


def test_approval_and_publish_require_mfa_and_separate_requester_reviewer():
    service, org_id, owner, reviewer, operator = _seed()
    owner_ctx = service.context(org_id=org_id, actor_id=owner.id, trace_id="t")
    reviewer_factor = service.enroll_mfa(
        context=owner_ctx, actor_id=reviewer.id, factor_type="fixture",
        verification_code="reviewer-code", idempotency_key="reviewer-mfa",
    )
    reviewer_ctx = service.context(org_id=org_id, actor_id=reviewer.id, trace_id="t")
    service.confirm_mfa(context=reviewer_ctx, factor_id=UUID(reviewer_factor["id"]), verification_code="reviewer-code")
    with pytest.raises(IamError) as error:
        service.authorize_approval(context=reviewer_ctx, requested_by=reviewer.id, aggregate_id=uuid4())
    assert error.value.code == "SEPARATION_OF_DUTIES"
    approval = service.authorize_approval(context=reviewer_ctx, requested_by=owner.id, aggregate_id=uuid4())

    operator_factor = service.enroll_mfa(
        context=owner_ctx, actor_id=operator.id, factor_type="fixture",
        verification_code="operator-code", idempotency_key="operator-mfa",
    )
    operator_ctx = service.context(org_id=org_id, actor_id=operator.id, trace_id="t")
    service.confirm_mfa(context=operator_ctx, factor_id=UUID(operator_factor["id"]), verification_code="operator-code")
    authorized = service.authorize_publish(context=operator_ctx, requested_by=owner.id, aggregate_id=approval["aggregate_id"], approval=approval)
    assert authorized["allowed"] is True
    assert authorized["side_effect_triggered"] is False


def test_publish_cannot_bypass_approval_or_mfa():
    service, org_id, owner, _reviewer, operator = _seed()
    operator_ctx = service.context(org_id=org_id, actor_id=operator.id, trace_id="t")
    with pytest.raises(IamError) as error:
        service.authorize_publish(
            context=operator_ctx, requested_by=owner.id, aggregate_id=uuid4(),
            approval={"status": "approved", "reviewer_id": str(uuid4())},
        )
    assert error.value.code == "MFA_REQUIRED"


def _approved_publish():
    service, org_id, owner, reviewer, operator = _seed()
    for actor in (reviewer, operator):
        context = service.context(org_id=org_id, actor_id=actor.id, trace_id="t")
        factor = service.enroll_mfa(context=context, factor_type="fixture", verification_code="fixture-proof", idempotency_key=str(actor.id))
        service.confirm_mfa(context=context, factor_id=factor["id"], verification_code="fixture-proof")
    reviewer_ctx = service.context(org_id=org_id, actor_id=reviewer.id, trace_id="t")
    approval = service.authorize_approval(context=reviewer_ctx, requested_by=owner.id, aggregate_id=uuid4())
    kwargs = dict(context=service.context(org_id=org_id, actor_id=operator.id, trace_id="t"),
                  requested_by=owner.id, aggregate_id=approval["aggregate_id"], approval=approval)
    return service, kwargs


@pytest.mark.parametrize("change", ["unregistered", "modified", "other_target", "other_requester"])
def test_publish_rejects_forged_or_reused_approval(change):
    service, kwargs = _approved_publish()
    if change == "unregistered":
        kwargs["approval"]["id"] = str(uuid4())
    elif change == "modified":
        kwargs["approval"]["reviewer_id"] = str(uuid4())
    elif change == "other_target":
        kwargs["aggregate_id"] = uuid4()
    else:
        kwargs["requested_by"] = uuid4()
    before = len(service.audit_log)
    with pytest.raises(IamError) as error:
        service.authorize_publish(**kwargs)
    assert error.value.code in {"APPROVAL_REQUIRED", "APPROVAL_SCOPE_MISMATCH"}
    assert len(service.audit_log) == before


def test_publish_rechecks_current_reviewer_permissions():
    service, kwargs = _approved_publish()
    org_id = kwargs["context"].org_id
    reviewer_id = UUID(kwargs["approval"]["reviewer_id"])
    del service.bindings[(org_id, reviewer_id, "reviewer")]
    with pytest.raises(IamError) as error:
        service.authorize_publish(**kwargs)
    assert error.value.code == "APPROVAL_REQUIRED"
