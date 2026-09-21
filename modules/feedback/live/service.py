"""Account-gated platform attribution and feedback observations.

The service accepts only aggregate platform facts.  It does not ingest raw
messages, profile data, tokens, or platform HTTP responses.  Until
``EXT-ACCOUNT-001`` is verified, callers can exercise the same contract with
an explicit fake account-evidence fixture, while the source remains marked
``platform`` and is never confused with account-free observations.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from threading import RLock
from typing import Any, Mapping
from uuid import NAMESPACE_URL, UUID, uuid5

from .ports import ObservationPort


class LiveFeedbackError(ValueError):
    """Stable errors for account-gated live feedback ingestion."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _hash(value: Any) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise LiveFeedbackError("INVALID_LIVE_INPUT", "value must be finite JSON") from exc
    return sha256(encoded.encode("utf-8")).hexdigest()


def _uuid(value: Any, field: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise LiveFeedbackError("INVALID_LIVE_INPUT", f"{field} must be a UUID") from exc


def _time(value: Any, field: str, *, required: bool = False) -> datetime | None:
    if value is None and not required:
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timezone missing")
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, AttributeError) as exc:
        raise LiveFeedbackError("INVALID_LIVE_INPUT", f"{field} must be an ISO-8601 timestamp with timezone") from exc


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


_METRICS = {
    "attribution": ("live.publication.attribution", "json", "aggregate"),
    "interactions": ("live.interaction.counts", "json", "count"),
    "platform_cost": ("live.platform.cost", "number", "minor_units"),
    "lead_quality": ("live.lead.quality", "json", "aggregate"),
}
_INTERACTION_KEYS = frozenset({"views", "likes", "shares", "comments", "saves", "clicks"})
_LEAD_KEYS = frozenset({"qualified", "converted", "score"})


