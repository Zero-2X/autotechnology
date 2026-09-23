"""Credential-free pilot runs and local editorial schedules.

The web console needs a small amount of durable planning state even when no
platform API has been approved yet.  This store deliberately contains only
operator supplied metadata (account keys, dates, limits and content
references); it never stores cookies, passwords, tokens or platform session
data.  A pilot run can therefore be used to rehearse a cross-platform
workflow without causing an external side effect.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import RLock
from typing import Any, Mapping
from uuid import UUID, uuid4


LOCAL_ORG_ID = UUID("00000000-0000-4000-8000-000000000001")
_STATUSES = {"planned", "running", "completed", "stopped"}
_ITEM_STATUSES = {"planned", "ready", "published", "stopped"}
_TRANSITIONS = {
    "planned": {"running", "stopped"},
    "running": {"completed", "stopped"},
    "completed": set(),
    "stopped": set(),
}


class PilotRunError(ValueError):
    """Raised when a local pilot run is invalid or cannot be changed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _text(value: Any, field: str, *, required: bool = False, max_length: int = 240) -> str:
    if not isinstance(value, str):
        if required:
            raise PilotRunError("INVALID_PILOT_RUN", f"{field} must be text")
        return ""
    result = value.strip()
    if required and not result:
        raise PilotRunError("INVALID_PILOT_RUN", f"{field} is required")
    if len(result) > max_length:
        raise PilotRunError("INVALID_PILOT_RUN", f"{field} is too long")
    return result


