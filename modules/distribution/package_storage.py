"""Private ExportPackage storage, signed downloads and lifecycle controls."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker

from .service import DistributionError, _hash, _stamp, _text, _time, _uuid, _validate


_ROOT = Path(__file__).resolve().parents[2]
_EVENT_VALIDATOR = Draft202012Validator(
    json.loads((_ROOT / "packages/contracts/events/event-envelope.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)


class PackageStoragePort(Protocol):
    """Small private store boundary used by ExportPackageStorage."""

    def put(self, *, org_id: str, storage_object_ref: str, content: bytes) -> None: ...

    def get(self, *, org_id: str, storage_object_ref: str) -> bytes: ...


class InMemoryPrivatePackageStore(PackageStoragePort):
    """Private-by-default object bytes store with immutable references."""

    def __init__(self) -> None:
        self._objects: dict[str, tuple[str, bytes]] = {}

    def put(self, *, org_id: str, storage_object_ref: str, content: bytes) -> None:
        if not isinstance(content, bytes) or not storage_object_ref.startswith("private://") or f"/{org_id}/" not in storage_object_ref:
            raise DistributionError("PRIVATE_STORAGE_REQUIRED", "object must be bytes under the tenant private namespace")
        previous = self._objects.get(storage_object_ref)
        if previous is not None and previous[1] != content:
            raise DistributionError("STORAGE_IMMUTABLE", "storage reference already contains different bytes")
        self._objects[storage_object_ref] = (org_id, bytes(content))

    def get(self, *, org_id: str, storage_object_ref: str) -> bytes:
        value = self._objects.get(storage_object_ref)
        if value is None or value[0] != org_id:
            raise DistributionError("TENANT_SCOPE_VIOLATION", "storage object is outside this organization")
        return bytes(value[1])


class ExportPackageStorage:
    """Register immutable packages and issue short-lived private download URLs."""

    def __init__(self, *, store: PackageStoragePort | None = None, signing_key: bytes | str = b"synthetic-download-key",
                 signed_url_ttl_seconds: int = 300) -> None:
        if isinstance(signing_key, str):
            signing_key = signing_key.encode("utf-8")
        if not isinstance(signing_key, bytes) or not signing_key:
            raise DistributionError("INVALID_STORAGE_SIGNING_KEY", "signing_key must be nonempty bytes")
        if type(signed_url_ttl_seconds) is not int or signed_url_ttl_seconds <= 0:
            raise DistributionError("INVALID_STORAGE_TTL", "signed_url_ttl_seconds must be positive")
        self.store = store or InMemoryPrivatePackageStore()
        self._signing_key = bytes(signing_key)
        self._ttl = signed_url_ttl_seconds
        self.packages: dict[tuple[str, str], dict[str, Any]] = {}
        self.files: dict[tuple[str, str], dict[str, bytes]] = {}
        self.audit: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self._commands: dict[tuple[str, str], tuple[str, Any]] = {}
        self._lock = RLock()

    def register_package(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        export_package: Mapping[str, Any], files: Sequence[Mapping[str, Any]] = (), registered_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        if not isinstance(export_package, Mapping) or export_package.get("org_id") != tenant:
            raise DistributionError("TENANT_SCOPE_VIOLATION", "export package is outside this organization")
        package = deepcopy(dict(export_package))
        _validate("export-package", package)
        if not package["storage_object_ref"].startswith("private://") or f"/{tenant}/" not in package["storage_object_ref"]:
            raise DistributionError("PRIVATE_STORAGE_REQUIRED", "export package must use a tenant private reference")
        normalized_files: dict[str, bytes] = {}
        for item in files:
            if not isinstance(item, Mapping) or not isinstance(item.get("name"), str) or not isinstance(item.get("content"), str):
                raise DistributionError("INVALID_PACKAGE_FILE", "files require name and text content")
            ref = str(item.get("storage_object_ref", ""))
            if not ref.startswith("private://") or f"/{tenant}/" not in ref:
                raise DistributionError("PRIVATE_STORAGE_REQUIRED", "package files must use private references")
            content = item["content"].encode("utf-8")
            digest = hashlib.sha256(content).hexdigest()
            if item.get("sha256") is not None and str(item["sha256"]).lower() != digest:
                raise DistributionError("PACKAGE_HASH_MISMATCH", f"file hash mismatch for {item['name']}")
            normalized_files[item["name"]] = content
        registered = _time(registered_at, "registered_at") or datetime.now(timezone.utc)
        digest = _hash({"package": package, "files": {name: hashlib.sha256(value).hexdigest() for name, value in sorted(normalized_files.items())}})
        with self._lock:
            prior = self._commands.get((tenant, key))
            if prior is not None:
                if prior[0] != digest:
                    raise DistributionError("IDEMPOTENCY_KEY_REUSED", "package registration differs from prior request")
                return deepcopy(prior[1])
            identity = (tenant, package["id"])
            existing = self.packages.get(identity)
            if existing is not None:
                if existing["package_hash"] != package["package_hash"]:
                    raise DistributionError("PACKAGE_IMMUTABLE", "export package cannot be overwritten")
                result = {"export_package": deepcopy(existing), "file_hashes": {name: hashlib.sha256(value).hexdigest() for name, value in sorted(self.files.get(identity, {}).items())}}
                self._commands[(tenant, key)] = (digest, deepcopy(result))
                return result
            self.packages[identity] = deepcopy(package)
            self.files[identity] = dict(normalized_files)
            for item in files:
                self.store.put(org_id=tenant, storage_object_ref=str(item["storage_object_ref"]), content=normalized_files[item["name"]])
            result = {"export_package": deepcopy(package), "file_hashes": {name: hashlib.sha256(value).hexdigest() for name, value in sorted(normalized_files.items())}}
            self._commands[(tenant, key)] = (digest, deepcopy(result))
            self._audit_event("export_package.registered", tenant, actor, trace, key, package, {"package_hash": package["package_hash"]}, registered)
            return deepcopy(result)

    def issue_download_url(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        package_id: UUID | str, issued_at: datetime | str | None = None, ttl_seconds: int | None = None,
    ) -> dict[str, Any]:
        tenant, actor, identity = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id"), _uuid(package_id, "package_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        at = _time(issued_at, "issued_at") or datetime.now(timezone.utc)
        ttl = self._ttl if ttl_seconds is None else ttl_seconds
        if type(ttl) is not int or ttl <= 0 or ttl > 3600:
            raise DistributionError("INVALID_STORAGE_TTL", "ttl_seconds must be between 1 and 3600")
        package = self._get_package(tenant, identity)
        self._check_available(package, at)
        expires = min(at + timedelta(seconds=ttl), _time(package["expires_at"], "package.expires_at", required=True))
        if expires <= at:
            raise DistributionError("PACKAGE_EXPIRED", "export package has expired")
        signature = self._signature(tenant, identity, package["package_hash"], int(expires.timestamp()))
        url = f"private://download/{tenant}/{identity}?{urlencode({'expires': int(expires.timestamp()), 'sig': signature})}"
        digest = _hash({"operation": "issue_download_url", "package_id": identity, "ttl": ttl, "issued_at": _stamp(at)})
        with self._lock:
            prior = self._commands.get((tenant, key))
            if prior is not None:
                if prior[0] != digest:
                    raise DistributionError("IDEMPOTENCY_KEY_REUSED", "download request differs from prior request")
                return deepcopy(prior[1])
            package["download_count"] += 1
            result = {"package_id": identity, "url": url, "expires_at": _stamp(expires), "package_hash": package["package_hash"], "download_count": package["download_count"]}
            self._commands[(tenant, key)] = (digest, deepcopy(result))
            self._audit_event("export_package.downloaded", tenant, actor, trace, key, package, {"expires_at": _stamp(expires)}, at)
            return deepcopy(result)

    def verify_download_url(self, *, org_id: UUID | str, url: str, at: datetime | str | None = None) -> dict[str, Any]:
        tenant = _uuid(org_id, "org_id")
        if not isinstance(url, str) or not url.startswith("private://download/"):
            raise DistributionError("INVALID_SIGNED_URL", "signed URL must use private://download")
        parsed = urlsplit(url)
        parts = parsed.path.strip("/").split("/")
        if parsed.scheme != "private" or parsed.netloc != "download" or len(parts) != 2 or parts[0] != tenant:
            raise DistributionError("TENANT_SCOPE_VIOLATION", "signed URL is outside this organization")
        identity = _uuid(parts[1], "package_id")
        query = parse_qs(parsed.query)
        try:
            expires_epoch, signature = int(query["expires"][0]), query["sig"][0]
        except (KeyError, IndexError, ValueError) as exc:
            raise DistributionError("INVALID_SIGNED_URL", "signed URL query is invalid") from exc
        now = _time(at, "at") or datetime.now(timezone.utc)
        package = self._get_package(tenant, identity)
        self._check_available(package, now)
        if int(now.timestamp()) >= expires_epoch:
            raise DistributionError("SIGNED_URL_EXPIRED", "signed URL has expired")
        expected = self._signature(tenant, identity, package["package_hash"], expires_epoch)
        if not hmac.compare_digest(signature, expected):
            raise DistributionError("INVALID_SIGNED_URL", "signed URL signature is invalid")
        return {"package_id": identity, "package_hash": package["package_hash"], "expires_at": datetime.fromtimestamp(expires_epoch, timezone.utc).isoformat().replace("+00:00", "Z")}

    def revoke_package(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
                       package_id: UUID | str, expected_package_hash: str, revoked_at: datetime | str | None = None) -> dict[str, Any]:
        tenant, actor, identity = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id"), _uuid(package_id, "package_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        package = self._get_package(tenant, identity)
        if package["package_hash"] != expected_package_hash:
            raise DistributionError("STALE_PACKAGE_VERSION", "package hash does not match If-Match")
        at = _time(revoked_at, "revoked_at") or datetime.now(timezone.utc)
        digest = _hash({"operation": "revoke_package", "package_id": identity, "expected_package_hash": expected_package_hash, "revoked_at": _stamp(at)})
        with self._lock:
            prior = self._commands.get((tenant, key))
            if prior is not None:
                if prior[0] != digest:
                    raise DistributionError("IDEMPOTENCY_KEY_REUSED", "revoke request differs from prior request")
                return deepcopy(prior[1])
            if package["status"] == "revoked":
                result = deepcopy(package)
            else:
                package["status"], package["revoked_at"] = "revoked", _stamp(at)
                _validate("export-package", package)
                result = deepcopy(package)
            self._commands[(tenant, key)] = (digest, deepcopy(result))
            self._audit_event("export_package.revoked", tenant, actor, trace, key, package, {"reason": "manual_revoke"}, at)
            return result

    def expire_package(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
                       package_id: UUID | str, at: datetime | str) -> dict[str, Any]:
        tenant, actor, identity = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id"), _uuid(package_id, "package_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        check = _time(at, "at", required=True)
        package = self._get_package(tenant, identity)
        digest = _hash({"operation": "expire_package", "package_id": identity, "at": _stamp(check)})
        with self._lock:
            prior = self._commands.get((tenant, key))
            if prior is not None:
                if prior[0] != digest:
                    raise DistributionError("IDEMPOTENCY_KEY_REUSED", "expiry request differs from prior request")
                return deepcopy(prior[1])
            expiry = _time(package["expires_at"], "package.expires_at", required=True)
            if check < expiry:
                raise DistributionError("PACKAGE_NOT_EXPIRED", "package expiry time has not arrived")
            if package["status"] == "available":
                package["status"] = "expired"
                _validate("export-package", package)
            result = deepcopy(package)
            self._commands[(tenant, key)] = (digest, deepcopy(result))
            self._audit_event("export_package.expired", tenant, actor, trace, key, package, {"expired_at": _stamp(check)}, check)
            return result

    def read_file(self, *, org_id: UUID | str, package_id: UUID | str, name: str, at: datetime | str | None = None) -> bytes:
        tenant, identity = _uuid(org_id, "org_id"), _uuid(package_id, "package_id")
        package = self._get_package(tenant, identity)
        check = _time(at, "at") or datetime.now(timezone.utc)
        self._check_available(package, check)
        if name not in self.files.get((tenant, identity), {}):
            raise DistributionError("PACKAGE_FILE_NOT_FOUND", "package file was not found")
        return bytes(self.files[(tenant, identity)][name])

    def _get_package(self, tenant: str, identity: str) -> dict[str, Any]:
        package = self.packages.get((tenant, identity))
        if package is None:
            raise DistributionError("TENANT_SCOPE_VIOLATION", "export package is not available in organization")
        return package

    def _check_available(self, package: Mapping[str, Any], at: datetime) -> None:
        if package["status"] == "revoked":
            raise DistributionError("PACKAGE_REVOKED", "export package has been revoked")
        expiry = _time(package["expires_at"], "package.expires_at", required=True)
        if package["status"] == "expired" or at >= expiry:
            if isinstance(package, dict) and package["status"] == "available":
                package["status"] = "expired"
            raise DistributionError("PACKAGE_EXPIRED", "export package has expired")

    def _signature(self, tenant: str, identity: str, package_hash: str, expires_epoch: int) -> str:
        payload = f"{tenant}|{identity}|{package_hash}|{expires_epoch}".encode("utf-8")
        return hmac.new(self._signing_key, payload, hashlib.sha256).hexdigest()

    def _audit_event(self, event_type: str, tenant: str, actor: str, trace: str, key: str,
                     package: Mapping[str, Any], payload: Mapping[str, Any], at: datetime) -> None:
        event_payload = {"package_id": package["id"], "package_hash": package["package_hash"], **dict(payload)}
        event = {
            "event_id": str(uuid4()), "event_type": event_type, "event_schema_version": 1,
            "occurred_at": _stamp(at), "org_id": tenant, "trace_id": trace,
            "aggregate_type": "export_package", "aggregate_id": package["id"], "aggregate_version": 1,
            "actor_type": "service", "actor_id": actor, "idempotency_key": key,
            "payload": event_payload, "payload_hash": _hash(event_payload),
        }
        errors = list(_EVENT_VALIDATOR.iter_errors(event))
        if errors:
            raise DistributionError("INVALID_STORAGE_EVENT", errors[0].message)
        self.events.append(event)
        self.audit.append({"event_type": event_type, "org_id": tenant, "actor_id": actor, "trace_id": trace,
                           "idempotency_key": key, "input_hash": _hash(payload), "output_hash": _hash(package),
                           "package_id": package["id"]})


__all__ = ["ExportPackageStorage", "InMemoryPrivatePackageStore", "PackageStoragePort"]