class LiveFeedbackService:
    """Append account-gated observations through the canonical observation port."""

    def __init__(self, *, observation_service: ObservationPort,
                 clock: Any | None = None) -> None:
        self.observations = observation_service
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.batches: dict[tuple[str, str], dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self._commands: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
        self._lock = RLock()

    def ingest_platform_window(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        account_connection_id: UUID | str, platform_id: UUID | str, external_account_id: str,
        publication_id: UUID | str, window_start: datetime | str, window_end: datetime | str,
        attribution: Mapping[str, Any], interactions: Mapping[str, Any], platform_cost: int | float,
        lead_quality: Mapping[str, Any], source_snapshot_ref: str,
        account_evidence: Mapping[str, Any], locale: str | None = None, region: str | None = None,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        connection = _uuid(account_connection_id, "account_connection_id")
        platform = _uuid(platform_id, "platform_id")
        publication = _uuid(publication_id, "publication_id")
        if not isinstance(trace_id, str) or not trace_id.strip() or not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise LiveFeedbackError("INVALID_LIVE_INPUT", "trace_id and idempotency_key are required")
        start = _time(window_start, "window_start", required=True)
        end = _time(window_end, "window_end", required=True)
        if end <= start:
            raise LiveFeedbackError("INVALID_INTERACTION_WINDOW", "window_end must be after window_start")
        external = str(external_account_id).strip() if isinstance(external_account_id, str) else ""
        if not external:
            raise LiveFeedbackError("INVALID_LIVE_INPUT", "external_account_id is required")
        if not isinstance(source_snapshot_ref, str) or not source_snapshot_ref.startswith("private://"):
            raise LiveFeedbackError("SOURCE_SNAPSHOT_REQUIRED", "platform feedback requires a private source snapshot reference")
        evidence = self._evidence(account_evidence, tenant, connection)
        attribution_value = self._attribution(attribution, external, platform, connection)
        interaction_value = self._interactions(interactions)
        cost_value = self._cost(platform_cost)
        lead_value = self._lead_quality(lead_quality)
        at = _time(now, "now") or self._now()
        digest = _hash({
            "operation": "ingest_platform_window", "org_id": str(tenant), "connection_id": str(connection),
            "platform_id": str(platform), "publication_id": str(publication),
            "window_start": _stamp(start), "window_end": _stamp(end),
            "attribution": attribution_value, "interactions": interaction_value,
            "platform_cost": cost_value, "lead_quality": lead_value,
            "source_snapshot_ref": source_snapshot_ref, "locale": locale, "region": region,
            "account_evidence_hash": _hash(evidence),
        })
        key = idempotency_key.strip()
        with self._lock:
            prior = self._commands.get((str(tenant), key))
            if prior is not None:
                if prior[0] != digest:
                    raise LiveFeedbackError("IDEMPOTENCY_KEY_REUSED", "live feedback command differs from prior request")
                return deepcopy(prior[1])
            definitions = self._definitions(tenant=tenant, actor=actor, at=at)
            values = {
                "attribution": attribution_value, "interactions": interaction_value,
                "platform_cost": cost_value, "lead_quality": lead_value,
            }
            observations: list[dict[str, Any]] = []
            for metric_key, metric_value in values.items():
                definition, category = definitions[metric_key]
                observation = self.observations.record_observation(
                    org_id=tenant, actor_id=actor, trace_id=trace_id, idempotency_key=f"{key}:{metric_key}",
                    metric_definition=definition, source="platform", subject_type="publication",
                    subject_id=publication, metric_value=metric_value, observed_at=end,
                    locale=locale, region=region, data_quality="validated",
                    dedupe_key=f"{connection}:{publication}:{_stamp(start)}:{_stamp(end)}:{metric_key}",
                    source_snapshot_ref=source_snapshot_ref, category=category,
                    external_account_available=True, account_evidence=evidence,
                )
                observations.append(observation)
            result = {
                "org_id": str(tenant), "account_connection_id": str(connection),
                "platform_id": str(platform), "publication_id": str(publication),
                "external_account_ref": _hash(external),
                "window_start": _stamp(start), "window_end": _stamp(end),
                "observations": observations, "account_evidence_hash": _hash(evidence),
                "source": "platform", "side_effect_triggered": False,
            }
            self.batches[(str(tenant), key)] = deepcopy(result)
            self._commands[(str(tenant), key)] = (digest, deepcopy(result))
            self.audit.append({"event_type": "feedback.live.window_ingested", "org_id": str(tenant),
                               "actor_id": str(actor), "trace_id": trace_id, "idempotency_key": key,
                               "account_connection_id": str(connection), "platform_id": str(platform),
                               "publication_id": str(publication), "window_start": _stamp(start),
                               "window_end": _stamp(end), "observation_ids": [item["id"] for item in observations],
                               "account_evidence_hash": _hash(evidence)})
            return deepcopy(result)

    ingest = ingest_platform_window

    @staticmethod
    def _evidence(value: Mapping[str, Any], tenant: UUID, connection: UUID) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise LiveFeedbackError("EXT_ACCOUNT_EVIDENCE_REQUIRED", "verified account evidence is required")
        evidence = deepcopy(dict(value))
        marker = evidence.get("org_id")
        if marker is None or _uuid(marker, "account_evidence.org_id") != tenant:
            raise LiveFeedbackError("TENANT_SCOPE_VIOLATION", "account evidence belongs to another organization")
        if evidence.get("connection_id", evidence.get("account_connection_id")) != str(connection):
            raise LiveFeedbackError("TENANT_SCOPE_VIOLATION", "account evidence belongs to another connection")
        if str(evidence.get("status", "")).lower() not in {"active", "ready", "verified"}:
            raise LiveFeedbackError("EXT_ACCOUNT_UNAVAILABLE", "platform feedback requires verified account evidence")
        forbidden = {"token", "access_token", "refresh_token", "secret", "password", "authorization", "cookie"}
        if forbidden.intersection(str(key).lower() for key in evidence):
            raise LiveFeedbackError("SENSITIVE_OBSERVATION_REJECTED", "account evidence contains a sensitive field")
        return evidence

    @staticmethod
    def _attribution(value: Mapping[str, Any], external: str, platform: UUID, connection: UUID) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise LiveFeedbackError("INVALID_ATTRIBUTION", "attribution must be an object")
        allowed = {"external_object_id", "external_url_hash", "attribution_type", "campaign_ref_hash"}
        if set(value) - allowed:
            raise LiveFeedbackError("INVALID_ATTRIBUTION", "attribution contains unsupported fields")
        result = deepcopy(dict(value))
        result["platform_id"] = str(platform)
        result["connection_id"] = str(connection)
        result["external_account_ref"] = _hash(external)
        if "external_url_hash" in result and not isinstance(result["external_url_hash"], str):
            raise LiveFeedbackError("INVALID_ATTRIBUTION", "external_url_hash must be text")
        return result

    @staticmethod
    def _interactions(value: Mapping[str, Any]) -> dict[str, int]:
        if not isinstance(value, Mapping) or set(value) - _INTERACTION_KEYS:
            raise LiveFeedbackError("INVALID_INTERACTIONS", "interaction keys are unsupported")
        result: dict[str, int] = {}
        for key, item in value.items():
            if isinstance(item, bool) or not isinstance(item, int) or item < 0:
                raise LiveFeedbackError("INVALID_INTERACTIONS", "interaction counts must be non-negative integers")
            result[str(key)] = item
        return result

    @staticmethod
    def _cost(value: int | float) -> int | float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < 0:
            raise LiveFeedbackError("INVALID_PLATFORM_COST", "platform cost must be a finite non-negative number")
        return value

    @staticmethod
    def _lead_quality(value: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(value, Mapping) or set(value) - _LEAD_KEYS:
            raise LiveFeedbackError("INVALID_LEAD_QUALITY", "lead quality keys are unsupported")
        result = deepcopy(dict(value))
        for key in ("qualified", "converted"):
            if key in result and (not isinstance(result[key], bool)):
                raise LiveFeedbackError("INVALID_LEAD_QUALITY", f"{key} must be boolean")
        if "score" in result and (isinstance(result["score"], bool) or not isinstance(result["score"], (int, float)) or not 0 <= result["score"] <= 1):
            raise LiveFeedbackError("INVALID_LEAD_QUALITY", "score must be between 0 and 1")
        return result

    @staticmethod
    def _definitions(*, tenant: UUID, actor: UUID, at: datetime) -> dict[str, tuple[dict[str, Any], str]]:
        result: dict[str, tuple[dict[str, Any], str]] = {}
        categories = {"attribution": "publication", "interactions": "interaction", "platform_cost": "cost", "lead_quality": "risk"}
        for name, (key, metric_type, unit) in _METRICS.items():
            identity = str(uuid5(NAMESPACE_URL, f"feedback-live:{tenant}:{key}"))
            base = {
                "id": identity, "org_id": str(tenant), "key": key, "version_no": 1,
                "metric_type": metric_type, "unit": unit, "formula": "platform window aggregate",
                "dimensions": ["platform", "connection", "publication", "window"], "window": "explicit_utc_window",
                "data_source": "feedback.live.platform", "dedupe_rule": "connection+publication+window+metric",
                "quality_rules": {"value_schema": {"type": "object"}} if metric_type == "json" else {},
                "owner_actor_id": str(actor), "status": "active", "effective_at": _stamp(at),
                "retired_at": None, "snapshot_hash": "0" * 64,
            }
            base["snapshot_hash"] = _hash({k: v for k, v in base.items() if k != "snapshot_hash"})
            result[name] = (base, categories[name])
        return result

    def _now(self) -> datetime:
        return _time(self._clock(), "clock", required=True)  # type: ignore[return-value]


__all__ = ["LiveFeedbackError", "LiveFeedbackService"]