def _timestamp(value: Any, field: str, *, required: bool = False) -> str | None:
    if value is None or value == "":
        if required:
            raise PilotRunError("INVALID_PILOT_RUN", f"{field} is required")
        return None
    if not isinstance(value, str):
        raise PilotRunError("INVALID_PILOT_RUN", f"{field} must be an ISO date-time")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise PilotRunError("INVALID_PILOT_RUN", f"{field} must be an ISO date-time") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _uuid_text(value: Any, field: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise PilotRunError("INVALID_PILOT_RUN", f"{field} must be a UUID") from exc


def _string_list(value: Any, field: str, *, max_items: int = 100, max_length: int = 240) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > max_items:
        raise PilotRunError("INVALID_PILOT_RUN", f"{field} must be a list")
    result: list[str] = []
    for item in value:
        text = _text(item, field, required=True, max_length=max_length)
        if text not in result:
            result.append(text)
    return result


def _limits(value: Any) -> dict[str, int]:
    raw = value if value is not None else {}
    if not isinstance(raw, Mapping):
        raise PilotRunError("INVALID_PILOT_LIMITS", "publish_limits must be an object")
    result: dict[str, int] = {}
    for field, default in (("daily_publish", 3), ("weekly_publish", 15)):
        number = raw.get(field, default)
        if type(number) is not int or number < 0 or number > 1000:
            raise PilotRunError("INVALID_PILOT_LIMITS", f"publish_limits.{field} must be 0-1000")
        result[field] = number
    if result["weekly_publish"] < result["daily_publish"]:
        raise PilotRunError("INVALID_PILOT_LIMITS", "weekly_publish cannot be smaller than daily_publish")
    return result


def _clean_item(value: Mapping[str, Any], *, existing_id: str | None = None) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PilotRunError("INVALID_PILOT_ITEM", "schedule item must be an object")
    item_id = existing_id or str(uuid4())
    if existing_id is None and value.get("id"):
        item_id = _uuid_text(value["id"], "items.id")
    else:
        item_id = _uuid_text(item_id, "items.id")
    scheduled = _timestamp(value.get("scheduled_at"), "items.scheduled_at", required=True)
    status = value.get("status", "planned")
    if status not in _ITEM_STATUSES:
        raise PilotRunError("INVALID_PILOT_ITEM", "items.status is invalid")
    return {
        "id": item_id,
        "content_id": _text(value.get("content_id", ""), "items.content_id", max_length=200),
        "title": _text(value.get("title"), "items.title", required=True, max_length=240),
        "account_key": _text(value.get("account_key"), "items.account_key", required=True, max_length=200),
        "scheduled_at": scheduled,
        "status": status,
        "notes": _text(value.get("notes", ""), "items.notes", max_length=1000),
        "updated_at": _timestamp(value.get("updated_at"), "items.updated_at") or datetime.now(timezone.utc).isoformat(),
    }


def _contract(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact pilot-run contract without local planning metadata."""

    return {
        "id": record["id"],
        "org_id": record["org_id"],
        "name": record["name"],
        "account_ids": list(record.get("account_ids", [])),
        "start_at": record["start_at"],
        "end_at": record.get("end_at"),
        "status": record["status"],
        "created_at": record["created_at"],
    }


class PilotRunStore:
    """Atomic JSON persistence for local pilot plans."""

    def __init__(self, path: str | Path, *, org_id: UUID | str = LOCAL_ORG_ID) -> None:
        self.path = Path(path)
        self.org_id = _uuid_text(org_id, "org_id")
        self._lock = RLock()
        self._records: dict[str, dict[str, Any]] | None = None

    def _load(self) -> dict[str, dict[str, Any]]:
        if self._records is not None:
            return self._records
        if not self.path.exists():
            self._records = {}
            return self._records
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PilotRunError("PILOT_RUN_READ_FAILED", str(exc)) from exc
        raw = payload.get("runs", []) if isinstance(payload, Mapping) else []
        if not isinstance(raw, list):
            raise PilotRunError("PILOT_RUN_READ_FAILED", "runs must be a list")
        records: dict[str, dict[str, Any]] = {}
        for record in raw:
            if isinstance(record, Mapping) and isinstance(record.get("id"), str):
                records[record["id"]] = deepcopy(dict(record))
        self._records = records
        return records

    def _save(self) -> None:
        assert self._records is not None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temporary.write_text(
                json.dumps({"schema_version": 1, "runs": list(self._records.values())}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(self.path)
        except OSError as exc:
            raise PilotRunError("PILOT_RUN_WRITE_FAILED", str(exc)) from exc

    def list(self, *, status: str | None = None, account_key: str | None = None) -> list[dict[str, Any]]:
        if status is not None and status not in _STATUSES:
            raise PilotRunError("INVALID_PILOT_STATUS", "status is invalid")
        with self._lock:
            records = self._load()
            result = []
            for record in records.values():
                if status and record.get("status") != status:
                    continue
                if account_key and account_key not in record.get("account_keys", []):
                    continue
                result.append(deepcopy(record))
            return sorted(result, key=lambda item: (item.get("start_at", ""), item.get("created_at", "")))

    def get(self, run_id: str | UUID) -> dict[str, Any]:
        identity = _uuid_text(run_id, "run_id")
        with self._lock:
            record = self._load().get(identity)
            if record is None:
                raise PilotRunError("PILOT_RUN_NOT_FOUND", "pilot run is not available")
            return deepcopy(record)

    def create(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise PilotRunError("INVALID_PILOT_RUN", "pilot run must be an object")
        name = _text(payload.get("name"), "name", required=True, max_length=160)
        start_at = _timestamp(payload.get("start_at"), "start_at", required=True)
        end_at = _timestamp(payload.get("end_at"), "end_at")
        if end_at and start_at and datetime.fromisoformat(end_at) < datetime.fromisoformat(start_at):
            raise PilotRunError("INVALID_PILOT_RUN", "end_at must not be before start_at")
        raw_ids = payload.get("account_ids", [])
        if not isinstance(raw_ids, list) or len(raw_ids) > 100:
            raise PilotRunError("INVALID_PILOT_RUN", "account_ids must be a list")
        account_ids = [_uuid_text(item, "account_ids") for item in raw_ids]
        account_keys = _string_list(payload.get("account_keys", []), "account_keys", max_length=200)
        owner = _text(payload.get("owner"), "owner", required=True, max_length=120)
        backup = _text(payload.get("backup"), "backup", required=True, max_length=120)
        stop_conditions = _string_list(payload.get("stop_conditions", []), "stop_conditions", max_items=30, max_length=500)
        if not stop_conditions:
            raise PilotRunError("INVALID_PILOT_RUN", "at least one stop condition is required")
        items_raw = payload.get("items", [])
        if not isinstance(items_raw, list) or len(items_raw) > 500:
            raise PilotRunError("INVALID_PILOT_RUN", "items must be a list")
        items = [_clean_item(item) for item in items_raw]
        if account_keys and any(item["account_key"] not in account_keys for item in items):
            raise PilotRunError("ACCOUNT_NOT_IN_PILOT", "item account is not assigned to this pilot")
        duplicate_ids = {item["id"] for item in items if [x["id"] for x in items].count(item["id"]) > 1}
        if duplicate_ids:
            raise PilotRunError("INVALID_PILOT_ITEM", "item ids must be unique")
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "id": str(uuid4()), "org_id": self.org_id, "name": name,
            "account_ids": account_ids, "account_keys": account_keys,
            "start_at": start_at, "end_at": end_at, "status": "planned", "created_at": now,
            "updated_at": now, "owner": owner, "backup": backup,
            "publish_limits": _limits(payload.get("publish_limits")),
            "stop_conditions": stop_conditions, "stop_reason": "", "items": items,
            "review_log": [], "metrics": {},
        }
        with self._lock:
            records = self._load()
            records[record["id"]] = record
            self._save()
            return deepcopy(record)

    def update(self, run_id: str | UUID, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise PilotRunError("INVALID_PILOT_RUN", "pilot payload must be an object")
        with self._lock:
            current = self.get(run_id)
            if current["status"] in {"completed", "stopped"}:
                raise PilotRunError("PILOT_RUN_TERMINAL", "completed or stopped pilot runs cannot be edited")
            merged = {**current, **dict(payload)}
            # Keep the generated identity and tenant immutable.
            merged["id"], merged["org_id"], merged["status"], merged["created_at"] = current["id"], current["org_id"], current["status"], current["created_at"]
            replacement = self.create_validation(merged)
            replacement["id"] = current["id"]
            replacement["created_at"] = current["created_at"]
            replacement["status"] = current["status"]
            replacement["updated_at"] = datetime.now(timezone.utc).isoformat()
            replacement["review_log"] = deepcopy(current.get("review_log", []))
            replacement["metrics"] = deepcopy(current.get("metrics", {}))
            self._load()[current["id"]] = replacement
            self._save()
            return deepcopy(replacement)

    def create_validation(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Validate a record-shaped payload without creating a new record."""
        name = _text(payload.get("name"), "name", required=True, max_length=160)
        start_at = _timestamp(payload.get("start_at"), "start_at", required=True)
        end_at = _timestamp(payload.get("end_at"), "end_at")
        if end_at and start_at and datetime.fromisoformat(end_at) < datetime.fromisoformat(start_at):
            raise PilotRunError("INVALID_PILOT_RUN", "end_at must not be before start_at")
        raw_ids = payload.get("account_ids", [])
        if not isinstance(raw_ids, list) or len(raw_ids) > 100:
            raise PilotRunError("INVALID_PILOT_RUN", "account_ids must be a list")
        account_ids = [_uuid_text(item, "account_ids") for item in raw_ids]
        account_keys = _string_list(payload.get("account_keys", []), "account_keys", max_length=200)
        owner = _text(payload.get("owner"), "owner", required=True, max_length=120)
        backup = _text(payload.get("backup"), "backup", required=True, max_length=120)
        stop_conditions = _string_list(payload.get("stop_conditions", []), "stop_conditions", max_items=30, max_length=500)
        if not stop_conditions:
            raise PilotRunError("INVALID_PILOT_RUN", "at least one stop condition is required")
        raw_items = payload.get("items", [])
        if not isinstance(raw_items, list) or len(raw_items) > 500:
            raise PilotRunError("INVALID_PILOT_RUN", "items must be a list")
        items = [_clean_item(item) for item in raw_items]
        if account_keys and any(item["account_key"] not in account_keys for item in items):
            raise PilotRunError("ACCOUNT_NOT_IN_PILOT", "item account is not assigned to this pilot")
        identity = _uuid_text(payload.get("id", uuid4()), "id")
        org_id = _uuid_text(payload.get("org_id", self.org_id), "org_id")
        if org_id != self.org_id:
            raise PilotRunError("TENANT_SCOPE_VIOLATION", "pilot run belongs to another local organization")
        status = payload.get("status", "planned")
        if status not in _STATUSES:
            raise PilotRunError("INVALID_PILOT_STATUS", "status is invalid")
        return {
            "id": identity, "org_id": org_id, "name": name, "account_ids": account_ids, "account_keys": account_keys,
            "start_at": start_at, "end_at": end_at, "status": status,
            "created_at": _timestamp(payload.get("created_at"), "created_at") or datetime.now(timezone.utc).isoformat(),
            "updated_at": _timestamp(payload.get("updated_at"), "updated_at") or datetime.now(timezone.utc).isoformat(),
            "owner": owner, "backup": backup, "publish_limits": _limits(payload.get("publish_limits")),
            "stop_conditions": stop_conditions, "stop_reason": _text(payload.get("stop_reason", ""), "stop_reason", max_length=500),
            "items": items, "review_log": deepcopy(payload.get("review_log", [])) if isinstance(payload.get("review_log", []), list) else [],
            "metrics": deepcopy(payload.get("metrics", {})) if isinstance(payload.get("metrics", {}), Mapping) else {},
        }

    def transition(self, run_id: str | UUID, status: str, *, reason: str = "") -> dict[str, Any]:
        if status not in _STATUSES:
            raise PilotRunError("INVALID_PILOT_STATUS", "status is invalid")
        with self._lock:
            current = self.get(run_id)
            if status not in _TRANSITIONS[current["status"]]:
                raise PilotRunError("INVALID_PILOT_TRANSITION", f"cannot move {current['status']} to {status}")
            if status == "stopped" and (not isinstance(reason, str) or not reason.strip()):
                raise PilotRunError("STOP_REASON_REQUIRED", "stopping a pilot requires a reason")
            current["status"] = status
            current["updated_at"] = datetime.now(timezone.utc).isoformat()
            if status == "stopped":
                current["stop_reason"] = _text(reason, "reason", required=True, max_length=500)
            self._load()[current["id"]] = current
            self._save()
            return deepcopy(current)

    def add_item(self, run_id: str | UUID, payload: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            current = self.get(run_id)
            if current["status"] not in {"planned", "running"}:
                raise PilotRunError("PILOT_RUN_TERMINAL", "items cannot be added to a finished pilot")
            item = _clean_item(payload)
            if current.get("account_keys") and item["account_key"] not in current["account_keys"]:
                raise PilotRunError("ACCOUNT_NOT_IN_PILOT", "item account is not assigned to this pilot")
            if any(existing["id"] == item["id"] for existing in current.get("items", [])):
                raise PilotRunError("DUPLICATE_PILOT_ITEM", "item id already exists")
            current.setdefault("items", []).append(item)
            current["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._load()[current["id"]] = current
            self._save()
            return deepcopy(current)

    def review(self, run_id: str | UUID, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise PilotRunError("INVALID_REVIEW", "review must be an object")
        note = _text(payload.get("note"), "note", required=True, max_length=2000)
        metrics = payload.get("metrics", {})
        if not isinstance(metrics, Mapping):
            raise PilotRunError("INVALID_REVIEW", "metrics must be an object")
        with self._lock:
            current = self.get(run_id)
            entry = {"id": str(uuid4()), "note": note, "metrics": deepcopy(dict(metrics)), "created_at": datetime.now(timezone.utc).isoformat()}
            current.setdefault("review_log", []).append(entry)
            current["metrics"] = deepcopy(dict(metrics))
            current["updated_at"] = entry["created_at"]
            self._load()[current["id"]] = current
            self._save()
            return deepcopy(current)

    def summary(self, run_id: str | UUID) -> dict[str, Any]:
        record = self.get(run_id)
        items = record.get("items", [])
        counts = {status: sum(1 for item in items if item.get("status") == status) for status in _ITEM_STATUSES}
        return {
            "id": record["id"], "name": record["name"], "status": record["status"],
            "owner": record["owner"], "backup": record["backup"], "start_at": record["start_at"], "end_at": record["end_at"],
            "account_keys": list(record.get("account_keys", [])), "publish_limits": deepcopy(record["publish_limits"]),
            "stop_conditions": list(record.get("stop_conditions", [])), "item_counts": counts,
            "total_items": len(items), "review_count": len(record.get("review_log", [])),
            "updated_at": record.get("updated_at"), "contract": _contract(record),
        }


__all__ = ["LOCAL_ORG_ID", "PilotRunError", "PilotRunStore"]
