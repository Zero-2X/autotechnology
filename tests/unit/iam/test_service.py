from uuid import uuid4

import pytest

from modules.iam import IamError, InMemoryIamService


def seed_owner() -> tuple[InMemoryIamService, object, object]:
    service = InMemoryIamService()
    org_id = uuid4()
    identity = service.create_identity(
        org_id=org_id,
        subject="owner@example.test",
        display_name="Owner",
        idempotency_key="seed-owner-1",
        trace_id="trace-owner",
    )
    return service, org_id, identity.id


def test_identity_idempotency_and_duplicate_payload() -> None:
    service = InMemoryIamService()
    org_id = uuid4()
    first = service.create_identity(org_id=org_id, subject="a", display_name="A", idempotency_key="key-1234", trace_id="t")
    assert service.create_identity(org_id=org_id, subject="a", display_name="A", idempotency_key="key-1234", trace_id="t").id == first.id
    with pytest.raises(IamError, match="payload") as error:
        service.create_identity(org_id=org_id, subject="a", display_name="B", idempotency_key="key-1234", trace_id="t")
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"


def test_tenant_scope_and_disabled_actor_are_rejected() -> None:
    service, org_id, actor_id = seed_owner()
    with pytest.raises(IamError) as error:
        service.context(org_id=uuid4(), actor_id=actor_id, trace_id="t")
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    service.identities[actor_id] = service.identities[actor_id].__class__(
        **{**service.identities[actor_id].__dict__, "status": "disabled"}
    )
    with pytest.raises(IamError) as error:
        service.context(org_id=org_id, actor_id=actor_id, trace_id="t")
    assert error.value.code == "ACTOR_DISABLED"


def test_owner_role_binding_and_audit_are_tenant_scoped() -> None:
    service, org_id, owner_id = seed_owner()
    target = service.create_identity(org_id=org_id, subject="editor", display_name="Editor", idempotency_key="editor-1234", trace_id="t")
    context = service.context(org_id=org_id, actor_id=owner_id, trace_id="t")
    binding = service.bind_role(context=context, actor_id=target.id, role="editor")
    assert binding.role == "editor"
    assert service.audit_log[-1].action == "role.bind"
    with pytest.raises(IamError) as error:
        service.bind_role(context=service.context(org_id=org_id, actor_id=target.id, trace_id="t"), actor_id=target.id, role="viewer")
    assert error.value.code == "FORBIDDEN"
