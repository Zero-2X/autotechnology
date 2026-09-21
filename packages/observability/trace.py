"""Trace, audit and metric facts with sensitive-payload redaction."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from threading import RLock
from typing import Any, Mapping


_SENSITIVE = frozenset({
    "authorization", "cookie", "password", "secret", "token", "access_token",
    "refresh_token", "private_key", "raw_content", "raw_output", "body", "prompt",
})


def redact_payload(value: Any, *, depth: int = 0) -> Any:
    """Return a bounded, JSON-safe payload suitable for audit and logs."""
    if depth > 8:
        return "<depth-limit>"
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            if name.strip().lower() in _SENSITIVE:
                result[name] = "<redacted>"
            else:
                result[name] = redact_payload(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [redact_payload(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str) and len(value) > 512:
            return {"sha256": hashlib.sha256(value.encode()).hexdigest(), "length": len(value)}
        return value
    return str(value)


class TraceLedger:
    """In-memory append-only trace, audit, metric and cost collector."""

    def __init__(self, *, clock: Any | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.events: list[dict[str, Any]] = []
        self.metrics: list[dict[str, Any]] = []
        self.costs: list[dict[str, Any]] = []
        self._lock = RLock()

    def emit(self, event_type: str, *, org_id: str, trace_id: str, actor_id: str | None = None,
             aggregate_id: str | None = None, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        body = redact_payload(dict(payload or {}))
        encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        event = {
            "event_id": hashlib.sha256(f"{event_type}:{org_id}:{trace_id}:{len(self.events)}".encode()).hexdigest()[:32],
            "event_type": event_type, "occurred_at": self._stamp(), "org_id": str(org_id),
            "trace_id": str(trace_id), "actor_id": None if actor_id is None else str(actor_id),
            "aggregate_id": None if aggregate_id is None else str(aggregate_id),
            "payload": body, "payload_hash": hashlib.sha256(encoded.encode()).hexdigest(),
        }
        with self._lock:
            self.events.append(deepcopy(event))
        return deepcopy(event)

    def observe(self, name: str, *, value: float, org_id: str, trace_id: str,
                labels: Mapping[str, str] | None = None) -> None:
        with self._lock:
            self.metrics.append({"name": name, "value": float(value), "org_id": str(org_id),
                                 "trace_id": str(trace_id), "labels": dict(labels or {}), "at": self._stamp()})

    def cost(self, *, org_id: str, trace_id: str, provider: str, input_tokens: int = 0,
             output_tokens: int = 0, amount_minor: int = 0) -> None:
        if min(input_tokens, output_tokens, amount_minor) < 0:
            raise ValueError("cost values cannot be negative")
        with self._lock:
            self.costs.append({"org_id": str(org_id), "trace_id": str(trace_id), "provider": provider,
                               "input_tokens": input_tokens, "output_tokens": output_tokens,
                               "amount_minor": amount_minor, "at": self._stamp()})

    def _stamp(self) -> str:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return timezone-aware datetime")
        return now.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
