"""Append-only, idempotent cost facts with an injectable local sink."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from threading import RLock
from typing import Protocol
from uuid import uuid4

from .observability import TenantContext, get_tenant_context


_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_SECRET_VALUE_RE = re.compile(r"(?i)(?:bearer\s+|password\s*[:=]|token\s*[:=]|secret\s*[:=])")
_STATUSES = frozenset({"succeeded", "failed", "timed_out", "budget_exceeded"})


class CostValidationError(ValueError):
    """Raised when a cost fact is malformed or unsafe."""


class CostIdempotencyConflictError(CostValidationError):
    """Raised when one idempotency key is reused for another cost fact."""


def _text(value: object, name: str, *, maximum: int = 128) -> str:
    normalized = value.strip() if isinstance(value, str) else ""
    if (
        not normalized
        or len(normalized) > maximum
        or _CONTROL_RE.search(normalized)
        or _SECRET_VALUE_RE.search(normalized)
    ):
        raise CostValidationError(f"{name} is invalid")
    return normalized


def _count(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CostValidationError(f"{name} must be a non-negative integer")
    return value


@dataclass(frozen=True)
class CostRecord:
    id: str
    org_id: str | None
    trace_id: str
    request_id: str
    service: str
    operation: str
    provider: str
    model: str
    input_units: int
    output_units: int
    cost_cents: int
    latency_ms: int
    status: str
    idempotency_key: str
    occurred_at: str

    def as_contract(self) -> dict[str, object]:
        return asdict(self)


class CostSink(Protocol):
    def write(self, record: CostRecord) -> None: ...


class InMemoryCostSink:
    def __init__(self) -> None:
        self._lock = RLock()
        self._records: list[CostRecord] = []

    def write(self, record: CostRecord) -> None:
        with self._lock:
            self._records.append(record)

    @property
    def records(self) -> tuple[CostRecord, ...]:
        with self._lock:
            return tuple(self._records)


class CostRecorder:
    def __init__(self, sink: CostSink | None = None) -> None:
        self.sink = sink or InMemoryCostSink()
        self._lock = RLock()
        self._by_key: dict[tuple[str | None, str], tuple[str, CostRecord]] = {}

    def record(
        self,
        *,
        service: str,
        operation: str,
        provider: str,
        model: str,
        input_units: int,
        output_units: int,
        cost_cents: int,
        latency_ms: int,
        status: str,
        idempotency_key: str,
        context: TenantContext | None = None,
        occurred_at: datetime | None = None,
    ) -> CostRecord:
        current = context or get_tenant_context()
        if current is None:
            raise CostValidationError("TenantContext is required")
        values = {
            "service": _text(service, "service"),
            "operation": _text(operation, "operation"),
            "provider": _text(provider, "provider"),
            "model": _text(model, "model"),
            "input_units": _count(input_units, "input_units"),
            "output_units": _count(output_units, "output_units"),
            "cost_cents": _count(cost_cents, "cost_cents"),
            "latency_ms": _count(latency_ms, "latency_ms"),
            "status": status,
        }
        if status not in _STATUSES:
            raise CostValidationError("status is invalid")
        key = _text(idempotency_key, "idempotency_key", maximum=200)
        if len(key) < 8:
            raise CostValidationError("idempotency_key must be between 8 and 200 characters")
        fingerprint = hashlib.sha256(
            json.dumps(
                {"org_id": current.org_id, **values},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        index_key = (current.org_id, key)
        with self._lock:
            existing = self._by_key.get(index_key)
            if existing is not None:
                if existing[0] != fingerprint:
                    raise CostIdempotencyConflictError("idempotency key was reused with another cost fact")
                return existing[1]
            timestamp = occurred_at or datetime.now(timezone.utc)
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise CostValidationError("occurred_at must include a timezone")
            record = CostRecord(
                id=str(uuid4()),
                org_id=current.org_id,
                trace_id=current.trace_id,
                request_id=current.request_id,
                idempotency_key=key,
                occurred_at=timestamp.astimezone(timezone.utc).isoformat(timespec="microseconds"),
                **values,
            )
            self.sink.write(record)
            self._by_key[index_key] = (fingerprint, record)
            return record

    def record_safely(self, **values: object) -> CostRecord | None:
        """Best-effort observation seam for business paths that must not fail."""

        try:
            return self.record(**values)  # type: ignore[arg-type]
        except Exception:
            return None


__all__ = [
    "CostIdempotencyConflictError",
    "CostRecord",
    "CostRecorder",
    "CostSink",
    "CostValidationError",
    "InMemoryCostSink",
]
