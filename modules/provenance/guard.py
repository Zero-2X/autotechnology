"""Rights enforcement, expiry reminders, and derived-content lineage."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any, Iterable, Mapping
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5

from .infrastructure.rights_guard_schema import initialize as initialize_guard
from .infrastructure.rights_schema import initialize as initialize_rights
from .infrastructure.source_schema import initialize as initialize_sources
from .rights import RightsError, RightsService
from .source import SourceError, _hash, _text as _source_text, _uuid as _source_uuid, _utc as _source_utc


class RightsGuardError(ValueError):
    """Stable error code for authorization, reminder, and lineage operations."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _uuid(value: UUID | str, name: str) -> str:
    try:
        return _source_uuid(value, name)
    except SourceError as exc:
        raise RightsGuardError("INVALID_GUARD_COMMAND", str(exc)) from exc


def _text(value: object, name: str, limit: int = 2048) -> str:
    try:
        return _source_text(value, name, limit)
    except SourceError as exc:
        raise RightsGuardError("INVALID_GUARD_COMMAND", str(exc)) from exc


def _utc(value: str | None, name: str, *, default_now: bool = True) -> str:
    try:
        return _source_utc(value, name, default_now=default_now)
    except SourceError as exc:
        raise RightsGuardError("INVALID_GUARD_TIMESTAMP", str(exc)) from exc


def _optional_uuid(value: UUID | str | None, name: str) -> str | None:
    return None if value is None else _uuid(value, name)


