"""Dependency-free IAM service for synthetic development and contract tests."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import hmac
import json
from typing import Any, Mapping
from uuid import UUID, uuid4

from modules.iam.domain.models import (
    PERMISSIONS,
    ROLES,
    ActorContext,
    DevIdentity,
    MfaFactor,
    Organization,
    RoleBinding,
    new_id,
    utc_now,
)


class IamError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AuditRecord:
    action: str
    org_id: UUID
    actor_id: UUID
    target_id: UUID
    role: str | None = None


class InMemoryIamService:
    """Tenant-scoped store with deterministic authorization semantics.

    It intentionally has no token, ORM, network, or production credential path.
    """

    def __init__(self) -> None:
        self.organizations: dict[UUID, Organization] = {}
        self.identities: dict[UUID, DevIdentity] = {}
        self._subjects: dict[tuple[UUID, str], UUID] = {}
        self.bindings: dict[tuple[UUID, UUID, str], RoleBinding] = {}
        self.idempotency: dict[tuple[UUID, str], tuple[str, Any]] = {}
        self.audit_log: list[AuditRecord] = []
        self.mfa_factors: dict[tuple[UUID, UUID], MfaFactor] = {}
        self._mfa_proofs: dict[tuple[UUID, UUID], str] = {}
        self._approval_decisions: dict[str, dict[str, Any]] = {}

    def ensure_organization(self, org_id: UUID, *, slug: str | None = None, name: str | None = None) -> Organization:
        organization = self.organizations.get(org_id)
        if organization:
            return organization
        organization = Organization(org_id, slug or f"org-{str(org_id)[:8]}", name or "Synthetic Organization")
        self.organizations[org_id] = organization
        return organization

    def create_identity(
        self,
        *,
        org_id: UUID,
        subject: str,
        display_name: str,
        idempotency_key: str,
        trace_id: str,
    ) -> DevIdentity:
        if not subject.strip() or not display_name.strip():
            raise IamError("INVALID_IDENTITY", "subject and display_name are required")
        self.ensure_organization(org_id)
        payload_hash = hashlib.sha256(json.dumps([str(org_id), subject, display_name]).encode()).hexdigest()
        cached = self.idempotency.get((org_id, idempotency_key))
        if cached:
            if cached[0] != payload_hash:
                raise IamError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
            return cached[1]
        existing = self._subjects.get((org_id, subject))
        if existing:
            raise IamError("DUPLICATE_IDENTITY", "subject already exists in organization")
        identity = DevIdentity(new_id(), org_id, subject, display_name, "active", utc_now())
        self.identities[identity.id] = identity
        self._subjects[(org_id, subject)] = identity.id
        if not any(existing.org_id == org_id for existing in self.identities.values() if existing.id != identity.id):
            self.bindings[(org_id, identity.id, "owner")] = RoleBinding(org_id, identity.id, "owner")
        self.idempotency[(org_id, idempotency_key)] = (payload_hash, identity)
        return identity

    def context(self, *, org_id: UUID, actor_id: UUID, trace_id: str) -> ActorContext:
        identity = self.identities.get(actor_id)
        if identity is None or identity.org_id != org_id:
            raise IamError("TENANT_SCOPE_VIOLATION", "actor does not belong to organization")
        if identity.status != "active":
            raise IamError("ACTOR_DISABLED", "actor is disabled")
        roles = tuple(sorted(binding.role for key, binding in self.bindings.items() if key[:2] == (org_id, actor_id)))
        permissions = frozenset(permission for role in roles for permission in PERMISSIONS[role])
        return ActorContext(org_id, actor_id, roles, permissions, trace_id)

    def bind_role(self, *, context: ActorContext, actor_id: UUID, role: str) -> RoleBinding:
        if role not in ROLES:
            raise IamError("INVALID_ROLE", "unknown role")
        if "role:bind" not in context.permissions:
            raise IamError("FORBIDDEN", "owner permission required")
        target = self.identities.get(actor_id)
        if target is None or target.org_id != context.org_id:
            raise IamError("TENANT_SCOPE_VIOLATION", "target actor does not belong to organization")
        key = (context.org_id, actor_id, role)
        if key in self.bindings:
            raise IamError("DUPLICATE_BINDING", "role binding already exists")
        binding = RoleBinding(*key)
        self.bindings[key] = binding
        self.audit_log.append(AuditRecord("role.bind", context.org_id, context.actor_id, actor_id, role))
        return binding

    def enroll_mfa(
        self, *, context: ActorContext, actor_id: UUID | None = None, factor_type: str = "totp",
        verification_code: str, idempotency_key: str,
    ) -> dict[str, Any]:
        """Create a fake MFA factor without persisting the code itself.

        The caller supplies a one-time fixture code in dev/test.  Production
        adapters can replace this proof channel while retaining the same
        ``MFA_REQUIRED`` gate and separation checks.
        """

        target_id = actor_id or context.actor_id
        if target_id != context.actor_id and "mfa:manage" not in context.permissions:
            raise IamError("FORBIDDEN", "MFA administration permission required")
        target = self.identities.get(target_id)
        if target is None or target.org_id != context.org_id:
            raise IamError("TENANT_SCOPE_VIOLATION", "MFA actor does not belong to organization")
        if factor_type not in {"totp", "webauthn", "fixture"}:
            raise IamError("INVALID_MFA_FACTOR", "unsupported MFA factor type")
        if not isinstance(verification_code, str) or not verification_code.strip():
            raise IamError("INVALID_MFA_PROOF", "verification code is required")
        payload_hash = hashlib.sha256(json.dumps(
            [str(context.org_id), str(target_id), factor_type, verification_code],
            separators=(",", ":"),
        ).encode()).hexdigest()
        cached = self.idempotency.get((context.org_id, idempotency_key))
        if cached:
            if cached[0] != payload_hash:
                raise IamError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
            return dict(cached[1])
        factor_id = uuid4()
        factor = MfaFactor(factor_id, context.org_id, target_id, factor_type, "pending", datetime.now(timezone.utc))
        self.mfa_factors[(context.org_id, target_id)] = factor
        # Store only a digest; the fixture code is never part of a contract or audit row.
        self._mfa_proofs[(context.org_id, factor_id)] = hashlib.sha256(verification_code.encode()).hexdigest()
        result = {**factor.as_contract(), "secret_reference": f"secret://mfa/{context.org_id}/{factor_id}"}
        self.idempotency[(context.org_id, idempotency_key)] = (payload_hash, result)
        self.audit_log.append(AuditRecord("mfa.enroll", context.org_id, context.actor_id, target_id))
        return dict(result)

    def confirm_mfa(self, *, context: ActorContext, factor_id: UUID | str, verification_code: str) -> dict[str, Any]:
        try:
            factor_id = UUID(str(factor_id))
        except (TypeError, ValueError) as exc:
            raise IamError("MFA_INVALID", "MFA factor id is invalid") from exc
        factor = self.mfa_factors.get((context.org_id, context.actor_id))
        if factor is None or factor.id != factor_id:
            raise IamError("MFA_NOT_FOUND", "MFA factor does not belong to actor")
        expected = self._mfa_proofs.get((context.org_id, factor_id))
        if expected is None or not isinstance(verification_code, str):
            raise IamError("MFA_INVALID", "MFA proof is invalid")
        supplied = hashlib.sha256(verification_code.encode()).hexdigest()
        if not hmac.compare_digest(expected, supplied):
            raise IamError("MFA_INVALID", "MFA proof is invalid")
        updated = replace(factor, status="verified", verified_at=datetime.now(timezone.utc))
        self.mfa_factors[(context.org_id, context.actor_id)] = updated
        self.audit_log.append(AuditRecord("mfa.confirm", context.org_id, context.actor_id, context.actor_id))
        return updated.as_contract()

    def require_mfa(self, *, context: ActorContext) -> None:
        self.context(org_id=context.org_id, actor_id=context.actor_id, trace_id=context.trace_id)
        factor = self.mfa_factors.get((context.org_id, context.actor_id))
        if factor is None or factor.status != "verified":
            raise IamError("MFA_REQUIRED", "a verified MFA factor is required")

    def authorize_approval(
        self, *, context: ActorContext, requested_by: UUID | str, aggregate_id: UUID | str,
        approval_type: str = "distribution",
    ) -> dict[str, Any]:
        try:
            requested_by = UUID(str(requested_by))
            aggregate_id = UUID(str(aggregate_id))
        except (TypeError, ValueError) as exc:
            raise IamError("INVALID_APPROVAL_INPUT", "approval ids must be UUIDs") from exc
        context = self.context(org_id=context.org_id, actor_id=context.actor_id, trace_id=context.trace_id)
        self.context(org_id=context.org_id, actor_id=requested_by, trace_id=context.trace_id)
        if "approval:review" not in context.permissions:
            raise IamError("FORBIDDEN", "approval review permission required")
        if context.actor_id == requested_by:
            raise IamError("SEPARATION_OF_DUTIES", "the requester cannot approve their own work")
        self.require_mfa(context=context)
        decision = {
            "id": str(uuid4()), "org_id": str(context.org_id), "aggregate_id": str(aggregate_id),
            "approval_type": approval_type, "requested_by": str(requested_by),
            "reviewer_id": str(context.actor_id), "status": "approved", "mfa_verified": True,
        }
        self._approval_decisions[decision["id"]] = dict(decision)
        self.audit_log.append(AuditRecord("approval.approve", context.org_id, context.actor_id, requested_by, approval_type))
        return decision

    def authorize_publish(
        self, *, context: ActorContext, requested_by: UUID | str, aggregate_id: UUID | str,
        approval: Mapping[str, Any],
    ) -> dict[str, Any]:
        try:
            requested_by = UUID(str(requested_by))
            aggregate_id = UUID(str(aggregate_id))
        except (TypeError, ValueError) as exc:
            raise IamError("INVALID_PUBLISH_INPUT", "publish ids must be UUIDs") from exc
        context = self.context(org_id=context.org_id, actor_id=context.actor_id, trace_id=context.trace_id)
        if "publish:execute" not in context.permissions:
            raise IamError("FORBIDDEN", "publish execution permission required")
        self.require_mfa(context=context)
        if not isinstance(approval, Mapping) or not isinstance(approval.get("id"), str):
            raise IamError("APPROVAL_REQUIRED", "a registered approval decision is required")
        registered = self._approval_decisions.get(approval["id"])
        if registered is None or dict(approval) != registered:
            raise IamError("APPROVAL_REQUIRED", "approval is unregistered or has been modified")
        if (registered["org_id"] != str(context.org_id)
                or registered["requested_by"] != str(requested_by)
                or registered["aggregate_id"] != str(aggregate_id)
                or registered["approval_type"] != "distribution"
                or registered["status"] != "approved"):
            raise IamError("APPROVAL_SCOPE_MISMATCH", "approval does not authorize this publication")
        reviewer = self.context(org_id=context.org_id, actor_id=UUID(registered["reviewer_id"]), trace_id=context.trace_id)
        self.context(org_id=context.org_id, actor_id=requested_by, trace_id=context.trace_id)
        if reviewer.actor_id in {requested_by, context.actor_id}:
            raise IamError("SEPARATION_OF_DUTIES", "reviewer must be independent of requester and executor")
        if "approval:review" not in reviewer.permissions:
            raise IamError("APPROVAL_REQUIRED", "reviewer no longer has approval permission")
        self.require_mfa(context=reviewer)
        result = {"allowed": True, "requested_by": str(requested_by), "executor_id": str(context.actor_id),
                  "approval_id": approval.get("id"), "side_effect_triggered": False}
        self.audit_log.append(AuditRecord("publish.authorize", context.org_id, context.actor_id, requested_by))
        return result
