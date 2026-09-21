"""Deterministic, account-free fixtures for foundation and domain tests."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import math
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

from .observability import TenantContext
from .storage import FakeStorage, StoredObject


DEFAULT_FIXTURE_TIME = datetime(2000, 1, 1, tzinfo=timezone.utc)


class FixtureValidationError(ValueError):
    pass


def _utc(value: datetime, *, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise FixtureValidationError(f"{name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _seconds(value: float | timedelta) -> float:
    result = value.total_seconds() if isinstance(value, timedelta) else value
    if isinstance(result, bool) or not isinstance(result, (int, float)) or not math.isfinite(result):
        raise FixtureValidationError("duration must be a finite number of seconds")
    if result < 0:
        raise FixtureValidationError("duration must not be negative")
    return float(result)


class FakeClock:
    """A deterministic UTC clock that never waits on wall time."""

    def __init__(self, current: datetime = DEFAULT_FIXTURE_TIME) -> None:
        self._current = _utc(current, name="current")

    def now(self) -> datetime:
        return self._current

    __call__ = now

    def set(self, value: datetime) -> datetime:
        target = _utc(value, name="value")
        if target < self._current:
            raise FixtureValidationError("fake clock cannot move backwards")
        self._current = target
        return self._current

    def advance(self, duration: float | timedelta) -> datetime:
        self._current += timedelta(seconds=_seconds(duration))
        return self._current

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)

    def as_contract(self) -> str:
        return self._current.isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class FixtureIdentity:
    fixture_id: str
    seed_hash: str
    org_id: str
    actor_id: str
    trace_id: str
    request_id: str
    idempotency_key: str

    @classmethod
    def from_seed(cls, seed: str) -> "FixtureIdentity":
        normalized = seed.strip() if isinstance(seed, str) else ""
        if not normalized or len(normalized.encode("utf-8")) > 256:
            raise FixtureValidationError("seed must contain 1 to 256 UTF-8 bytes")
        digest = sha256(normalized.encode("utf-8")).hexdigest()
        namespace = f"https://fixtures.ai-content-workflow.local/{digest}"
        return cls(
            fixture_id=str(uuid5(NAMESPACE_URL, namespace)),
            seed_hash=digest,
            org_id=str(uuid5(NAMESPACE_URL, namespace + "/org")),
            actor_id=str(uuid5(NAMESPACE_URL, namespace + "/actor")),
            trace_id=sha256((namespace + "/trace").encode()).hexdigest()[:32],
            request_id=str(uuid5(NAMESPACE_URL, namespace + "/request")),
            idempotency_key="fixture-" + sha256((namespace + "/idempotency").encode()).hexdigest(),
        )

    @property
    def context(self) -> TenantContext:
        return TenantContext(
            trace_id=self.trace_id,
            request_id=self.request_id,
            org_id=self.org_id,
            actor_id=self.actor_id,
        )

    def as_contract(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class FixtureAuditEvent:
    event_id: str
    sequence: int
    event_type: str
    fixture_id: str
    org_id: str
    actor_id: str
    trace_id: str
    occurred_at: str
    subject_ref: str
    content_hash: str | None
    metadata: Mapping[str, str]

    def as_contract(self) -> dict[str, Any]:
        value = {name: getattr(self, name) for name in self.__dataclass_fields__}
        value["metadata"] = dict(self.metadata)
        return value


class SyntheticFixtureKit:
    """Tenant-scoped fixture identity, clock, private storage and audit facts."""

    def __init__(
        self,
        identity: FixtureIdentity,
        *,
        clock: FakeClock | None = None,
        storage: FakeStorage | None = None,
    ) -> None:
        self.identity = identity
        self.clock = clock or FakeClock()
        self.storage = storage or FakeStorage()
        self._audit: list[FixtureAuditEvent] = []
        self._audit_index: dict[tuple[str, str, str | None], FixtureAuditEvent] = {}

    @classmethod
    def from_seed(
        cls,
        seed: str,
        *,
        started_at: datetime = DEFAULT_FIXTURE_TIME,
    ) -> "SyntheticFixtureKit":
        return cls(FixtureIdentity.from_seed(seed), clock=FakeClock(started_at))

    @property
    def context(self) -> TenantContext:
        return self.identity.context

    @property
    def idempotency_key(self) -> str:
        return self.identity.idempotency_key

    def _record(
        self,
        event_type: str,
        subject_ref: str,
        content_hash: str | None,
        metadata: Mapping[str, str] | None = None,
    ) -> FixtureAuditEvent:
        key = (event_type, subject_ref, content_hash)
        existing = self._audit_index.get(key)
        if existing is not None:
            return existing
        sequence = len(self._audit) + 1
        event = FixtureAuditEvent(
            event_id=str(uuid5(NAMESPACE_URL, f"{self.identity.fixture_id}/{sequence}/{event_type}/{subject_ref}")),
            sequence=sequence,
            event_type=event_type,
            fixture_id=self.identity.fixture_id,
            org_id=self.identity.org_id,
            actor_id=self.identity.actor_id,
            trace_id=self.identity.trace_id,
            occurred_at=self.clock.as_contract(),
            subject_ref=subject_ref,
            content_hash=content_hash,
            metadata={str(key): str(value) for key, value in (metadata or {}).items()},
        )
        self._audit.append(event)
        self._audit_index[key] = event
        return event

    def put_object(
        self,
        object_key: str,
        content: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: Mapping[str, str] | None = None,
    ) -> StoredObject:
        key_hash = sha256(object_key.encode("utf-8")).hexdigest()
        record = self.storage.put(
            self.identity.org_id,
            object_key,
            content,
            content_type=content_type,
            metadata=metadata,
            idempotency_key=f"{self.idempotency_key}:put:{key_hash}",
        )
        self._record(
            "fixture.storage.put",
            record.storage_object_ref,
            record.content_hash,
            {"content_type": record.content_type, "size_bytes": str(record.size_bytes)},
        )
        return record

    def delete_object(self, storage_object_ref: str) -> None:
        record = self.storage.head(self.identity.org_id, storage_object_ref)
        self.storage.delete(self.identity.org_id, storage_object_ref)
        self._record("fixture.storage.deleted", storage_object_ref, record.content_hash)

    def audit_events(self) -> tuple[FixtureAuditEvent, ...]:
        return tuple(self._audit)

    def as_contract(self) -> dict[str, Any]:
        objects = sorted(
            (item.as_contract() for item in self.storage.list(self.identity.org_id)),
            key=lambda item: item["storage_object_ref"],
        )
        return {
            "fixture_id": self.identity.fixture_id,
            "fixture_version": 1,
            "seed_hash": self.identity.seed_hash,
            "context": self.context.as_dict(),
            "idempotency_key": self.idempotency_key,
            "clock": self.clock.as_contract(),
            "storage_objects": objects,
            "audit_events": [event.as_contract() for event in self._audit],
            "network_access": False,
            "model_calls": False,
            "platform_calls": False,
        }


def create_synthetic_fixture(
    seed: str,
    *,
    started_at: datetime = DEFAULT_FIXTURE_TIME,
) -> SyntheticFixtureKit:
    return SyntheticFixtureKit.from_seed(seed, started_at=started_at)
