"""Account-free platform registry and port shapes for FOUND-010."""
from __future__ import annotations

from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Protocol
from uuid import UUID

from .observability import TenantContext


_KEY = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
_KINDS = {"site", "official", "fake", "inbox"}
_STATUSES = {"active", "disabled"}


class PlatformContractError(ValueError):
    pass


def _uuid(value: str, name: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise PlatformContractError(f"{name} must be a UUID") from exc


@dataclass(frozen=True)
class Platform:
    id: str
    key: str
    display_name: str
    kind: str
    status: str
    policy_ref: str | None = None
    adapter_key: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _uuid(self.id, "id"))
        if not _KEY.fullmatch(self.key):
            raise PlatformContractError("key must be a lowercase registry key")
        if not self.display_name.strip():
            raise PlatformContractError("display_name must not be empty")
        if self.kind not in _KINDS:
            raise PlatformContractError("kind is invalid")
        if self.status not in _STATUSES:
            raise PlatformContractError("status is invalid")
        if self.adapter_key is not None and not _KEY.fullmatch(self.adapter_key):
            raise PlatformContractError("adapter_key is invalid")
        if self.kind == "fake" and self.adapter_key is None:
            raise PlatformContractError("fake platform requires an adapter_key")

    def as_contract(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


class PlatformRegistry:
    """Immutable lookup table; it does not discover or load adapters."""

    def __init__(self, platforms: Iterable[Platform]) -> None:
        by_id: dict[str, Platform] = {}
        by_key: dict[str, Platform] = {}
        for platform in platforms:
            if platform.id in by_id or platform.key in by_key:
                raise PlatformContractError("platform id and key must be unique")
            by_id[platform.id] = platform
            by_key[platform.key] = platform
        self._by_id = MappingProxyType(by_id)
        self._by_key = MappingProxyType(by_key)

    def get(self, key_or_id: str) -> Platform:
        platform = self._by_key.get(key_or_id) or self._by_id.get(key_or_id)
        if platform is None:
            raise PlatformContractError("platform is not registered")
        return platform

    def list(self, *, active_only: bool = False) -> tuple[Platform, ...]:
        values = (item for item in self._by_key.values() if not active_only or item.status == "active")
        return tuple(sorted(values, key=lambda item: item.key))


class ConnectionPort(Protocol):
    def inspect(self, *, context: TenantContext, connection_id: str) -> Mapping[str, Any]: ...


class PublisherPort(Protocol):
    def publish(
        self, *, context: TenantContext, publication_intent: Mapping[str, Any], idempotency_key: str
    ) -> Mapping[str, Any]: ...


class InboxPort(Protocol):
    def receive(self, *, context: TenantContext, cursor: str | None = None) -> tuple[Mapping[str, Any], ...]: ...


class MetricsPort(Protocol):
    def emit(self, *, context: TenantContext, name: str, value: float, labels: Mapping[str, str]) -> None: ...
