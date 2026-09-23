"""Credential-free publishing safety policy for the local operations console.

The policy is deliberately small and provider agnostic.  It does not attempt
to predict a platform's anti-abuse system and it never stores cookies, tokens,
or passwords.  It only provides an operator-controlled stop switch, account
enablement, and conservative daily/weekly publish limits before a side-effect
workflow is opened.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from threading import RLock
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class OperationsPolicyError(ValueError):
    """Raised when a local operations policy is malformed or cannot be saved."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def default_policy() -> dict[str, Any]:
    """Return a fresh fail-safe policy with conservative limits."""

    return {
        "schema_version": 1,
        "emergency_stop": False,
        "emergency_stop_reason": "",
        "timezone": "Asia/Shanghai",
        "default_limits": {"daily_publish": 3, "weekly_publish": 15},
        "accounts": {},
        "updated_at": None,
    }


def _int_limit(value: Any, field: str) -> int:
    if type(value) is not int or value < 0 or value > 1000:
        raise OperationsPolicyError("INVALID_POLICY_LIMIT", f"{field} must be an integer between 0 and 1000")
    return value


def _clean_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise OperationsPolicyError("INVALID_POLICY", "policy must be an object")
    base = default_policy()
    if "schema_version" in value and value["schema_version"] != 1:
        raise OperationsPolicyError("UNSUPPORTED_POLICY_VERSION", "only policy schema version 1 is supported")
    stop = value.get("emergency_stop", base["emergency_stop"])
    if type(stop) is not bool:
        raise OperationsPolicyError("INVALID_POLICY", "emergency_stop must be a boolean")
    reason = value.get("emergency_stop_reason", "")
    if not isinstance(reason, str) or len(reason) > 512:
        raise OperationsPolicyError("INVALID_POLICY", "emergency_stop_reason must be text up to 512 characters")
    timezone_name = value.get("timezone", base["timezone"])
    if not isinstance(timezone_name, str) or not timezone_name.strip() or len(timezone_name) > 80:
        raise OperationsPolicyError("INVALID_POLICY", "timezone must be non-empty text")
    try:
        ZoneInfo(timezone_name.strip())
    except ZoneInfoNotFoundError as exc:
        raise OperationsPolicyError("INVALID_POLICY", "timezone must be a valid IANA timezone") from exc
    raw_limits = value.get("default_limits", {})
    if not isinstance(raw_limits, Mapping):
        raise OperationsPolicyError("INVALID_POLICY", "default_limits must be an object")
    limits = {
        "daily_publish": _int_limit(raw_limits.get("daily_publish", 3), "default_limits.daily_publish"),
        "weekly_publish": _int_limit(raw_limits.get("weekly_publish", 15), "default_limits.weekly_publish"),
    }
    if limits["weekly_publish"] < limits["daily_publish"]:
        raise OperationsPolicyError("INVALID_POLICY_LIMIT", "weekly_publish cannot be smaller than daily_publish")

    raw_accounts = value.get("accounts", {})
    if not isinstance(raw_accounts, Mapping):
        raise OperationsPolicyError("INVALID_POLICY", "accounts must be an object")
    accounts: dict[str, dict[str, Any]] = {}
    for account_key, raw in raw_accounts.items():
        if not isinstance(account_key, str) or not account_key.strip() or len(account_key) > 200:
            raise OperationsPolicyError("INVALID_ACCOUNT_POLICY", "account keys must be non-empty text")
        if not isinstance(raw, Mapping):
            raise OperationsPolicyError("INVALID_ACCOUNT_POLICY", f"policy for {account_key} must be an object")
        enabled = raw.get("enabled", True)
        if type(enabled) is not bool:
            raise OperationsPolicyError("INVALID_ACCOUNT_POLICY", f"enabled for {account_key} must be a boolean")
        account_limits = raw.get("limits", {})
        if not isinstance(account_limits, Mapping):
            raise OperationsPolicyError("INVALID_ACCOUNT_POLICY", f"limits for {account_key} must be an object")
        daily = _int_limit(account_limits.get("daily_publish", limits["daily_publish"]), f"accounts.{account_key}.limits.daily_publish")
        weekly = _int_limit(account_limits.get("weekly_publish", limits["weekly_publish"]), f"accounts.{account_key}.limits.weekly_publish")
        if weekly < daily:
            raise OperationsPolicyError("INVALID_POLICY_LIMIT", f"weekly_publish for {account_key} cannot be smaller than daily_publish")
        owner = raw.get("owner", "")
        backup = raw.get("backup", "")
        if not isinstance(owner, str) or not isinstance(backup, str) or len(owner) > 120 or len(backup) > 120:
            raise OperationsPolicyError("INVALID_ACCOUNT_POLICY", f"owner and backup for {account_key} must be short text")
        accounts[account_key.strip()] = {
            "enabled": enabled,
            "owner": owner.strip(),
            "backup": backup.strip(),
            "limits": {"daily_publish": daily, "weekly_publish": weekly},
        }
    result = {
        "schema_version": 1,
        "emergency_stop": stop,
        "emergency_stop_reason": reason.strip(),
        "timezone": timezone_name.strip(),
        "default_limits": limits,
        "accounts": accounts,
        "updated_at": value.get("updated_at"),
    }
    return result


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        stamp = value.strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class OperationsPolicyStore:
    """Persist and evaluate the local policy without external dependencies."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = RLock()
        self._policy: dict[str, Any] | None = None

    def get(self) -> dict[str, Any]:
        with self._lock:
            if self._policy is not None:
                return deepcopy(self._policy)
            if self.path.exists():
                try:
                    loaded = json.loads(self.path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise OperationsPolicyError("POLICY_READ_FAILED", str(exc)) from exc
                self._policy = _clean_policy(loaded)
            else:
                self._policy = default_policy()
            return deepcopy(self._policy)

    def replace(self, value: Mapping[str, Any]) -> dict[str, Any]:
        policy = _clean_policy(value)
        policy["updated_at"] = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            try:
                temporary.write_text(json.dumps(policy, ensure_ascii=False, indent=2), encoding="utf-8")
                temporary.replace(self.path)
            except OSError as exc:
                raise OperationsPolicyError("POLICY_WRITE_FAILED", str(exc)) from exc
            self._policy = deepcopy(policy)
            return deepcopy(policy)

    def update_stop(self, *, paused: bool, reason: str = "") -> dict[str, Any]:
        if type(paused) is not bool:
            raise OperationsPolicyError("INVALID_POLICY", "paused must be a boolean")
        current = self.get()
        current["emergency_stop"] = paused
        current["emergency_stop_reason"] = str(reason or "").strip()
        return self.replace(current)

    def guard(
        self, *, action: str, account_key: str | None = None,
        state: Mapping[str, Any] | None = None, now: datetime | None = None,
    ) -> dict[str, Any]:
        if action not in {"prepare_publish", "publish", "reply"}:
            raise OperationsPolicyError("INVALID_POLICY_ACTION", "unsupported operations guard action")
        policy = self.get()
        account = str(account_key or "").strip()
        account_policy = policy["accounts"].get(account, {})
        limits = account_policy.get("limits", policy["default_limits"])
        enabled = account_policy.get("enabled", True)
        reasons: list[str] = []
        if policy["emergency_stop"] and action in {"prepare_publish", "publish", "reply"}:
            reasons.append(policy["emergency_stop_reason"] or "运营人员已启用紧急停止")
        if not enabled:
            reasons.append("该账号已在运营规则中停用")

        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        try:
            local_zone = ZoneInfo(policy["timezone"])
        except ZoneInfoNotFoundError:  # persisted files are revalidated on read; keep the guard fail-safe
            local_zone = timezone.utc
        current = current.astimezone(local_zone)
        records: list[Mapping[str, Any]] = []
        account_aliases = {account} if account else set()
        if isinstance(state, Mapping):
            raw_accounts = state.get("accounts", [])
            if isinstance(raw_accounts, list):
                for item in raw_accounts:
                    if not isinstance(item, Mapping):
                        continue
                    if account and str(item.get("id", "")).strip() == account:
                        for field in ("name", "handle"):
                            value = str(item.get(field, "")).strip()
                            if value:
                                account_aliases.add(value)
            raw_contents = state.get("contents", [])
            if isinstance(raw_contents, list):
                for item in raw_contents:
                    if not isinstance(item, Mapping) or item.get("status") != "published":
                        continue
                    item_account = str(item.get("accountId") or item.get("account") or "").strip()
                    if account and item_account not in account_aliases:
                        # Account IDs and display names are both used by the local console.
                        continue
                    records.append(item)
        day_count = 0
        week_count = 0
        week_start = (current - timedelta(days=current.weekday())).date()
        for item in records:
            stamp = _parse_timestamp(item.get("publishedAt") or item.get("updated"))
            # Human labels such as “刚刚” cannot be dated; count them conservatively
            # in the current window so a missing timestamp cannot bypass a limit.
            if stamp is None:
                day_count += 1
                week_count += 1
                continue
            local_stamp = stamp.astimezone(local_zone)
            if local_stamp.date() == current.date():
                day_count += 1
            if local_stamp.date() >= week_start:
                week_count += 1
        if action in {"prepare_publish", "publish"}:
            if day_count >= limits["daily_publish"]:
                reasons.append(f"已达到今日发布上限 {limits['daily_publish']} 条")
            if week_count >= limits["weekly_publish"]:
                reasons.append(f"已达到本周发布上限 {limits['weekly_publish']} 条")
        allowed = not reasons
        return {
            "allowed": allowed,
            "action": action,
            "account_key": account or None,
            "code": "ALLOWED" if allowed else "OPERATIONS_POLICY_BLOCKED",
            "reasons": reasons,
            "emergency_stop": policy["emergency_stop"],
            "counts": {"today": day_count, "this_week": week_count},
            "limits": deepcopy(limits),
            "account_enabled": enabled,
        }


__all__ = ["OperationsPolicyError", "OperationsPolicyStore", "default_policy"]
