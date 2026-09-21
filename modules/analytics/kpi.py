"""Deterministic account-free KPI aggregation for ANALYTICS-003."""

from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
from threading import RLock
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid5

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from .catalog import AnalyticsError, _canonical, _context, _hash, _stamp, _text, _time, _uuid
from .observation import _locale, _region


_ROOT = Path(__file__).resolve().parents[2]
_OBSERVATION_SCHEMA = json.loads(
    (_ROOT / "packages/contracts/jsonschema/observation.schema.json").read_text(encoding="utf-8")
)
_SNAPSHOT_SCHEMA = json.loads(
    (_ROOT / "packages/contracts/jsonschema/analytics-kpi-snapshot.schema.json").read_text(encoding="utf-8")
)
_OBSERVATION_VALIDATOR = Draft202012Validator(_OBSERVATION_SCHEMA, format_checker=FormatChecker())
_SNAPSHOT_VALIDATOR = Draft202012Validator(_SNAPSHOT_SCHEMA, format_checker=FormatChecker())
_SNAPSHOT_NAMESPACE = UUID("16bbc519-3337-54ff-8998-2350b0033da7")
_EVENT_NAMESPACE = UUID("9eb43b04-b25b-5d21-bdb4-9239ef90e3f1")
_RULE_VERSION = "analytics-003.v1"
_CHANNEL_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")

_FAMILIES = {
    "publication.outcome": "publication_success_rate",
    "publication.status": "publication_success_rate",
    "publication.success": "publication_success_rate",
    "workflow.manual_intervention": "manual_intervention_rate",
    "manual.intervention": "manual_intervention_rate",
    "human.intervention_required": "manual_intervention_rate",
    "rights.rejected": "rights_rejection_rate",
    "copyright.rejected": "rights_rejection_rate",
    "rights.decision": "rights_rejection_rate",
    "translation.qa_passed": "translation_pass_rate",
    "translation.passed": "translation_pass_rate",
    "support.answer_incorrect": "answer_error_rate",
    "answer.incorrect": "answer_error_rate",
    "support.answer_error": "answer_error_rate",
    "cost.amount_cents": "cost",
    "cost.cents": "cost",
    "operation.cost_cents": "cost",
    "lead.attribution": "lead_attribution",
    "lead.attributed": "lead_attribution",
}
_RATE_NAMES = (
    "publication_success_rate",
    "manual_intervention_rate",
    "rights_rejection_rate",
    "translation_pass_rate",
    "answer_error_rate",
)


AnalyticsKpiError = AnalyticsError
KpiAggregationError = AnalyticsError


def _ratio(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": None if denominator == 0 else round(numerator / denominator, 6),
    }


