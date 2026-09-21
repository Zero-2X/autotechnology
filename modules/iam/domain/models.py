"""Pure IAM records used by the synthetic development identity slice."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

ROLES = frozenset({"owner", "editor", "reviewer", "operator", "viewer"})
PERMISSIONS = {
    "owner": frozenset({"identity:create", "role:bind", "resource:read", "resource:write", "approval:review", "publish:execute", "mfa:manage"}),
    "editor": frozenset({"resource:read", "resource:write"}),
    "reviewer": frozenset({"resource:read", "approval:review"}),
    "operator": frozenset({"resource:read", "resource:write", "operation:run", "publish:execute"}),
    "viewer": frozenset({"resource:read"}),
}


@dataclass(frozen=True)
class Organization:
    id: UUID
    slug: str
    name: str
    status: str = "active"

    def as_contract(self) -> dict[str, Any]:
        return {**asdict(self), "id": str(self.id)}


@dataclass(frozen=True)
class DevIdentity:
    id: UUID
    org_id: UUID
    subject: str
    display_name: str
    status: str
    created_at: datetime

    def as_contract(self, roles: list[str] | None = None) -> dict[str, Any]:
        return {
            **asdict(self),
            "id": str(self.id),
            "org_id": str(self.org_id),
            "created_at": self.created_at.isoformat(),
            "roles": sorted(roles or []),
            "permissions": sorted({permission for role in roles or [] for permission in PERMISSIONS[role]}),
        }


@dataclass(frozen=True)
class RoleBinding:
    org_id: UUID
    actor_id: UUID
    role: str

    def as_contract(self) -> dict[str, str]:
        return {"org_id": str(self.org_id), "actor_id": str(self.actor_id), "role": self.role}


@dataclass(frozen=True)
class ActorContext:
    org_id: UUID
    actor_id: UUID
    roles: tuple[str, ...]
    permissions: frozenset[str]
    trace_id: str

    def as_contract(self) -> dict[str, Any]:
        return {
            "org_id": str(self.org_id),
            "actor_id": str(self.actor_id),
            "roles": list(self.roles),
            "permissions": sorted(self.permissions),
            "trace_id": self.trace_id,
        }


@dataclass(frozen=True)
class MfaFactor:
    """Secret-free MFA enrollment projection used by the synthetic IAM port."""

    id: UUID
    org_id: UUID
    actor_id: UUID
    factor_type: str
    status: str
    created_at: datetime
    verified_at: datetime | None = None

    def as_contract(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "org_id": str(self.org_id),
            "actor_id": str(self.actor_id),
            "factor_type": self.factor_type,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
        }


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> UUID:
    return uuid4()
