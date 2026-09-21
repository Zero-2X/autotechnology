"""Deterministic, tenant-scoped TopicOpportunity scoring and human shortlist."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker

from .infrastructure.opportunity_schema import DEFAULT_VERSION, initialize
from .signal import TopicSignalError, TopicSignalImportService


ROOT = Path(__file__).resolve().parents[2]
OPPORTUNITY_VALIDATOR = Draft202012Validator(
    json.loads((ROOT / "packages/contracts/jsonschema/topic-opportunity.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
SNAPSHOT_VALIDATOR = Draft202012Validator(
    json.loads((ROOT / "packages/contracts/jsonschema/topic-score-snapshot.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
POSITIVE = ("demand", "relevance", "evidence_availability", "differentiation", "timeliness")
COMPONENTS = (*POSITIVE, "cost", "risk")


class TopicOpportunityError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _uuid(value: UUID | str, name: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise TopicOpportunityError("INVALID_TOPIC_COMMAND", f"{name} must be a UUID") from exc


def _text(value: object, name: str, limit: int = 512) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise TopicOpportunityError("INVALID_TOPIC_COMMAND", f"{name} must be nonempty and at most {limit} characters")
    return value.strip()


def _utc(value: str, name: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise TopicOpportunityError("INVALID_EXPIRY", f"{name} must be a UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise TopicOpportunityError("INVALID_EXPIRY", f"{name} must use UTC")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _hash(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode()).hexdigest()


def _component(value: object, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TopicOpportunityError("INVALID_SCORE_COMPONENT", f"{name} must be a number")
    try:
        score = Decimal(str(value))
    except InvalidOperation as exc:
        raise TopicOpportunityError("INVALID_SCORE_COMPONENT", f"{name} must be a number") from exc
    if not score.is_finite() or score < 0 or score > 100:
        raise TopicOpportunityError("INVALID_SCORE_COMPONENT", f"{name} must be between 0 and 100")
    return score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _two(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class TopicOpportunityService:
    def __init__(self, signal_service: TopicSignalImportService, database: str | Path = ":memory:") -> None:
        self.signals = signal_service
        self._connection = sqlite3.connect(str(database), timeout=30, check_same_thread=False)
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.row_factory = sqlite3.Row
        initialize(self._connection)
        self._lock = RLock()

    def close(self) -> None:
        self._connection.close()

    def _prior(self, tenant: str, key: str, digest: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT payload_hash, response FROM topic_opportunity_commands WHERE org_id = ? AND idempotency_key = ?",
            (tenant, key),
        ).fetchone()
        if row is None:
            return None
        if row["payload_hash"] != digest:
            raise TopicOpportunityError("IDEMPOTENCY_KEY_REUSED", "command payload differs from prior request")
        return json.loads(row["response"])

    def _save_command(self, tenant: str, key: str, digest: str, actor: str, trace: str, response: dict[str, Any]) -> None:
        self._connection.execute(
            "INSERT INTO topic_opportunity_commands (org_id, idempotency_key, payload_hash, actor_id, trace_id, response) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tenant, key, digest, actor, trace, json.dumps(response, ensure_ascii=False, sort_keys=True)),
        )

    def score(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
        idempotency_key: str, signal_ids: Sequence[UUID | str], canonical_topic: str,
        scores: Mapping[str, object], expires_at: str, scoring_version: str = DEFAULT_VERSION,
    ) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id", 256), _text(idempotency_key, "idempotency_key", 200)
        title = _text(canonical_topic, "canonical_topic")
        canonical_key = " ".join(title.casefold().split())
        expiry = _utc(expires_at, "expires_at")
        if expiry <= _now():
            raise TopicOpportunityError("INVALID_EXPIRY", "expires_at must be in the future")
        if isinstance(signal_ids, (str, bytes)) or not isinstance(signal_ids, Sequence) or not signal_ids:
            raise TopicOpportunityError("INVALID_SIGNAL_IDS", "at least one signal is required")
        ids = [_uuid(value, "signal_id") for value in signal_ids]
        if len(ids) != len(set(ids)) or len(ids) > 100:
            raise TopicOpportunityError("INVALID_SIGNAL_IDS", "signal IDs must be unique, at most 100")
        if not isinstance(scores, Mapping) or set(scores) != set(COMPONENTS):
            raise TopicOpportunityError("INVALID_SCORE_COMPONENT", "seven score components are required")
        requested = {name: _component(scores[name], name) for name in COMPONENTS}
        version = _text(scoring_version, "scoring_version", 64)
        digest = _hash({"signal_ids": ids, "canonical_topic": canonical_key,
                        "scores": {name: str(requested[name]) for name in COMPONENTS},
                        "expires_at": expiry, "scoring_version": version})
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                config = self._connection.execute(
                    "SELECT weights_json FROM topic_scoring_versions WHERE version = ?", (version,)
                ).fetchone()
                if config is None:
                    raise TopicOpportunityError("UNKNOWN_SCORING_VERSION", "scoring version is not registered")
                existing = self._connection.execute(
                    "SELECT id FROM topic_opportunities WHERE org_id = ? AND canonical_key = ? "
                    "AND status IN ('proposed', 'shortlisted') AND expires_at > ?",
                    (tenant, canonical_key, _now()),
                ).fetchone()
                if existing is not None:
                    raise TopicOpportunityError("TOPIC_ACTIVE_CONFLICT", "active opportunity already exists")
                inputs = []
                for signal_id in sorted(ids):
                    try:
                        signal = self.signals.get(org_id=tenant, signal_id=signal_id)
                    except TopicSignalError as exc:
                        raise TopicOpportunityError("TENANT_SCOPE_VIOLATION", "signal is not in this organization") from exc
                    evidence = bool(signal["terms_snapshot_ref"] or signal["license_ref"])
                    publishable = (signal["usage_rights_status"] == "verified" and evidence
                                   and signal["permitted_use"] in {"editorial", "commercial"})
                    reasons = []
                    if not evidence:
                        reasons.append("missing_rights_evidence")
                    if signal["usage_rights_status"] != "verified":
                        reasons.append(f"usage_rights_{signal['usage_rights_status']}")
                    if signal["permitted_use"] not in {"editorial", "commercial"}:
                        reasons.append(f"permitted_use_{signal['permitted_use']}")
                    inputs.append({"id": signal_id, "source_ref": signal["source_ref"],
                                   "usage_rights_status": signal["usage_rights_status"],
                                   "evidence_present": evidence, "publishable": publishable,
                                   "input_hash": _hash(signal),
                                   "deduction_reasons": reasons})
                blocked = not all(item["publishable"] for item in inputs)
                effective = dict(requested)
                if blocked:
                    effective["evidence_availability"] = Decimal(0)
                weights = {name: Decimal(str(value)) for name, value in json.loads(config["weights_json"]).items()}
                positive = sum((effective[name] * weights[name] for name in POSITIVE), Decimal(0))
                cost_deduction = effective["cost"] * weights["cost"]
                risk_deduction = effective["risk"] * weights["risk"]
                total = max(Decimal(0), min(Decimal(100), positive - cost_deduction - risk_deduction))
                breakdown = {name: _two(effective[name]) for name in COMPONENTS}
                opportunity_id, snapshot_id = str(uuid4()), str(uuid4())
                content = {"scoring_version": version, "weights": {name: float(weights[name]) for name in COMPONENTS},
                           "signal_inputs": {"signals": inputs}, "score_components": breakdown,
                           "total_score": _two(total),
                           "deductions": {"cost": _two(cost_deduction), "risk": _two(risk_deduction),
                                          "rights_blocked": blocked}}
                content_hash = _hash(content)
                input_snapshot_hash = _hash(content["signal_inputs"])
                snapshot = {"id": snapshot_id, "org_id": tenant, "opportunity_id": opportunity_id,
                            "formula_version": version, **content,
                            "reasoning": "Rights or evidence block shortlist" if blocked else "Weighted component score",
                            "content_hash": content_hash, "input_snapshot_hash": input_snapshot_hash,
                            "created_at": _now()}
                risk_band = "R4" if blocked else f"R{min(4, int(effective['risk'] // 20))}"
                opportunity = {
                    "id": opportunity_id, "org_id": tenant, "signal_ids": sorted(ids),
                    "topic_key": canonical_key, "title": title, "question": title,
                    "score_snapshot_id": snapshot_id, "score_snapshot_hash": content_hash,
                    "owner_actor_id": actor, "priority": "normal", "due_at": expiry,
                    "editorial_plan_id": None, "risk_level": risk_band,
                    "status": "proposed", "canonical_topic": title, "score_total": _two(total),
                    "score_breakdown": breakdown, "scoring_version": version,
                    "decision_reason": None, "expires_at": expiry, "version": 0,
                    "shortlist_eligible": not blocked,
                }
                SNAPSHOT_VALIDATOR.validate(snapshot)
                OPPORTUNITY_VALIDATOR.validate(opportunity)
                self._connection.execute(
                    "INSERT INTO topic_opportunities (id, org_id, canonical_key, status, expires_at, version, payload) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (opportunity_id, tenant, canonical_key, "proposed", expiry, 0,
                     json.dumps(opportunity, ensure_ascii=False, sort_keys=True)),
                )
                self._connection.execute(
                    "INSERT INTO topic_score_snapshots (id, org_id, opportunity_id, content_hash, payload) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (snapshot_id, tenant, opportunity_id, content_hash,
                     json.dumps(snapshot, ensure_ascii=False, sort_keys=True)),
                )
                event_id = str(uuid4())
                event_payload = {"aggregate_id": opportunity_id, "aggregate_version": 1,
                                 "snapshot_hash": content_hash, "reason": snapshot["reasoning"]}
                envelope = {"event_id": event_id, "event_type": "topic.opportunity.scored",
                            "event_schema_version": 1, "occurred_at": _now(), "org_id": tenant,
                            "trace_id": trace, "correlation_id": None, "causation_id": None,
                            "aggregate_type": "TopicOpportunity", "aggregate_id": opportunity_id,
                            "aggregate_version": 1, "actor_type": "user", "actor_id": actor,
                            "idempotency_key": key + ":scored", "payload": event_payload,
                            "payload_hash": _hash(event_payload)}
                self._connection.execute(
                    "INSERT INTO topic_opportunity_events (event_id, org_id, event_type, envelope) VALUES (?, ?, ?, ?)",
                    (event_id, tenant, "topic.opportunity.scored", json.dumps(envelope, sort_keys=True)),
                )
                response = {"opportunity": opportunity, "snapshot": snapshot}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except Exception:
                self._connection.rollback()
                raise

    def shortlist(
        self, *, org_id: UUID | str, opportunity_id: UUID | str, actor_id: UUID | str,
        trace_id: str, idempotency_key: str, expected_version: int, decision_reason: str,
    ) -> dict[str, Any]:
        tenant, identity, actor = _uuid(org_id, "org_id"), _uuid(opportunity_id, "opportunity_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id", 256), _text(idempotency_key, "idempotency_key", 200)
        reason = _text(decision_reason, "decision_reason", 2048)
        if type(expected_version) is not int or expected_version < 0:
            raise TopicOpportunityError("VERSION_CONFLICT", "expected_version must be nonnegative")
        digest = _hash({"opportunity_id": identity, "expected_version": expected_version, "decision_reason": reason})
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                row = self._connection.execute(
                    "SELECT payload FROM topic_opportunities WHERE id = ? AND org_id = ?", (identity, tenant)
                ).fetchone()
                if row is None:
                    raise TopicOpportunityError("TENANT_SCOPE_VIOLATION", "opportunity is not in this organization")
                opportunity = json.loads(row["payload"])
                if opportunity["version"] != expected_version:
                    raise TopicOpportunityError("VERSION_CONFLICT", "opportunity version changed")
                if opportunity["expires_at"] <= _now():
                    raise TopicOpportunityError("TOPIC_OPPORTUNITY_EXPIRED", "opportunity has expired")
                if opportunity["status"] != "proposed":
                    raise TopicOpportunityError("INVALID_TOPIC_STATE", "only proposed opportunities can be shortlisted")
                if not opportunity["shortlist_eligible"]:
                    raise TopicOpportunityError("RIGHTS_BLOCK_SHORTLIST", "signal rights or evidence block shortlist")
                opportunity.update(status="shortlisted", decision_reason=reason, version=expected_version + 1)
                OPPORTUNITY_VALIDATOR.validate(opportunity)
                updated = self._connection.execute(
                    "UPDATE topic_opportunities SET status = ?, version = ?, payload = ? "
                    "WHERE id = ? AND org_id = ? AND version = ?",
                    ("shortlisted", opportunity["version"], json.dumps(opportunity, ensure_ascii=False, sort_keys=True),
                     identity, tenant, expected_version),
                )
                if updated.rowcount != 1:
                    raise TopicOpportunityError("VERSION_CONFLICT", "opportunity version changed")
                response = {"opportunity": opportunity}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except Exception:
                self._connection.rollback()
                raise

    def transition(
        self, *, org_id: UUID | str, opportunity_id: UUID | str, actor_id: UUID | str,
        trace_id: str, idempotency_key: str, action: str, expected_version: int,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Apply an explicit human/system state command with an auditable reason."""
        tenant, identity, actor = _uuid(org_id, "org_id"), _uuid(opportunity_id, "opportunity_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id", 256), _text(idempotency_key, "idempotency_key", 200)
        action = _text(action, "action", 32)
        if action not in {"reject", "defer", "expire", "resume"}:
            raise TopicOpportunityError("INVALID_TOPIC_ACTION", "unsupported opportunity action")
        if type(expected_version) is not int or expected_version < 0:
            raise TopicOpportunityError("VERSION_CONFLICT", "expected_version must be nonnegative")
        normalized_reason = _text(reason, "reason", 2048) if reason is not None else None
        if action in {"reject", "defer"} and normalized_reason is None:
            raise TopicOpportunityError("REASON_REQUIRED", "reject and defer require a reason")
        digest = _hash({"opportunity_id": identity, "action": action,
                        "expected_version": expected_version, "reason": normalized_reason})
        target = {"reject": "rejected", "defer": "deferred", "expire": "expired", "resume": "proposed"}[action]
        allowed = {
            "proposed": {"reject", "defer", "expire"},
            "shortlisted": {"reject", "defer", "expire"},
            "deferred": {"reject", "expire", "resume"},
            "rejected": set(), "expired": set(),
        }
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                row = self._connection.execute(
                    "SELECT payload FROM topic_opportunities WHERE org_id = ? AND id = ?", (tenant, identity)
                ).fetchone()
                if row is None:
                    raise TopicOpportunityError("TENANT_SCOPE_VIOLATION", "opportunity is not in this organization")
                opportunity = json.loads(row["payload"])
                if opportunity["version"] != expected_version:
                    raise TopicOpportunityError("VERSION_CONFLICT", "opportunity version changed")
                if allowed.get(opportunity["status"], set()).isdisjoint({action}):
                    raise TopicOpportunityError("INVALID_TOPIC_STATE", f"cannot {action} from {opportunity['status']}")
                if self._connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'topic_briefs'"
                ).fetchone() is not None and self._connection.execute(
                    "SELECT 1 FROM topic_briefs WHERE org_id = ? AND opportunity_id = ? "
                    "AND status IN ('locked', 'approved') LIMIT 1",
                    (tenant, identity),
                ).fetchone() is not None:
                    raise TopicOpportunityError("BRIEF_LOCKED", "locked brief prevents opportunity state changes")
                previous = opportunity["status"]
                opportunity.update(status=target, decision_reason=normalized_reason or "expired",
                                   version=expected_version + 1,
                                   shortlist_eligible=(target == "proposed"))
                OPPORTUNITY_VALIDATOR.validate(opportunity)
                updated = self._connection.execute(
                    "UPDATE topic_opportunities SET status = ?, version = ?, payload = ? "
                    "WHERE id = ? AND org_id = ? AND version = ?",
                    (target, opportunity["version"], json.dumps(opportunity, ensure_ascii=False, sort_keys=True),
                     identity, tenant, expected_version),
                )
                if updated.rowcount != 1:
                    raise TopicOpportunityError("VERSION_CONFLICT", "opportunity changed while transitioning")
                sequence = self._connection.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 FROM topic_opportunity_state_events "
                    "WHERE org_id = ? AND opportunity_id = ?", (tenant, identity)
                ).fetchone()[0]
                event_id = str(uuid4())
                payload = {"aggregate_id": identity, "aggregate_version": opportunity["version"],
                           "from_state": previous, "to_state": target, "command": action,
                           "reason": normalized_reason or "expired"}
                envelope = {"event_id": event_id, "event_type": f"topic.opportunity.{action}",
                            "event_schema_version": 1, "occurred_at": _now(), "org_id": tenant,
                            "trace_id": trace, "correlation_id": None, "causation_id": None,
                            "aggregate_type": "TopicOpportunity", "aggregate_id": identity,
                            "aggregate_version": opportunity["version"], "actor_type": "user", "actor_id": actor,
                            "idempotency_key": key, "payload": payload, "payload_hash": _hash(payload)}
                self._connection.execute(
                    "INSERT INTO topic_opportunity_state_events "
                    "(event_id, org_id, opportunity_id, event_type, sequence, envelope) VALUES (?, ?, ?, ?, ?, ?)",
                    (event_id, tenant, identity, envelope["event_type"], sequence,
                     json.dumps(envelope, ensure_ascii=False, sort_keys=True)),
                )
                response = {"opportunity": opportunity, "event": envelope}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except Exception:
                self._connection.rollback()
                raise

    def get(self, *, org_id: UUID | str, opportunity_id: UUID | str) -> dict[str, Any]:
        tenant, identity = _uuid(org_id, "org_id"), _uuid(opportunity_id, "opportunity_id")
        row = self._connection.execute(
            "SELECT payload FROM topic_opportunities WHERE org_id = ? AND id = ?", (tenant, identity)
        ).fetchone()
        if row is None:
            raise TopicOpportunityError("TENANT_SCOPE_VIOLATION", "opportunity is not in this organization")
        return json.loads(row["payload"])

    def assert_brief_eligible(self, *, org_id: UUID | str, opportunity_id: UUID | str) -> dict[str, Any]:
        opportunity = self.get(org_id=org_id, opportunity_id=opportunity_id)
        if opportunity["expires_at"] <= _now():
            raise TopicOpportunityError("TOPIC_OPPORTUNITY_EXPIRED", "opportunity has expired")
        if opportunity["status"] != "shortlisted":
            raise TopicOpportunityError("INVALID_TOPIC_STATE", "opportunity must be shortlisted")
        return opportunity

    def get_snapshot(self, *, org_id: UUID | str, snapshot_id: UUID | str) -> dict[str, Any]:
        tenant, identity = _uuid(org_id, "org_id"), _uuid(snapshot_id, "snapshot_id")
        row = self._connection.execute(
            "SELECT payload FROM topic_score_snapshots WHERE org_id = ? AND id = ?", (tenant, identity)
        ).fetchone()
        if row is None:
            raise TopicOpportunityError("TENANT_SCOPE_VIOLATION", "score snapshot is not in this organization")
        return json.loads(row["payload"])

    def recompute_snapshot(self, *, org_id: UUID | str, snapshot_id: UUID | str) -> dict[str, Any]:
        snapshot = self.get_snapshot(org_id=org_id, snapshot_id=snapshot_id)
        content = {key: snapshot[key] for key in (
            "scoring_version", "weights", "signal_inputs", "score_components", "total_score", "deductions"
        )}
        if _hash(content) != snapshot["content_hash"]:
            raise TopicOpportunityError("SCORING_SNAPSHOT_MISMATCH", "snapshot content hash differs")
        if _hash(snapshot["signal_inputs"]) != snapshot["input_snapshot_hash"]:
            raise TopicOpportunityError("SCORING_SNAPSHOT_MISMATCH", "input snapshot hash differs")
        components = {name: Decimal(str(snapshot["score_components"][name])) for name in COMPONENTS}
        weights = {name: Decimal(str(snapshot["weights"][name])) for name in COMPONENTS}
        calculated = sum((components[name] * weights[name] for name in POSITIVE), Decimal(0))
        calculated -= components["cost"] * weights["cost"] + components["risk"] * weights["risk"]
        calculated = max(Decimal(0), min(Decimal(100), calculated))
        if _two(calculated) != snapshot["total_score"]:
            raise TopicOpportunityError("SCORING_SNAPSHOT_MISMATCH", "snapshot total cannot be reproduced")
        return snapshot

    def verify_snapshot(
        self, *, org_id: UUID | str, snapshot_id: UUID | str, actor_id: UUID | str,
        trace_id: str, idempotency_key: str,
    ) -> dict[str, Any]:
        """Verify an immutable snapshot against its captured signal inputs and current signals."""
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id", 256), _text(idempotency_key, "idempotency_key", 200)
        identity = _uuid(snapshot_id, "snapshot_id")
        digest = _hash({"snapshot_id": identity})
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    "SELECT payload FROM topic_score_snapshot_verifications WHERE org_id = ? AND snapshot_id = ? "
                    "AND idempotency_key = ?", (tenant, identity, key)
                ).fetchone()
                if row is not None:
                    self._connection.commit()
                    return json.loads(row["payload"])
                snapshot = self.get_snapshot(org_id=tenant, snapshot_id=identity)
                self.recompute_snapshot(org_id=tenant, snapshot_id=identity)
                drift: list[str] = []
                for item in snapshot["signal_inputs"]["signals"]:
                    try:
                        signal = self.signals.get(org_id=tenant, signal_id=item["id"])
                    except TopicSignalError:
                        drift.append(item["id"] + ":missing")
                        continue
                    if _hash(signal) != item["input_hash"]:
                        drift.append(item["id"] + ":changed")
                report = {"snapshot_id": identity, "org_id": tenant, "verified": not drift,
                          "drift": drift, "content_hash": snapshot["content_hash"],
                          "input_snapshot_hash": snapshot["input_snapshot_hash"],
                          "actor_id": actor, "trace_id": trace}
                self._connection.execute(
                    "INSERT INTO topic_score_snapshot_verifications "
                    "(org_id, snapshot_id, idempotency_key, payload_hash, payload) VALUES (?, ?, ?, ?, ?)",
                    (tenant, identity, key, digest, json.dumps(report, ensure_ascii=False, sort_keys=True)),
                )
                self._connection.commit()
                return report
            except Exception:
                self._connection.rollback()
                raise

    def scored_events(self, *, org_id: UUID | str) -> tuple[dict[str, Any], ...]:
        tenant = _uuid(org_id, "org_id")
        rows = self._connection.execute(
            "SELECT envelope FROM topic_opportunity_events WHERE org_id = ? ORDER BY event_id", (tenant,)
        ).fetchall()
        return tuple(json.loads(row["envelope"]) for row in rows)

    def state_events(self, *, org_id: UUID | str, opportunity_id: UUID | str | None = None) -> tuple[dict[str, Any], ...]:
        tenant = _uuid(org_id, "org_id")
        if opportunity_id is None:
            rows = self._connection.execute(
                "SELECT envelope FROM topic_opportunity_state_events WHERE org_id = ? "
                "ORDER BY opportunity_id, sequence", (tenant,)
            ).fetchall()
        else:
            identity = _uuid(opportunity_id, "opportunity_id")
            rows = self._connection.execute(
                "SELECT envelope FROM topic_opportunity_state_events WHERE org_id = ? AND opportunity_id = ? "
                "ORDER BY sequence", (tenant, identity)
            ).fetchall()
        return tuple(json.loads(row["envelope"]) for row in rows)


__all__ = ["TopicOpportunityError", "TopicOpportunityService"]