def _decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AnalyticsError("KPI_SEMANTIC_VALUE_INVALID", f"{field} must be a non-negative number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AnalyticsError("KPI_SEMANTIC_VALUE_INVALID", f"{field} must be a non-negative number") from exc
    if not result.is_finite() or result < 0:
        raise AnalyticsError("KPI_SEMANTIC_VALUE_INVALID", f"{field} must be a non-negative number")
    return result


def _json_number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(round(value, 6))


def _boolean(value: Any, *, true_values: set[str], false_values: set[str], metric: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in true_values:
            return True
        if normalized in false_values:
            return False
    raise AnalyticsError("KPI_SEMANTIC_VALUE_INVALID", f"{metric} has an unsupported semantic value")


class InMemoryAnalyticsKpiStore:
    """Append-only KPI snapshot and idempotency adapter."""

    def __init__(self) -> None:
        self.lock = RLock()
        self._snapshots: dict[str, dict[str, Any]] = {}
        self._commands: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self.outbox: list[dict[str, Any]] = []

    def get(self, identity: str) -> dict[str, Any] | None:
        value = self._snapshots.get(identity)
        return deepcopy(value) if value is not None else None

    def save(self, snapshot: Mapping[str, Any]) -> None:
        identity = str(snapshot["id"])
        prior = self._snapshots.get(identity)
        if prior is not None and prior != snapshot:
            raise AnalyticsError("KPI_SNAPSHOT_CONFLICT", "snapshot id already exists with another payload")
        self._snapshots[identity] = deepcopy(dict(snapshot))

    def command(self, org_id: str, namespace: str, key: str) -> dict[str, Any] | None:
        value = self._commands.get((org_id, namespace, key))
        return deepcopy(value) if value is not None else None

    def save_command(
        self,
        org_id: str,
        namespace: str,
        key: str,
        request_hash: str,
        response: Mapping[str, Any],
    ) -> None:
        self._commands[(org_id, namespace, key)] = {
            "request_hash": request_hash,
            "response": deepcopy(dict(response)),
        }


AnalyticsKpiStore = InMemoryAnalyticsKpiStore
KpiSnapshotStore = InMemoryAnalyticsKpiStore


class AnalyticsKpiService:
    """Aggregate the latest immutable observations into seven fixed KPIs."""

    rule_version = _RULE_VERSION

    def __init__(self, store: InMemoryAnalyticsKpiStore | None = None, *, clock: Any | None = None) -> None:
        self.store = store or InMemoryAnalyticsKpiStore()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self, value: Any = None) -> datetime:
        return _time(value, "calculated_at", required=True) if value is not None else _time(self._clock(), "clock", required=True)  # type: ignore[return-value]

    def _replay(self, org_id: str, key: str, digest: str) -> dict[str, Any] | None:
        prior = self.store.command(org_id, "analytics.kpi.calculate", key)
        if prior is None:
            return None
        if prior["request_hash"] != digest:
            raise AnalyticsError("IDEMPOTENCY_KEY_REUSED", "idempotency key was reused with another payload")
        return deepcopy(prior["response"])

    def _verify_account(
        self,
        *,
        tenant: UUID,
        has_platform: bool,
        external_account_available: bool,
        account_evidence: Mapping[str, Any] | None,
    ) -> str | None:
        if not has_platform:
            return None
        verified = external_account_available
        if account_evidence is not None:
            if not isinstance(account_evidence, Mapping):
                raise AnalyticsError("EXT_ACCOUNT_EVIDENCE_INVALID", "account evidence must be an object")
            marker = account_evidence.get("org_id")
            if marker is not None and _uuid(marker, "account_evidence.org_id") != tenant:
                raise AnalyticsError("TENANT_SCOPE_VIOLATION", "account evidence belongs to another organization")
            forbidden = {"token", "secret", "password", "cookie", "authorization"}
            if {str(key).strip().lower() for key in account_evidence} & forbidden:
                raise AnalyticsError("SENSITIVE_ANALYTICS_INPUT", "account evidence contains a forbidden sensitive field")
            verified = verified or str(account_evidence.get("status", "")).lower() in {"active", "ready", "verified"}
        if not verified:
            raise AnalyticsError("EXT_ACCOUNT_UNAVAILABLE", "platform metrics require verified external account evidence")
        return _hash(account_evidence if account_evidence is not None else {"org_id": str(tenant), "verified": True})

    def _latest(
        self,
        observations: Sequence[Mapping[str, Any]],
        *,
        tenant: UUID,
    ) -> tuple[dict[str, Any], ...]:
        by_id: dict[str, dict[str, Any]] = {}
        by_dedupe: dict[str, dict[str, Any]] = {}
        by_dedupe_version: dict[tuple[str, int], str] = {}
        for raw in observations:
            if not isinstance(raw, Mapping):
                raise AnalyticsError("KPI_INPUT_INVALID", "observations must contain objects")
            value = deepcopy(dict(raw))
            try:
                json.dumps(value, allow_nan=False)
                _OBSERVATION_VALIDATOR.validate(value)
            except (ValidationError, ValueError, TypeError):
                raise AnalyticsError("KPI_INPUT_INVALID", "observation violates its schema") from None
            if value["org_id"] != str(tenant):
                raise AnalyticsError("TENANT_SCOPE_VIOLATION", "observation belongs to another organization")
            identity, digest = value["id"], _hash(value)
            if identity in by_id:
                if _hash(by_id[identity]) != digest:
                    raise AnalyticsError("KPI_INPUT_CONFLICT", "observation id has conflicting snapshots")
                continue
            by_id[identity] = value
            version_key = (value["dedupe_key"], value["observation_version"])
            if version_key in by_dedupe_version and by_dedupe_version[version_key] != digest:
                raise AnalyticsError("KPI_INPUT_CONFLICT", "dedupe key/version has conflicting snapshots")
            by_dedupe_version[version_key] = digest
            current = by_dedupe.get(value["dedupe_key"])
            if current is not None and any(
                current[field] != value[field]
                for field in ("source", "subject_type", "subject_id", "metric_definition_id", "metric_name", "metric_type")
            ):
                raise AnalyticsError("KPI_INPUT_CONFLICT", "observation revisions changed their identity")
            if current is None or value["observation_version"] > current["observation_version"]:
                by_dedupe[value["dedupe_key"]] = value
        return tuple(by_dedupe[key] for key in sorted(by_dedupe))

    def calculate_snapshot(
        self,
        observations: Sequence[Mapping[str, Any]],
        *,
        window_start: Any,
        window_end: Any,
        tenant_context: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
        org_id: Any = None,
        actor_id: Any = None,
        trace_id: Any = None,
        idempotency_key: Any,
        region: Any = None,
        locale: Any = None,
        external_account_available: bool = False,
        account_evidence: Mapping[str, Any] | None = None,
        calculated_at: Any = None,
    ) -> dict[str, Any]:
        tenant, actor, trace, _ = _context(
            tenant_context=tenant_context,
            context=context,
            org_id=org_id,
            actor_id=actor_id,
            trace_id=trace_id,
        )
        if isinstance(observations, (str, bytes, Mapping)) or not isinstance(observations, Sequence):
            raise AnalyticsError("KPI_INPUT_INVALID", "observations must be an array")
        start = _time(window_start, "window_start", required=True)
        end = _time(window_end, "window_end", required=True)
        if start >= end:  # type: ignore[operator]
            raise AnalyticsError("KPI_WINDOW_INVALID", "window_start must be before window_end")
        region_filter, locale_filter = _region(region), _locale(locale)
        at = self._now(calculated_at)
        idempotency = _text(idempotency_key, "idempotency_key", maximum=200)
        latest = self._latest(observations, tenant=tenant)
        windowed: list[dict[str, Any]] = []
        unsupported = 0
        for item in latest:
            observed = _time(item["observed_at"], "observed_at", required=True)
            if not (start <= observed < end):  # type: ignore[operator]
                continue
            if region_filter is not None and item["region"] != region_filter:
                continue
            if locale_filter is not None and item["locale"] != locale_filter:
                continue
            if item["metric_name"] not in _FAMILIES:
                unsupported += 1
                continue
            windowed.append(item)
        if not windowed:
            raise AnalyticsError("KPI_NO_SUPPORTED_INPUT", "no supported observations fall inside the requested window")
        has_platform = any(item["source"] == "platform" for item in windowed)
        account_hash = self._verify_account(
            tenant=tenant,
            has_platform=has_platform,
            external_account_available=external_account_available,
            account_evidence=account_evidence,
        )
        source_scope = "all_verified" if has_platform else "account_free"
        counters = {name: [0, 0] for name in _RATE_NAMES}
        cost_total = Decimal(0)
        cost_count = 0
        lead_total = lead_attributed = lead_qualified = 0
        lead_value = Decimal(0)
        by_channel: dict[str, int] = {}
        issues: dict[tuple[str, str], int] = {}

        def issue(code: str, metric: str, count: int = 1) -> None:
            issues[(code, metric)] = issues.get((code, metric), 0) + count

        if unsupported:
            issue("UNSUPPORTED_METRIC_EXCLUDED", "all", unsupported)
        for item in windowed:
            metric_name = item["metric_name"]
            family = _FAMILIES[metric_name]
            value = item["metric_value"]
            if item["data_quality"] == "raw":
                issue("RAW_INPUT_PRESENT", family)
            elif item["data_quality"] == "estimated":
                issue("ESTIMATED_INPUT_PRESENT", family)
            if family == "publication_success_rate":
                if isinstance(value, bool):
                    counters[family][1] += 1
                    counters[family][0] += int(value)
                    continue
                if not isinstance(value, str):
                    raise AnalyticsError("KPI_SEMANTIC_VALUE_INVALID", "publication outcome must be text or boolean")
                outcome = value.strip().lower()
                if outcome in {"published", "succeeded", "success"}:
                    counters[family][0] += 1
                    counters[family][1] += 1
                elif outcome in {"failed", "blocked", "cancelled", "rejected"}:
                    counters[family][1] += 1
                elif outcome == "unknown":
                    issue("PUBLICATION_UNKNOWN_EXCLUDED", family)
                else:
                    raise AnalyticsError("KPI_SEMANTIC_VALUE_INVALID", "publication outcome is unsupported")
            elif family == "manual_intervention_rate":
                matched = _boolean(value, true_values={"manual", "required", "true", "yes"}, false_values={"automatic", "not_required", "false", "no"}, metric=family)
                counters[family][0] += int(matched)
                counters[family][1] += 1
            elif family == "rights_rejection_rate":
                matched = _boolean(value, true_values={"rejected", "blocked", "true", "yes"}, false_values={"approved", "verified", "false", "no"}, metric=family)
                counters[family][0] += int(matched)
                counters[family][1] += 1
            elif family == "translation_pass_rate":
                matched = _boolean(value, true_values={"passed", "approved", "true", "yes"}, false_values={"failed", "rejected", "false", "no"}, metric=family)
                counters[family][0] += int(matched)
                counters[family][1] += 1
            elif family == "answer_error_rate":
                matched = _boolean(value, true_values={"incorrect", "error", "true", "yes"}, false_values={"correct", "passed", "false", "no"}, metric=family)
                counters[family][0] += int(matched)
                counters[family][1] += 1
            elif family == "cost":
                cost_total += _decimal(value, "cost")
                cost_count += 1
            else:
                lead_total += 1
                if isinstance(value, bool):
                    attributed, qualified, channel, amount = value, False, "unknown" if value else None, Decimal(0)
                elif isinstance(value, Mapping):
                    unknown = set(value) - {"channel", "attributed", "qualified", "value_cents"}
                    if unknown:
                        raise AnalyticsError("KPI_SEMANTIC_VALUE_INVALID", "lead attribution contains unsupported fields")
                    attributed = value.get("attributed")
                    qualified = value.get("qualified", False)
                    if not isinstance(attributed, bool) or not isinstance(qualified, bool):
                        raise AnalyticsError("KPI_SEMANTIC_VALUE_INVALID", "lead attribution flags must be boolean")
                    channel_value = value.get("channel")
                    channel = None if channel_value is None else _text(channel_value, "lead.channel", maximum=64).lower()
                    if channel is not None and _CHANNEL_RE.fullmatch(channel) is None:
                        raise AnalyticsError("KPI_SEMANTIC_VALUE_INVALID", "lead channel must be a de-identified slug")
                    amount = _decimal(value.get("value_cents", 0), "lead.value_cents")
                else:
                    raise AnalyticsError("KPI_SEMANTIC_VALUE_INVALID", "lead attribution must be boolean or object")
                if qualified and not attributed:
                    raise AnalyticsError("KPI_SEMANTIC_VALUE_INVALID", "qualified lead must be attributed")
                if attributed and channel is None:
                    raise AnalyticsError("KPI_SEMANTIC_VALUE_INVALID", "attributed lead requires channel")
                if attributed:
                    lead_attributed += 1
                    by_channel[channel] = by_channel.get(channel, 0) + 1  # type: ignore[index]
                if qualified:
                    lead_qualified += 1
                lead_value += amount
        metrics: dict[str, Any] = {
            name: _ratio(counters[name][0], counters[name][1]) for name in _RATE_NAMES
        }
        metrics["cost"] = {
            "total_cents": _json_number(cost_total),
            "sample_count": cost_count,
            "average_cents": None if cost_count == 0 else _json_number(cost_total / cost_count),
        }
        metrics["lead_attribution"] = {
            "total": lead_total,
            "attributed": lead_attributed,
            "qualified": lead_qualified,
            "attribution_rate": None if lead_total == 0 else round(lead_attributed / lead_total, 6),
            "total_value_cents": _json_number(lead_value),
            "by_channel": {key: by_channel[key] for key in sorted(by_channel)},
        }
        for name in _RATE_NAMES:
            if metrics[name]["denominator"] == 0:
                issue(f"INSUFFICIENT_{name.upper()}", name, 0)
        if cost_count == 0:
            issue("INSUFFICIENT_COST", "cost", 0)
        if lead_total == 0:
            issue("INSUFFICIENT_LEAD_ATTRIBUTION", "lead_attribution", 0)
        quality_issues = [
            {"code": code, "metric": metric, "count": count}
            for (code, metric), count in sorted(issues.items())
        ]
        incomplete = any(item["code"].startswith("INSUFFICIENT_") for item in quality_issues)
        included = sorted(windowed, key=lambda item: item["id"])
        input_ids = [item["id"] for item in included]
        input_snapshot_hash = _hash([{"id": item["id"], "hash": _hash(item)} for item in included])
        request = {
            "operation": "calculate_kpi_snapshot",
            "window_start": _stamp(start),  # type: ignore[arg-type]
            "window_end": _stamp(end),  # type: ignore[arg-type]
            "region": region_filter,
            "locale": locale_filter,
            "input_snapshot_hash": input_snapshot_hash,
            "account_evidence_hash": account_hash,
            "quality_issues": quality_issues,
            "rule_version": _RULE_VERSION,
        }
        digest = _hash(request)
        with getattr(self.store, "lock", nullcontext()):
            replay = self._replay(str(tenant), idempotency, digest)
            if replay is not None:
                return replay
            identity = str(uuid5(
                _SNAPSHOT_NAMESPACE,
                f"{tenant}:{digest}",
            ))
            prior = self.store.get(identity)
            if prior is not None:
                self.store.save_command(str(tenant), "analytics.kpi.calculate", idempotency, digest, prior)
                return prior
            base = {
                "id": identity,
                "org_id": str(tenant),
                "window_start": request["window_start"],
                "window_end": request["window_end"],
                "region": region_filter,
                "locale": locale_filter,
                "source_scope": source_scope,
                "input_observation_ids": input_ids,
                "input_snapshot_hash": input_snapshot_hash,
                "metrics": metrics,
                "status": "insufficient_data" if incomplete else "complete",
                "quality_issues": quality_issues,
                "rule_version": _RULE_VERSION,
                "created_by": str(actor),
                "created_at": _stamp(at),
            }
            result = {**base, "snapshot_hash": _hash(base)}
            try:
                _SNAPSHOT_VALIDATOR.validate(result)
            except ValidationError as exc:
                raise AnalyticsError("KPI_SNAPSHOT_INVALID", "computed snapshot violates its schema") from exc
            self.store.save(result)
            event_payload = {
                "aggregate_id": identity,
                "aggregate_version": 1,
                "from_state": None,
                "to_state": result["status"],
                "command": "calculate",
                "snapshot_hash": result["snapshot_hash"],
                "reason": None,
                "window_start": result["window_start"],
                "window_end": result["window_end"],
                "input_snapshot_hash": input_snapshot_hash,
                "status": result["status"],
            }
            event = {
                "event_id": str(uuid5(_EVENT_NAMESPACE, f"analytics.kpi_snapshot.created:{identity}")),
                "event_type": "analytics.kpi_snapshot.created",
                "event_schema_version": 1,
                "occurred_at": _stamp(at),
                "org_id": str(tenant),
                "trace_id": trace,
                "correlation_id": None,
                "causation_id": None,
                "aggregate_type": "AnalyticsKpiSnapshot",
                "aggregate_id": identity,
                "aggregate_version": 1,
                "actor_type": "user",
                "actor_id": str(actor),
                "idempotency_key": idempotency,
                "payload": event_payload,
                "payload_hash": _hash(event_payload),
            }
            self.store.outbox.append(deepcopy(event))
            self.store.audit.append(
                {
                    "event_type": "analytics.kpi_snapshot.created",
                    "org_id": str(tenant),
                    "actor_id": str(actor),
                    "trace_id": trace,
                    "snapshot_id": identity,
                    "status": result["status"],
                    "source_scope": source_scope,
                    "input_count": len(input_ids),
                    "input_snapshot_hash": input_snapshot_hash,
                    "snapshot_hash": result["snapshot_hash"],
                    "occurred_at": _stamp(at),
                }
            )
            self.store.save_command(str(tenant), "analytics.kpi.calculate", idempotency, digest, result)
            return deepcopy(result)

    calculate = calculate_snapshot
    aggregate = calculate_snapshot
    compute = calculate_snapshot
    build_snapshot = calculate_snapshot

    def get_snapshot(
        self,
        snapshot_id: Any,
        *,
        tenant_context: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
        org_id: Any = None,
    ) -> dict[str, Any]:
        tenant, _, _, _ = _context(tenant_context=tenant_context, context=context, org_id=org_id)
        identity = str(_uuid(snapshot_id, "snapshot_id"))
        with getattr(self.store, "lock", nullcontext()):
            value = self.store.get(identity)
            if value is None:
                raise AnalyticsError("KPI_SNAPSHOT_NOT_FOUND", "KPI snapshot does not exist")
            if value["org_id"] != str(tenant):
                raise AnalyticsError("TENANT_SCOPE_VIOLATION", "KPI snapshot belongs to another organization")
            return value

    get = get_snapshot


KpiAggregationService = AnalyticsKpiService
AnalyticsMetricService = AnalyticsKpiService
AnalyticsMetricsService = AnalyticsKpiService


__all__ = [
    "AnalyticsKpiError",
    "AnalyticsKpiService",
    "AnalyticsKpiStore",
    "AnalyticsMetricService",
    "AnalyticsMetricsService",
    "InMemoryAnalyticsKpiStore",
    "KpiAggregationError",
    "KpiAggregationService",
    "KpiSnapshotStore",
]
