"""Deterministic upload status reconciliation and PublicationRecord projection."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import RLock
from typing import Any, Mapping
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker

from .service import DistributionError, _EVENT_VALIDATOR, _hash, _stamp, _text, _time, _uuid, _validate


_ROOT = Path(__file__).resolve().parents[2]
_PUBLICATION_VALIDATOR = Draft202012Validator(
    json.loads((_ROOT / "packages/contracts/jsonschema/publication-record.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
_ORDER = {"attempted": 0, "acknowledged": 1, "published": 2, "failed": 0, "unknown": 0, "removed": 3}
_OBSERVED = {"uploaded", "acknowledged", "published", "failed", "unknown"}


class ReconciliationError(DistributionError):
    pass


class PublicationReconciler:
    """Create immutable observations while preventing successful state regression."""

    def __init__(self) -> None:
        self.records: dict[tuple[str, str], dict[str, Any]] = {}
        self.attempts: dict[tuple[str, str], dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self._commands: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
        self._lock = RLock()

    def observe(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        delivery_attempt: Mapping[str, Any], observed_status: str, observed_at: datetime | str | None = None,
        external_request_id: str | None = None, external_object_id: str | None = None,
        external_url: str | None = None, observation_source: str = "poll", unknown_reason: str | None = None,
    ) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        if not isinstance(delivery_attempt, Mapping) or delivery_attempt.get("org_id") != tenant:
            raise ReconciliationError("TENANT_SCOPE_VIOLATION", "delivery attempt is outside this organization")
        attempt = deepcopy(dict(delivery_attempt))
        _validate("delivery-attempt", attempt)
        if observed_status not in _OBSERVED:
            raise ReconciliationError("INVALID_RECONCILIATION", "observed_status is invalid")
        if observation_source not in {"adapter", "webhook", "poll", "manual"}:
            raise ReconciliationError("INVALID_RECONCILIATION", "observation_source is invalid")
        at = _time(observed_at, "observed_at") or datetime.now(timezone.utc)
        identity = (tenant, attempt["id"])
        digest = _hash({"attempt": attempt, "observed_status": observed_status, "observed_at": _stamp(at),
                        "external_request_id": external_request_id, "external_object_id": external_object_id,
                        "external_url": external_url, "observation_source": observation_source, "unknown_reason": unknown_reason})
        with self._lock:
            prior = self._commands.get((tenant, key))
            if prior is not None:
                if prior[0] != digest:
                    raise ReconciliationError("IDEMPOTENCY_KEY_REUSED", "reconciliation differs from prior request")
                return deepcopy(prior[1])
            current = self.records.get(identity)
            status = {"uploaded": "acknowledged", "acknowledged": "acknowledged", "published": "published",
                      "failed": "failed", "unknown": "unknown"}[observed_status]
            if current is not None and _ORDER.get(current["status"], 0) > _ORDER.get(status, 0) and current["status"] not in {"failed", "unknown"}:
                raise ReconciliationError("OBSERVATION_REGRESSION", "publication status cannot regress")
            if observed_status == "unknown" and not unknown_reason:
                raise ReconciliationError("UNKNOWN_REASON_REQUIRED", "unknown observation requires unknown_reason")
            result_snapshot = {"simulated": attempt["provider_mode"] == "fake", "replay_input_hash": _hash({"attempt": attempt, "observed_status": observed_status}), "attempt_no": attempt["attempt_no"]}
            record = {
                "id": current["id"] if current is not None else str(uuid4()), "org_id": tenant,
                "publication_intent_id": attempt["publication_intent_id"], "delivery_attempt_id": attempt["id"],
                "provider_mode": attempt["provider_mode"], "external_request_id": external_request_id or attempt["external_request_id"],
                "external_object_id": external_object_id or attempt["external_object_id"], "external_url": external_url,
                "status": status, "result_snapshot": result_snapshot,
                "observed_at": current["observed_at"] if current is not None and current["observed_at"] < _stamp(at) else _stamp(at),
                "last_observed_at": _stamp(at), "observation_source": observation_source,
                "unknown_reason": unknown_reason if observed_status == "unknown" else None,
                "resolution_reason": None, "resolved_by": None, "resolved_at": None, "resolution_evidence_ref": None,
            }
            _validate("publication-record", record)
            attempt_update = deepcopy(attempt)
            attempt_update["status"] = "unknown" if observed_status == "unknown" else "succeeded" if status in {"acknowledged", "published"} else "failed"
            attempt_update["external_request_id"] = record["external_request_id"]
            attempt_update["external_object_id"] = record["external_object_id"]
            attempt_update["completed_at"] = _stamp(at)
            attempt_update["last_error_code"] = unknown_reason if observed_status in {"unknown", "failed"} else None
            _validate("delivery-attempt", attempt_update)
            self.records[identity] = deepcopy(record)
            self.attempts[identity] = deepcopy(attempt_update)
            result = {"publication_record": deepcopy(record), "delivery_attempt": deepcopy(attempt_update)}
            self._commands[(tenant, key)] = (digest, deepcopy(result))
            self.audit.append({"event_type": "publication.reconciled", "org_id": tenant, "actor_id": actor,
                               "trace_id": trace, "idempotency_key": key, "input_hash": digest,
                               "output_hash": _hash(result), "observed_status": observed_status})
            self._event("publication.reconciled", tenant, actor, trace, key, record["publication_intent_id"],
                        {"delivery_attempt_id": attempt["id"], "status": status, "observation_source": observation_source}, at)
            return deepcopy(result)

    def _event(self, event_type: str, tenant: str, actor: str, trace: str, key: str, aggregate_id: str,
               payload: Mapping[str, Any], occurred_at: datetime) -> None:
        event_payload = {"aggregate_id": aggregate_id, "aggregate_version": 1, **dict(payload)}
        event = {"event_id": str(uuid4()), "event_type": event_type, "event_schema_version": 1,
                 "occurred_at": _stamp(occurred_at), "org_id": tenant, "trace_id": trace,
                 "aggregate_type": "publication_intent", "aggregate_id": aggregate_id, "aggregate_version": 1,
                 "actor_type": "service", "actor_id": actor, "idempotency_key": key,
                 "payload": event_payload, "payload_hash": _hash(event_payload)}
        errors = list(_EVENT_VALIDATOR.iter_errors(event))
        if errors:
            raise ReconciliationError("INVALID_RECONCILIATION_EVENT", errors[0].message)
        self.events.append(event)


__all__ = ["PublicationReconciler", "ReconciliationError"]
