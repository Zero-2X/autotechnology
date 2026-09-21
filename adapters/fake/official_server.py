"""A local fake platform server within the account-free adapter boundary.

The server accepts only an opaque ``connection_handle``.  It never accepts a
raw token, opens a socket, or produces a public URL.  Its quota, permission
failure and unknown-result switches make the platform boundary testable before
``EXT-ACCOUNT-001`` is available.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker

from modules.distribution.service import _hash, _stamp, _time, _uuid


_ROOT = Path(__file__).resolve().parents[2]
_CAPABILITY = json.loads(
    (_ROOT / "packages/contracts/jsonschema/publisher-capability.schema.json").read_text(encoding="utf-8")
)
_CAPABILITY_VALIDATOR = Draft202012Validator(_CAPABILITY, format_checker=FormatChecker())


class FakePlatformError(ValueError):
    """Machine-readable fake server failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class FakeOfficialServer:
    """Simulate draft, publish, quota, permission and re-query behavior."""

    adapter_ref = "fake:official-server@v1"

    def __init__(self, *, platform_id: UUID | str | None = None, quota: int = 10,
                 window_seconds: int = 60, clock: Any | None = None) -> None:
        self.platform_id = _uuid(platform_id or UUID("00000000-0000-4000-8000-000000000003"), "platform_id")
        if type(quota) is not int or quota < 1 or type(window_seconds) is not int or window_seconds < 1:
            raise FakePlatformError("INVALID_QUOTA", "quota and window_seconds must be positive integers")
        self.quota = quota
        self.window_seconds = window_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.handles: dict[tuple[str, str], dict[str, Any]] = {}
        self.drafts: dict[tuple[str, str], dict[str, Any]] = {}
        self.records: dict[tuple[str, str], dict[str, Any]] = {}
        self.requests: dict[tuple[str, str], dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self._lock = RLock()

    def capability(self, *, created_at: datetime | str | None = None) -> dict[str, Any]:
        value = {
            "id": str(uuid4()), "platform_id": self.platform_id, "version": 1,
            "actions": ["draft", "publish", "metrics", "requery"],
            "limits": {"requests_per_window": self.quota, "window_seconds": self.window_seconds},
            "policy_version": "fake-official-server-v1", "status": "active",
            "created_at": _stamp(_time(created_at, "created_at") or self._now()),
        }
        # The contract requires UUID strings and a closed limits object.  Keep
        # the quota details in the server state and expose an empty snapshot.
        value["platform_id"] = str(self.platform_id)
        value["limits"] = {}
        errors = sorted(_CAPABILITY_VALIDATOR.iter_errors(value), key=lambda error: list(error.path))
        if errors:
            raise FakePlatformError("INVALID_CAPABILITY", errors[0].message)
        return value

    def issue_connection_handle(self, *, org_id: UUID | str, external_account_id: str,
                                scopes: list[str] | tuple[str, ...] = ("content.draft", "content.publish"),
                                permissions: list[str] | tuple[str, ...] = ("draft", "publish", "metrics", "requery")) -> str:
        tenant = _uuid(org_id, "org_id")
        external = str(external_account_id).strip() if isinstance(external_account_id, str) else ""
        if not external:
            raise FakePlatformError("INVALID_CONNECTION", "external_account_id is required")
        handle = f"handle://fake/{uuid4()}"
        self.handles[(tenant, handle)] = {
            "org_id": tenant, "external_account_id": external,
            "scopes": sorted(set(scopes)), "permissions": sorted(set(permissions)),
            "window_start": self._now(), "request_count": 0, "revoked": False,
        }
        return handle

    def revoke_handle(self, *, org_id: UUID | str, connection_handle: str) -> None:
        record = self._handle(org_id, connection_handle)
        record["revoked"] = True

    def set_permissions(self, *, org_id: UUID | str, connection_handle: str,
                        permissions: list[str] | tuple[str, ...]) -> None:
        record = self._handle(org_id, connection_handle)
        record["permissions"] = sorted(set(permissions))

    def create_draft(self, *, org_id: UUID | str, connection_handle: str,
                     idempotency_key: str, title: str, body: str,
                     now: datetime | str | None = None) -> dict[str, Any]:
        tenant, handle, key = self._command_inputs(org_id, connection_handle, idempotency_key)
        if not isinstance(title, str) or not title.strip() or not isinstance(body, str) or not body.strip():
            raise FakePlatformError("INVALID_DRAFT", "title and body are required")
        digest = _hash({"operation": "draft", "handle": handle, "title": title, "body": body})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            self._guard(handle, "draft", now)
            draft_id = str(uuid4())
            result = {"id": draft_id, "org_id": tenant, "platform_id": self.platform_id,
                      "external_account_id": self.handles[(tenant, handle)]["external_account_id"],
                      "status": "draft", "version": 1, "title": title.strip(), "body": body,
                      "created_at": _stamp(_time(now, "now") or self._now())}
            self.drafts[(tenant, draft_id)] = deepcopy(result)
            self.requests[(tenant, key)] = {"digest": digest, "result": deepcopy(result)}
            self._audit("fake.platform.draft", tenant, key, digest, result)
            return deepcopy(result)

    def publish(self, *, org_id: UUID | str, connection_handle: str,
                draft_id: UUID | str, idempotency_key: str,
                unknown_result: bool = False, now: datetime | str | None = None) -> dict[str, Any]:
        tenant, handle, key = self._command_inputs(org_id, connection_handle, idempotency_key)
        identity = _uuid(draft_id, "draft_id")
        draft = self.drafts.get((tenant, identity))
        if draft is None:
            raise FakePlatformError("DRAFT_NOT_FOUND", "draft is not available in organization")
        self._assert_account(tenant, handle, draft)
        digest = _hash({"operation": "publish", "handle": handle, "draft_id": identity})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            if draft["status"] == "published":
                raise FakePlatformError("ALREADY_PUBLISHED", "draft already has a publication; re-query it")
            self._guard(handle, "publish", now)
            external_id = f"fake-object-{_hash({'tenant': tenant, 'draft': identity})[:16]}"
            record = {"id": str(uuid4()), "org_id": tenant, "platform_id": self.platform_id,
                      "external_account_id": self.handles[(tenant, handle)]["external_account_id"],
                      "draft_id": identity, "external_object_id": external_id,
                      "status": "published", "external_url": f"private://fake/{external_id}",
                      "observed_at": _stamp(_time(now, "now") or self._now())}
            self.records[(tenant, external_id)] = deepcopy(record)
            self.requests[(tenant, key)] = {"digest": digest, "result": deepcopy(record), "unknown": unknown_result}
            self._audit("fake.platform.publish", tenant, key, digest, record)
            draft["status"] = "published"
            draft["version"] += 1
            if unknown_result:
                raise FakePlatformError("UNKNOWN_RESULT", "platform acknowledgement was lost; re-query is required")
            return deepcopy(record)

    def requery(self, *, org_id: UUID | str, connection_handle: str,
                external_object_id: str, idempotency_key: str) -> dict[str, Any]:
        tenant, handle, key = self._command_inputs(org_id, connection_handle, idempotency_key)
        external = str(external_object_id).strip() if isinstance(external_object_id, str) else ""
        if not external:
            raise FakePlatformError("INVALID_REQUERY", "external_object_id is required")
        digest = _hash({"operation": "requery", "handle": handle, "external_object_id": external})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            self._guard(handle, "requery", None)
            record = self.records.get((tenant, external))
            if record is None:
                raise FakePlatformError("OBJECT_NOT_FOUND", "external object is not available")
            self._assert_account(tenant, handle, record)
            self.requests[(tenant, key)] = {"digest": digest, "result": deepcopy(record)}
            self._audit("fake.platform.requery", tenant, key, digest, record)
            return deepcopy(record)

    def metrics(self, *, org_id: UUID | str, connection_handle: str,
                external_object_id: str, idempotency_key: str) -> dict[str, Any]:
        tenant, handle, key = self._command_inputs(org_id, connection_handle, idempotency_key)
        external = str(external_object_id).strip() if isinstance(external_object_id, str) else ""
        digest = _hash({"operation": "metrics", "handle": handle, "external_object_id": external})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            self._guard(handle, "metrics", None)
            if (tenant, external) not in self.records:
                raise FakePlatformError("OBJECT_NOT_FOUND", "external object is not available")
            self._assert_account(tenant, handle, self.records[(tenant, external)])
            result = {"external_object_id": external, "views": 0, "likes": 0, "shares": 0,
                      "source": "fake", "observed_at": _stamp(self._now())}
            self.requests[(tenant, key)] = {"digest": digest, "result": deepcopy(result)}
            self._audit("fake.platform.metrics", tenant, key, digest, result)
            return result

    def _command_inputs(self, org_id: UUID | str, handle: str, key: str) -> tuple[str, str, str]:
        tenant = _uuid(org_id, "org_id")
        if not isinstance(handle, str) or not handle.startswith("handle://fake/"):
            raise FakePlatformError("INVALID_CONNECTION_HANDLE", "only opaque fake handles are accepted")
        if not isinstance(key, str) or not key.strip():
            raise FakePlatformError("INVALID_IDEMPOTENCY_KEY", "idempotency_key is required")
        self._handle(tenant, handle)
        return tenant, handle, key.strip()

    def _handle(self, org_id: UUID | str, handle: str) -> dict[str, Any]:
        tenant = _uuid(org_id, "org_id")
        record = self.handles.get((tenant, handle))
        if record is None:
            raise FakePlatformError("TENANT_SCOPE_VIOLATION", "connection handle is not available in organization")
        if record["revoked"]:
            raise FakePlatformError("PERMISSION_REVOKED", "connection handle has been revoked")
        return record

    def _guard(self, handle: str, action: str, now: datetime | str | None) -> None:
        tenant = next((scope for scope, value in self.handles if value == handle), None)
        if tenant is None:
            raise FakePlatformError("TENANT_SCOPE_VIOLATION", "connection handle is not registered")
        record = self.handles[(tenant, handle)]
        if action not in record["permissions"]:
            raise FakePlatformError("PERMISSION_REVOKED", f"permission for {action} is unavailable")
        if action in {"draft", "publish"} and f"content.{action}" not in record["scopes"]:
            raise FakePlatformError("SCOPE_REQUIRED", f"scope for {action} is unavailable")
        at = _time(now, "now") if now is not None else self._now()
        if at - record["window_start"] >= timedelta(seconds=self.window_seconds):
            record["window_start"], record["request_count"] = at, 0
        if record["request_count"] >= self.quota:
            raise FakePlatformError("QUOTA_EXCEEDED", "fake platform quota exceeded")
        record["request_count"] += 1

    def _assert_account(self, tenant: str, handle: str, value: dict[str, Any]) -> None:
        if value["external_account_id"] != self._handle(tenant, handle)["external_account_id"]:
            raise FakePlatformError("ACCOUNT_SCOPE_VIOLATION", "object belongs to another platform account")

    def _prior(self, tenant: str, key: str, digest: str) -> dict[str, Any] | None:
        prior = self.requests.get((tenant, key))
        if prior is None:
            return None
        if prior["digest"] != digest:
            raise FakePlatformError("IDEMPOTENCY_KEY_REUSED", "request differs from prior command")
        return deepcopy(prior["result"])

    def _audit(self, event_type: str, tenant: str, key: str, digest: str, result: dict[str, Any]) -> None:
        self.audit.append({"event_type": event_type, "org_id": tenant, "idempotency_key": key,
                           "input_hash": digest, "output_hash": _hash(result)})

    def _now(self) -> datetime:
        return _time(self._clock(), "clock", required=True)  # type: ignore[return-value]


__all__ = ["FakeOfficialServer", "FakePlatformError"]