class RightsGuardService:
    """Enforce rights before use and retain a traversable derivative lineage."""

    def __init__(self, database: str | Path = ":memory:", *, connection: sqlite3.Connection | None = None,
                 rights_service: RightsService | None = None) -> None:
        self._owns_connection = connection is None and rights_service is None
        if rights_service is not None:
            self._connection = rights_service._connection
            self._rights = rights_service
        else:
            self._connection = connection or sqlite3.connect(str(database), timeout=30, check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys=ON")
            initialize_sources(self._connection)
            initialize_rights(self._connection)
            self._rights = RightsService(connection=self._connection)
        initialize_guard(self._connection)
        self._lock = RLock()

    def close(self) -> None:
        if self._owns_connection:
            self._connection.close()

    def _prior(self, tenant: str, key: str, digest: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT payload_hash, response FROM rights_guard_commands WHERE org_id = ? AND idempotency_key = ?",
            (tenant, key),
        ).fetchone()
        if row is None:
            return None
        if row["payload_hash"] != digest:
            raise RightsGuardError("IDEMPOTENCY_KEY_REUSED", "command payload differs from prior request")
        return json.loads(row["response"])

    def _save_command(self, tenant: str, key: str, digest: str, actor: str, trace: str,
                      response: dict[str, Any]) -> None:
        self._connection.execute(
            "INSERT INTO rights_guard_commands (org_id, idempotency_key, payload_hash, actor_id, trace_id, response) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tenant, key, digest, actor, trace, json.dumps(response, ensure_ascii=False, sort_keys=True)),
        )

    def _version(self, tenant: str, version_id: str) -> tuple[sqlite3.Row, dict[str, Any]]:
        row = self._connection.execute(
            "SELECT * FROM rights_record_versions WHERE org_id = ? AND id = ?", (tenant, version_id)
        ).fetchone()
        if row is None:
            raise RightsGuardError("TENANT_SCOPE_VIOLATION", "rights version is not in this organization")
        return row, json.loads(row["payload"])

    @staticmethod
    def _reason_codes(version: Mapping[str, Any], *, region: str | None, locale: str | None,
                      media: str | None, use: str | None, at: datetime) -> list[str]:
        reasons: list[str] = []
        if version.get("status") != "verified":
            reasons.append(f"RIGHTS_STATUS_{str(version.get('status', 'unknown')).upper()}")
        start = version.get("valid_from")
        end = version.get("valid_to")
        if start and at < datetime.fromisoformat(start.replace("Z", "+00:00")):
            reasons.append("RIGHTS_NOT_YET_VALID")
        if end and at >= datetime.fromisoformat(end.replace("Z", "+00:00")):
            reasons.append("RIGHTS_EXPIRED")
        if region is None or region not in version.get("permitted_regions", []):
            reasons.append("REGION_NOT_PERMITTED")
        if locale is None or locale not in version.get("permitted_locales", []):
            reasons.append("LOCALE_NOT_PERMITTED")
        if media is None or media not in version.get("permitted_media", []):
            reasons.append("MEDIA_NOT_PERMITTED")
        levels = {"research": 0, "derivative": 1, "commercial": 2}
        permitted = version.get("permitted_use")
        if use not in levels or permitted not in levels or levels[use] > levels[permitted]:
            reasons.append("USE_NOT_PERMITTED")
        return reasons

    def check_authorization(
        self, *, org_id: UUID | str, rights_record_version_id: UUID | str, actor_id: UUID | str,
        trace_id: str, idempotency_key: str, region: str | None, locale: str | None,
        media: str | None, use: str | None, as_of: str | None = None,
    ) -> dict[str, Any]:
        tenant, version_id, actor = _uuid(org_id, "org_id"), _uuid(rights_record_version_id, "rights_record_version_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id", 256), _text(idempotency_key, "idempotency_key", 200)
        region = None if region is None else _text(region, "region", 128)
        locale = None if locale is None else _text(locale, "locale", 128)
        media = None if media is None else _text(media, "media", 128)
        use = None if use is None else _text(use, "use", 64)
        at_input = None if as_of is None else _utc(as_of, "as_of", default_now=False)
        digest = _hash({"operation": "check_authorization", "rights_record_version_id": version_id,
                        "region": region, "locale": locale, "media": media, "use": use, "as_of": at_input})
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                _, version = self._version(tenant, version_id)
                checked_at = at_input or _utc(None, "checked_at")
                at = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
                reasons = self._reason_codes(version, region=region, locale=locale, media=media, use=use, at=at)
                decision = "allowed" if not reasons else "blocked"
                decision_id = str(uuid4())
                requested_scope = {"region": region, "locale": locale, "media": media, "use": use}
                envelope = {
                    "decision_id": decision_id,
                    "org_id": tenant,
                    "rights_record_version_id": version_id,
                    "decision": decision,
                    "allowed": decision == "allowed",
                    "reason_codes": reasons,
                    "requested_scope": requested_scope,
                    "checked_at": checked_at,
                    "snapshot_hash": version["snapshot_hash"],
                    "actor_id": actor,
                    "trace_id": trace,
                }
                self._connection.execute(
                    "INSERT INTO rights_guard_decisions "
                    "(decision_id, org_id, rights_record_version_id, decision, reason_codes, requested_scope, checked_at, envelope) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (decision_id, tenant, version_id, decision, json.dumps(reasons), json.dumps(requested_scope, sort_keys=True),
                     checked_at, json.dumps(envelope, ensure_ascii=False, sort_keys=True)),
                )
                response = {"decision": decision, "allowed": decision == "allowed", "reason_codes": reasons,
                            "decision_id": decision_id, "rights_record_version_id": version_id,
                            "snapshot_hash": version["snapshot_hash"], "checked_at": checked_at,
                            "requested_scope": requested_scope}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except sqlite3.IntegrityError as exc:
                self._connection.rollback()
                raise RightsGuardError("GUARD_CONFLICT", "authorization decision conflicts with an existing record") from exc
            except Exception:
                self._connection.rollback()
                raise

    authorize = check_authorization
    check = check_authorization

    def schedule_expiry_reminders(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        horizon_seconds: int = 7 * 24 * 60 * 60, lead_seconds: int = 24 * 60 * 60,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id", 256), _text(idempotency_key, "idempotency_key", 200)
        if type(horizon_seconds) is not int or horizon_seconds < 0 or horizon_seconds > 366 * 24 * 60 * 60:
            raise RightsGuardError("INVALID_EXPIRY_WINDOW", "horizon_seconds is invalid")
        if type(lead_seconds) is not int or lead_seconds < 0 or lead_seconds > horizon_seconds:
            raise RightsGuardError("INVALID_EXPIRY_WINDOW", "lead_seconds is invalid")
        as_of_value = None if as_of is None else _utc(as_of, "as_of", default_now=False)
        digest = _hash({"operation": "schedule_expiry_reminders", "horizon_seconds": horizon_seconds,
                        "lead_seconds": lead_seconds, "as_of": as_of_value})
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                now = datetime.fromisoformat((as_of_value or _utc(None, "now")).replace("Z", "+00:00"))
                horizon = now + timedelta(seconds=horizon_seconds)
                rows = self._connection.execute(
                    "SELECT id, valid_to, payload FROM rights_record_versions "
                    "WHERE org_id = ? AND status = 'verified' AND valid_to IS NOT NULL "
                    "AND valid_to <= ? ORDER BY valid_to, id",
                    (tenant, horizon.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")),
                ).fetchall()
                reminders: list[dict[str, Any]] = []
                for row in rows:
                    valid_to = row["valid_to"]
                    due = datetime.fromisoformat(valid_to.replace("Z", "+00:00")) - timedelta(seconds=lead_seconds)
                    remind_at = due.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
                    reminder_id = str(uuid5(NAMESPACE_URL, f"rights-reminder:{tenant}:{row['id']}:{remind_at}"))
                    payload = {"reminder_id": reminder_id, "org_id": tenant,
                               "rights_record_version_id": row["id"], "valid_to": valid_to,
                               "remind_at": remind_at, "status": "scheduled", "actor_id": actor, "trace_id": trace}
                    self._connection.execute(
                        "INSERT OR IGNORE INTO rights_expiry_reminders "
                        "(reminder_id, org_id, rights_record_version_id, valid_to, remind_at, status, idempotency_key, payload) "
                        "VALUES (?, ?, ?, ?, ?, 'scheduled', ?, ?)",
                        (reminder_id, tenant, row["id"], valid_to, remind_at, key, json.dumps(payload, sort_keys=True)),
                    )
                    reminders.append(payload)
                response = {"reminders": reminders, "checked_at": now.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
                            "horizon_seconds": horizon_seconds, "lead_seconds": lead_seconds}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except Exception:
                self._connection.rollback()
                raise

    scan_expiry = schedule_expiry_reminders
    find_expiring = schedule_expiry_reminders

    def register_lineage(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        rights_record_version_id: UUID | str, derived_type: str, derived_id: UUID | str,
        relation: str = "derived_from", parent_derived_type: str | None = None,
        parent_derived_id: UUID | str | None = None, metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        tenant, actor, version_id, derived_identity = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id"), _uuid(rights_record_version_id, "rights_record_version_id"), _uuid(derived_id, "derived_id")
        trace, key = _text(trace_id, "trace_id", 256), _text(idempotency_key, "idempotency_key", 200)
        kind, rel = _text(derived_type, "derived_type", 128), _text(relation, "relation", 128)
        parent_kind = None if parent_derived_type is None else _text(parent_derived_type, "parent_derived_type", 128)
        parent_id = _optional_uuid(parent_derived_id, "parent_derived_id")
        if (parent_kind is None) != (parent_id is None):
            raise RightsGuardError("INVALID_LINEAGE", "parent derived type and id must be supplied together")
        metadata_value = dict(metadata or {})
        try:
            json.dumps(metadata_value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise RightsGuardError("INVALID_LINEAGE", "metadata must be finite JSON") from exc
        digest = _hash({"operation": "register_lineage", "rights_record_version_id": version_id,
                        "derived_type": kind, "derived_id": derived_identity, "relation": rel,
                        "parent_derived_type": parent_kind, "parent_derived_id": parent_id, "metadata": metadata_value})
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                _, version = self._version(tenant, version_id)
                if version["status"] != "verified":
                    raise RightsGuardError("RIGHTS_NOT_USABLE", "only verified rights versions can create lineage")
                if parent_id is not None and self._connection.execute(
                    "SELECT 1 FROM rights_lineage_edges WHERE org_id = ? AND derived_type = ? AND derived_id = ?",
                    (tenant, parent_kind, parent_id),
                ).fetchone() is None:
                    raise RightsGuardError("LINEAGE_PARENT_NOT_FOUND", "parent derived object is not registered")
                edge_id = str(uuid4())
                created_at = _utc(None, "created_at")
                payload = {"edge_id": edge_id, "org_id": tenant, "rights_record_version_id": version_id,
                           "parent_derived_type": parent_kind, "parent_derived_id": parent_id,
                           "derived_type": kind, "derived_id": derived_identity, "relation": rel,
                           "created_by": actor, "created_at": created_at, "metadata": metadata_value,
                           "snapshot_hash": version["snapshot_hash"]}
                self._connection.execute(
                    "INSERT INTO rights_lineage_edges "
                    "(edge_id, org_id, rights_record_version_id, parent_derived_type, parent_derived_id, derived_type, derived_id, relation, created_by, created_at, payload) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (edge_id, tenant, version_id, parent_kind, parent_id, kind, derived_identity, rel, actor, created_at,
                     json.dumps(payload, ensure_ascii=False, sort_keys=True)),
                )
                response = {"edge": payload}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except sqlite3.IntegrityError as exc:
                self._connection.rollback()
                raise RightsGuardError("LINEAGE_CONFLICT", "derived object lineage already exists") from exc
            except Exception:
                self._connection.rollback()
                raise

    register_derivative = register_lineage
    register_derived = register_lineage

    def trace_lineage(self, *, org_id: UUID | str, rights_record_version_id: UUID | str) -> tuple[dict[str, Any], ...]:
        tenant, version_id = _uuid(org_id, "org_id"), _uuid(rights_record_version_id, "rights_record_version_id")
        self._version(tenant, version_id)
        rows = self._connection.execute(
            "SELECT payload FROM rights_lineage_edges WHERE org_id = ? AND rights_record_version_id = ? ORDER BY created_at, edge_id",
            (tenant, version_id),
        ).fetchall()
        edges = [json.loads(row["payload"]) for row in rows]
        seen = {(edge["derived_type"], edge["derived_id"]) for edge in edges}
        queue = list(seen)
        while queue:
            parent = queue.pop(0)
            children = self._connection.execute(
                "SELECT payload FROM rights_lineage_edges WHERE org_id = ? AND parent_derived_type = ? AND parent_derived_id = ? ORDER BY created_at, edge_id",
                (tenant, parent[0], parent[1]),
            ).fetchall()
            for row in children:
                edge = json.loads(row["payload"])
                identity = (edge["derived_type"], edge["derived_id"])
                if identity not in seen:
                    seen.add(identity)
                    edges.append(edge)
                    queue.append(identity)
        return tuple(edges)

    trace_derivatives = trace_lineage
    find_derivatives = trace_lineage

    def block_derivatives(
        self, *, org_id: UUID | str, rights_record_version_id: UUID | str, actor_id: UUID | str,
        trace_id: str, idempotency_key: str, reason: str, source_event_id: UUID | str | None = None,
    ) -> dict[str, Any]:
        tenant, actor, version_id = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id"), _uuid(rights_record_version_id, "rights_record_version_id")
        trace, key, normalized_reason = _text(trace_id, "trace_id", 256), _text(idempotency_key, "idempotency_key", 200), _text(reason, "reason", 2048)
        source_event = _optional_uuid(source_event_id, "source_event_id")
        digest = _hash({"operation": "block_derivatives", "rights_record_version_id": version_id,
                        "reason": normalized_reason, "source_event_id": source_event})
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                self._version(tenant, version_id)
                edges = self.trace_lineage(org_id=tenant, rights_record_version_id=version_id)
                blocks: list[dict[str, Any]] = []
                for edge in edges:
                    block_id = str(uuid5(NAMESPACE_URL, f"rights-block:{tenant}:{edge['edge_id']}:{normalized_reason}"))
                    blocked_at = _utc(None, "blocked_at")
                    payload = {"block_id": block_id, "org_id": tenant, "edge_id": edge["edge_id"],
                               "rights_record_version_id": version_id, "reason": normalized_reason,
                               "source_event_id": source_event, "blocked_at": blocked_at,
                               "derived_type": edge["derived_type"], "derived_id": edge["derived_id"],
                               "actor_id": actor, "trace_id": trace}
                    self._connection.execute(
                        "INSERT OR IGNORE INTO rights_derivative_blocks "
                        "(block_id, org_id, edge_id, rights_record_version_id, reason, source_event_id, blocked_at, payload) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (block_id, tenant, edge["edge_id"], version_id, normalized_reason, source_event, blocked_at,
                         json.dumps(payload, ensure_ascii=False, sort_keys=True)),
                    )
                    blocks.append(payload)
                response = {"rights_record_version_id": version_id, "reason": normalized_reason, "blocks": blocks}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except Exception:
                self._connection.rollback()
                raise

    def freeze_complaint(
        self, *, org_id: UUID | str, rights_record_id: UUID | str, version_id: UUID | str,
        actor_id: UUID | str, trace_id: str, idempotency_key: str, expected_version: int, reason: str,
    ) -> dict[str, Any]:
        transition = self._rights.transition_version(
            org_id=org_id, rights_record_id=rights_record_id, version_id=version_id,
            actor_id=actor_id, trace_id=trace_id, idempotency_key=idempotency_key,
            action="hold_complaint", expected_version=expected_version, reason=reason,
        )
        blocks = self.block_derivatives(
            org_id=org_id, rights_record_version_id=version_id, actor_id=actor_id, trace_id=trace_id,
            idempotency_key=f"{idempotency_key}:blocks", reason=reason,
            source_event_id=transition["event"]["event_id"],
        )
        return {**transition, "blocks": blocks["blocks"]}

    complaint_hold = freeze_complaint

    def expire_due(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id", 256), _text(idempotency_key, "idempotency_key", 200)
        as_of_value = None if as_of is None else _utc(as_of, "as_of", default_now=False)
        digest = _hash({"operation": "expire_due", "as_of": as_of_value})
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                now = datetime.fromisoformat((as_of_value or _utc(None, "now")).replace("Z", "+00:00"))
                cutoff = now.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
                rows = self._connection.execute(
                    "SELECT id, rights_record_id, version_no, valid_to FROM rights_record_versions "
                    "WHERE org_id = ? AND status = 'verified' AND valid_to IS NOT NULL AND valid_to <= ? ORDER BY id",
                    (tenant, cutoff),
                ).fetchall()
                expired: list[dict[str, Any]] = []
                # Release the local transaction before invoking the rights
                # aggregate service, which owns its own optimistic update.
                self._connection.commit()
                for row in rows:
                    try:
                        result = self._rights.transition_version(
                            org_id=tenant, rights_record_id=row["rights_record_id"], version_id=row["id"],
                            actor_id=actor, trace_id=trace, idempotency_key=f"{key}:{row['id']}",
                            action="expire", expected_version=row["version_no"], reason="validity period ended",
                        )
                        expired.append(result["version"])
                    except RightsError as exc:
                        if exc.code not in {"INVALID_RIGHTS_STATE", "VERSION_CONFLICT"}:
                            raise
                response = {"expired": expired, "checked_at": cutoff}
                self._connection.execute("BEGIN IMMEDIATE")
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except Exception:
                self._connection.rollback()
                raise

    expire_expired = expire_due

    def reminders(self, *, org_id: UUID | str, version_id: UUID | str | None = None) -> tuple[dict[str, Any], ...]:
        tenant = _uuid(org_id, "org_id")
        if version_id is None:
            rows = self._connection.execute(
                "SELECT payload FROM rights_expiry_reminders WHERE org_id = ? ORDER BY remind_at, reminder_id", (tenant,)
            ).fetchall()
        else:
            identity = _uuid(version_id, "version_id")
            rows = self._connection.execute(
                "SELECT payload FROM rights_expiry_reminders WHERE org_id = ? AND rights_record_version_id = ? ORDER BY remind_at, reminder_id",
                (tenant, identity),
            ).fetchall()
        return tuple(json.loads(row["payload"]) for row in rows)

    def blocked_derivatives(self, *, org_id: UUID | str, rights_record_version_id: UUID | str) -> tuple[dict[str, Any], ...]:
        tenant, version_id = _uuid(org_id, "org_id"), _uuid(rights_record_version_id, "rights_record_version_id")
        rows = self._connection.execute(
            "SELECT payload FROM rights_derivative_blocks WHERE org_id = ? AND rights_record_version_id = ? ORDER BY blocked_at, block_id",
            (tenant, version_id),
        ).fetchall()
        return tuple(json.loads(row["payload"]) for row in rows)


RightsEnforcementService = RightsGuardService

__all__ = ["RightsGuardError", "RightsGuardService", "RightsEnforcementService"]
