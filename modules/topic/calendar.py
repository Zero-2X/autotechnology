"""Tenant-scoped editorial calendar assignments and manual overrides."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker

from .infrastructure.calendar_schema import initialize
from .opportunity import TopicOpportunityError, TopicOpportunityService


ROOT = Path(__file__).resolve().parents[2]
OPPORTUNITY_VALIDATOR = Draft202012Validator(
    json.loads((ROOT / "packages/contracts/jsonschema/topic-opportunity.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
PRIORITIES = frozenset({"low", "normal", "high", "urgent"})


class EditorialCalendarError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _uuid(value: UUID | str, name: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise EditorialCalendarError("INVALID_CALENDAR_COMMAND", f"{name} must be a UUID") from exc


def _text(value: object, name: str, limit: int = 2048) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise EditorialCalendarError("INVALID_CALENDAR_COMMAND", f"{name} must be nonempty and at most {limit} characters")
    return value.strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _utc(value: object) -> str:
    if not isinstance(value, str):
        raise EditorialCalendarError("INVALID_DUE_AT", "due_at must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise EditorialCalendarError("INVALID_DUE_AT", "due_at must be a UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise EditorialCalendarError("INVALID_DUE_AT", "due_at must use UTC")
    normalized = parsed.astimezone(timezone.utc)
    if normalized <= datetime.now(timezone.utc):
        raise EditorialCalendarError("INVALID_DUE_AT", "due_at must be in the future")
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _hash(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode()).hexdigest()


class EditorialCalendarService:
    """Calendar writes share the opportunity transaction and optimistic version."""

    def __init__(self, opportunities: TopicOpportunityService) -> None:
        self.opportunities = opportunities
        self._connection = opportunities._connection
        self._lock = opportunities._lock
        initialize(self._connection)

    def _prior(self, tenant: str, key: str, digest: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT payload_hash, response FROM topic_editorial_commands WHERE org_id = ? AND idempotency_key = ?",
            (tenant, key),
        ).fetchone()
        if row is None:
            return None
        if row["payload_hash"] != digest:
            raise EditorialCalendarError("IDEMPOTENCY_KEY_REUSED", "calendar command payload differs")
        return json.loads(row["response"])

    def _save_command(self, tenant: str, key: str, digest: str, actor: str, trace: str,
                      response: dict[str, Any]) -> None:
        self._connection.execute(
            "INSERT INTO topic_editorial_commands (org_id, idempotency_key, payload_hash, actor_id, trace_id, response) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tenant, key, digest, actor, trace, json.dumps(response, ensure_ascii=False, sort_keys=True)),
        )

    def _audit(self, *, tenant: str, opportunity_id: str, actor: str, trace: str,
               key: str, event_type: str, plan: Mapping[str, Any],
               input_version: int, output_version: int, reason: str | None) -> None:
        audit_id = str(uuid4())
        occurred_at = _now()
        sequence = self._connection.execute(
            "SELECT COALESCE(MAX(audit_seq), 0) + 1 FROM topic_editorial_audit"
        ).fetchone()[0]
        payload = {
            "aggregate_id": opportunity_id, "aggregate_version": output_version,
            "plan_id": plan["id"], "plan_version": plan["version_no"],
            "owner_id": plan["owner_id"], "priority": plan["priority"],
            "due_at": plan["due_at"], "manual_override_reason": reason,
            "input_version": input_version, "output_version": output_version,
        }
        envelope = {
            "audit_id": audit_id, "event_type": event_type, "occurred_at": occurred_at,
            "org_id": tenant, "trace_id": trace, "actor_id": actor,
            "idempotency_key": key, "payload": payload, "payload_hash": _hash(payload),
        }
        self._connection.execute(
            "INSERT INTO topic_editorial_audit (audit_id, org_id, opportunity_id, event_type, occurred_at, audit_seq, envelope) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (audit_id, tenant, opportunity_id, event_type, occurred_at, sequence,
             json.dumps(envelope, ensure_ascii=False, sort_keys=True)),
        )

    def schedule(
        self, *, org_id: UUID | str, opportunity_id: UUID | str, actor_id: UUID | str,
        trace_id: str, idempotency_key: str, expected_version: int,
        owner_id: UUID | str, priority: str, due_at: str,
        manual_override_reason: str | None = None, override: bool = False,
    ) -> dict[str, Any]:
        tenant, identity, actor, owner = (_uuid(org_id, "org_id"), _uuid(opportunity_id, "opportunity_id"),
                                           _uuid(actor_id, "actor_id"), _uuid(owner_id, "owner_id"))
        trace, key = _text(trace_id, "trace_id", 256), _text(idempotency_key, "idempotency_key", 200)
        if priority not in PRIORITIES:
            raise EditorialCalendarError("INVALID_PRIORITY", "priority is invalid")
        if type(expected_version) is not int or expected_version < 0:
            raise EditorialCalendarError("VERSION_CONFLICT", "expected_version must be nonnegative")
        due = _utc(due_at)
        reason = None
        if override:
            reason = _text(manual_override_reason, "manual_override_reason", 2048)
        elif manual_override_reason is not None:
            raise EditorialCalendarError("UNEXPECTED_OVERRIDE_REASON", "override reason requires override command")
        digest = _hash({"opportunity_id": identity, "expected_version": expected_version,
                        "owner_id": owner, "priority": priority, "due_at": due,
                        "manual_override_reason": reason, "override": override})
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
                    raise EditorialCalendarError("TENANT_SCOPE_VIOLATION", "opportunity is not in this organization")
                opportunity = json.loads(row["payload"])
                if opportunity["version"] != expected_version:
                    raise EditorialCalendarError("VERSION_CONFLICT", "opportunity version changed")
                if opportunity["expires_at"] <= _now():
                    raise EditorialCalendarError("TOPIC_OPPORTUNITY_EXPIRED", "opportunity has expired")
                if datetime.fromisoformat(due.replace("Z", "+00:00")) > datetime.fromisoformat(opportunity["expires_at"].replace("Z", "+00:00")):
                    raise EditorialCalendarError("INVALID_DUE_AT", "due_at cannot exceed opportunity expiry")
                existing = self._connection.execute(
                    "SELECT payload FROM topic_editorial_plans WHERE org_id = ? AND opportunity_id = ? "
                    "AND status = 'active' ORDER BY version_no DESC LIMIT 1", (tenant, identity)
                ).fetchone()
                if existing is not None and not override:
                    raise EditorialCalendarError("EDITORIAL_PLAN_EXISTS", "active editorial plan already exists")
                if existing is not None:
                    old_plan = json.loads(existing["payload"])
                    next_version = int(old_plan["version_no"]) + 1
                else:
                    old_plan = None
                    next_version = 1
                plan = {
                    "id": str(uuid4()), "org_id": tenant, "opportunity_id": identity,
                    "version_no": next_version, "status": "active", "owner_id": owner,
                    "priority": priority, "due_at": due, "manual_override_reason": reason,
                    "created_by": actor, "created_at": _now(),
                }
                if old_plan is not None:
                    old_plan["status"] = "superseded"
                    self._connection.execute(
                        "UPDATE topic_editorial_plans SET status = 'superseded', payload = ? WHERE id = ? AND org_id = ?",
                        (json.dumps(old_plan, ensure_ascii=False, sort_keys=True), old_plan["id"], tenant),
                    )
                opportunity.update(owner_actor_id=owner, priority=priority, due_at=due,
                                  editorial_plan_id=plan["id"], version=expected_version + 1)
                OPPORTUNITY_VALIDATOR.validate(opportunity)
                updated = self._connection.execute(
                    "UPDATE topic_opportunities SET version = ?, status = ?, expires_at = ?, payload = ? "
                    "WHERE id = ? AND org_id = ? AND version = ?",
                    (opportunity["version"], opportunity["status"], opportunity["expires_at"],
                     json.dumps(opportunity, ensure_ascii=False, sort_keys=True), identity, tenant, expected_version),
                )
                if updated.rowcount != 1:
                    raise EditorialCalendarError("VERSION_CONFLICT", "opportunity changed while scheduling")
                self._connection.execute(
                    "INSERT INTO topic_editorial_plans (id, org_id, opportunity_id, version_no, status, payload) "
                    "VALUES (?, ?, ?, ?, 'active', ?)",
                    (plan["id"], tenant, identity, next_version, json.dumps(plan, ensure_ascii=False, sort_keys=True)),
                )
                event_type = "topic.editorial_plan.overridden" if override else "topic.editorial_plan.scheduled"
                self._audit(tenant=tenant, opportunity_id=identity, actor=actor, trace=trace, key=key,
                            event_type=event_type, plan=plan, input_version=expected_version,
                            output_version=opportunity["version"], reason=reason)
                response = {"plan": plan, "opportunity": opportunity}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except Exception:
                self._connection.rollback()
                raise

    def get(self, *, org_id: UUID | str, plan_id: UUID | str) -> dict[str, Any]:
        tenant, identity = _uuid(org_id, "org_id"), _uuid(plan_id, "plan_id")
        row = self._connection.execute(
            "SELECT payload FROM topic_editorial_plans WHERE org_id = ? AND id = ?", (tenant, identity)
        ).fetchone()
        if row is None:
            raise EditorialCalendarError("TENANT_SCOPE_VIOLATION", "editorial plan is not in this organization")
        return json.loads(row["payload"])

    def current(self, *, org_id: UUID | str, opportunity_id: UUID | str) -> dict[str, Any]:
        tenant, identity = _uuid(org_id, "org_id"), _uuid(opportunity_id, "opportunity_id")
        row = self._connection.execute(
            "SELECT payload FROM topic_editorial_plans WHERE org_id = ? AND opportunity_id = ? "
            "AND status = 'active' ORDER BY version_no DESC LIMIT 1", (tenant, identity)
        ).fetchone()
        if row is None:
            raise EditorialCalendarError("EDITORIAL_PLAN_NOT_FOUND", "no active editorial plan exists")
        return json.loads(row["payload"])

    def audit(self, *, org_id: UUID | str) -> tuple[dict[str, Any], ...]:
        tenant = _uuid(org_id, "org_id")
        rows = self._connection.execute(
            "SELECT envelope FROM topic_editorial_audit WHERE org_id = ? ORDER BY audit_seq", (tenant,)
        ).fetchall()
        return tuple(json.loads(row["envelope"]) for row in rows)


__all__ = ["EditorialCalendarError", "EditorialCalendarService"]
