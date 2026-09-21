"""S3-compatible storage configuration and an account-free Fake Storage port."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
import re
import unicodedata
from typing import Any, Mapping, Protocol
from urllib.parse import SplitResult, urlsplit


DEFAULT_STORAGE_NAMESPACE = "tenant"
DEFAULT_SIGNED_URL_TTL_SECONDS = 300
PRIVATE_ACCESS_POLICY = "private"
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MAX_STORAGE_KEY_BYTES = 1024
MAX_NAMESPACE_BYTES = 128


def _canonical_key_text(value: object) -> bool:
    return (
        isinstance(value, str) and bool(value)
        and unicodedata.normalize("NFC", value) == value
        and not any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} or char in "\\%?#" for char in value)
    )


class StorageConfigurationError(ValueError):
    """Raised when S3-compatible storage configuration is invalid."""


class StorageError(RuntimeError):
    """Base class for deterministic storage-port failures."""


class StorageNotFoundError(StorageError):
    """Raised when an object is absent or belongs to another tenant."""


class StorageAccessError(StorageError):
    """Raised when an object reference is outside the tenant namespace."""


class StorageConflictError(StorageError):
    """Raised when immutable object or idempotency invariants are violated."""


def _parse_endpoint(endpoint: str) -> SplitResult:
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise StorageConfigurationError(
            "STORAGE_ENDPOINT_URL must be an http(s) URL with a host"
        )
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise StorageConfigurationError(
            "STORAGE_ENDPOINT_URL must not contain a path, query, or fragment"
        )
    if parsed.username or parsed.password:
        raise StorageConfigurationError("STORAGE_ENDPOINT_URL must not contain credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise StorageConfigurationError("STORAGE_ENDPOINT_URL has an invalid port") from exc
    if port is not None and not 1 <= port <= 65535:
        raise StorageConfigurationError("STORAGE_ENDPOINT_URL port must be between 1 and 65535")
    return parsed


def _positive_int(raw: str | None, *, name: str, default: int) -> int:
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise StorageConfigurationError(f"{name} must be an integer") from exc
    if value <= 0:
        raise StorageConfigurationError(f"{name} must be greater than zero")
    return value


def _required_name(raw: str | None, *, name: str) -> str:
    value = raw
    if not value:
        raise StorageConfigurationError(f"{name} must not be empty")
    if not _canonical_key_text(value) or any(char.isspace() for char in value) or "/" in value or value in {".", ".."}:
        raise StorageConfigurationError(f"{name} contains an invalid character")
    if len(value.encode("utf-8")) > MAX_NAMESPACE_BYTES:
        raise StorageConfigurationError(f"{name} exceeds the UTF-8 byte limit")
    return value


@dataclass(frozen=True)
class StorageSettings:
    """Validated non-secret S3-compatible object-storage settings."""

    endpoint_url: str | None
    bucket_name: str | None
    namespace_prefix: str = DEFAULT_STORAGE_NAMESPACE
    default_access_policy: str = PRIVATE_ACCESS_POLICY
    signed_url_ttl_seconds: int = DEFAULT_SIGNED_URL_TTL_SECONDS
    region: str = "us-east-1"
    source: str = "environment"

    def __post_init__(self) -> None:
        if (self.endpoint_url is None) != (self.bucket_name is None):
            raise StorageConfigurationError(
                "STORAGE_ENDPOINT_URL and STORAGE_BUCKET must be configured together"
            )
        if self.endpoint_url is not None:
            _parse_endpoint(self.endpoint_url)
        if self.bucket_name is not None:
            _required_name(self.bucket_name, name="bucket_name")
        _required_name(self.namespace_prefix, name="namespace_prefix")
        if self.default_access_policy != PRIVATE_ACCESS_POLICY:
            raise StorageConfigurationError("default_access_policy must be private")
        if self.signed_url_ttl_seconds <= 0:
            raise StorageConfigurationError("signed_url_ttl_seconds must be greater than zero")
        _required_name(self.region, name="region")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "StorageSettings":
        values = os.environ if environ is None else environ
        endpoint = (values.get("STORAGE_ENDPOINT_URL") or "").strip() or None
        bucket = (values.get("STORAGE_BUCKET") or "").strip() or None
        policy = (values.get("STORAGE_DEFAULT_ACCESS_POLICY") or PRIVATE_ACCESS_POLICY).strip()
        return cls(
            endpoint_url=endpoint,
            bucket_name=bucket,
            namespace_prefix=(
                values.get("STORAGE_NAMESPACE_PREFIX") or DEFAULT_STORAGE_NAMESPACE
            ),
            default_access_policy=policy,
            signed_url_ttl_seconds=_positive_int(
                values.get("STORAGE_SIGNED_URL_TTL_SECONDS"),
                name="STORAGE_SIGNED_URL_TTL_SECONDS",
                default=DEFAULT_SIGNED_URL_TTL_SECONDS,
            ),
            region=(values.get("STORAGE_REGION") or "us-east-1").strip(),
        )

    @classmethod
    def synthetic_fixture(cls) -> "StorageSettings":
        return cls(
            endpoint_url="http://127.0.0.1:9000",
            bucket_name="foundation-fixture",
            namespace_prefix="tenant",
            default_access_policy=PRIVATE_ACCESS_POLICY,
            signed_url_ttl_seconds=60,
            region="synthetic",
            source="synthetic_fixture",
        )

    @property
    def configured(self) -> bool:
        return bool(self.endpoint_url and self.bucket_name)

    @property
    def redacted_endpoint_url(self) -> str | None:
        if not self.endpoint_url:
            return None
        parsed = _parse_endpoint(self.endpoint_url)
        host = parsed.hostname or ""
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        port = f":{parsed.port}" if parsed.port else ""
        return parsed._replace(netloc=f"{host}{port}").geturl()

    @property
    def config_hash(self) -> str:
        payload = json.dumps(self.as_contract(), sort_keys=True, separators=(",", ":"))
        return f"sha256:{sha256(payload.encode('utf-8')).hexdigest()}"

    def as_contract(self) -> dict[str, Any]:
        return {
            "provider": "s3-compatible",
            "configured": self.configured,
            "endpoint_url": self.redacted_endpoint_url,
            "bucket_name": self.bucket_name,
            "namespace_prefix": self.namespace_prefix,
            "default_access_policy": self.default_access_policy,
            "signed_url_ttl_seconds": self.signed_url_ttl_seconds,
            "region": self.region,
            "source": self.source,
            "credentials_in_repository": False,
        }


def storage_health(settings: StorageSettings) -> dict[str, Any]:
    """Return configuration-only health; no SDK or network probe is attempted."""
    if not settings.configured:
        return {
            "status": "not_configured",
            "provider": "s3-compatible",
            "probe": "skipped",
            "reason": "STORAGE_ENDPOINT_URL and STORAGE_BUCKET are required",
        }
    return {
        "status": "configured",
        "provider": "s3-compatible",
        "probe": "not_attempted",
        "endpoint_url": settings.redacted_endpoint_url,
        "bucket_name": settings.bucket_name,
        "namespace_prefix": settings.namespace_prefix,
        "access_policy": settings.default_access_policy,
        "config_hash": settings.config_hash,
    }


def _validate_org_id(org_id: str) -> str:
    value = org_id
    if not _canonical_key_text(value) or "/" in value or any(char.isspace() for char in value) or value in {".", ".."}:
        raise StorageAccessError("org_id is required and must be a single namespace segment")
    if len(value.encode("utf-8")) > MAX_NAMESPACE_BYTES:
        raise StorageAccessError("org_id exceeds the UTF-8 byte limit")
    return value


def _validate_object_key(object_key: str) -> str:
    value = object_key
    if not _canonical_key_text(value) or value.startswith("/"):
        raise StorageAccessError("object_key must be a non-empty relative key")
    parts = value.split("/")
    if any(part in {"", ".", ".."} or part != part.strip() for part in parts):
        raise StorageAccessError("object_key contains an invalid path segment")
    return value


@dataclass(frozen=True)
class StoredObject:
    org_id: str
    object_key: str
    storage_object_ref: str
    content_hash: str
    size_bytes: int
    content_type: str
    access_policy: str
    metadata: dict[str, str]

    def as_contract(self) -> dict[str, Any]:
        return {
            "org_id": self.org_id,
            "object_key": self.object_key,
            "storage_object_ref": self.storage_object_ref,
            "content_hash": self.content_hash,
            "size_bytes": self.size_bytes,
            "content_type": self.content_type,
            "access_policy": self.access_policy,
            "metadata": dict(self.metadata),
        }


class StoragePort(Protocol):
    def put(
        self,
        org_id: str,
        object_key: str,
        content: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> StoredObject: ...

    def get(self, org_id: str, storage_object_ref: str) -> bytes: ...

    def head(self, org_id: str, storage_object_ref: str) -> StoredObject: ...

    def delete(self, org_id: str, storage_object_ref: str) -> None: ...


class FakeStorage:
    """Deterministic, private-by-default, in-memory StoragePort implementation."""

    def __init__(self, settings: StorageSettings | None = None) -> None:
        self.settings = settings or StorageSettings.synthetic_fixture()
        self._objects: dict[str, tuple[StoredObject, bytes]] = {}
        self._idempotency: dict[tuple[str, str], tuple[str, str]] = {}

    def _reference(self, org_id: str, object_key: str) -> str:
        storage_key = f"{self.settings.namespace_prefix}/{org_id}/{object_key}"
        if len(storage_key.encode("utf-8")) > MAX_STORAGE_KEY_BYTES:
            raise StorageAccessError("storage key exceeds the UTF-8 byte limit")
        return f"private://{self.settings.bucket_name or 'foundation-fixture'}/{self.settings.namespace_prefix}/{org_id}/{object_key}"

    def _parse_reference(self, org_id: str, storage_object_ref: str) -> str:
        expected_prefix = f"private://{self.settings.bucket_name or 'foundation-fixture'}/{self.settings.namespace_prefix}/{_validate_org_id(org_id)}/"
        if not isinstance(storage_object_ref, str) or not storage_object_ref.startswith(expected_prefix):
            raise StorageAccessError("storage object is outside the tenant namespace")
        key = _validate_object_key(storage_object_ref[len(expected_prefix) :])
        self._reference(org_id, key)
        return key

    def put(
        self,
        org_id: str,
        object_key: str,
        content: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> StoredObject:
        tenant = _validate_org_id(org_id)
        key = _validate_object_key(object_key)
        if not isinstance(content, bytes):
            raise TypeError("content must be bytes")
        if not content_type.strip():
            raise StorageAccessError("content_type must not be empty")
        content_hash = sha256(content).hexdigest()
        ref = self._reference(tenant, key)
        payload_hash = sha256(
            json.dumps(
                {"object_key": key, "content_hash": content_hash, "content_type": content_type},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if idempotency_key:
            idempotency_ref = (tenant, idempotency_key)
            previous = self._idempotency.get(idempotency_ref)
            if previous and previous[0] != payload_hash:
                raise StorageConflictError("idempotency key reused with a different payload")
            if previous:
                existing_idempotent = self._objects.get(previous[1])
                if existing_idempotent is not None:
                    return existing_idempotent[0]
                # A deleted object must not leave a dangling idempotency
                # pointer that turns a later valid write into a KeyError.
                self._idempotency.pop(idempotency_ref, None)
        existing = self._objects.get(ref)
        if existing:
            if existing[0].content_hash == content_hash:
                if idempotency_key:
                    self._idempotency[(tenant, idempotency_key)] = (payload_hash, ref)
                return existing[0]
            raise StorageConflictError("object key already contains a different immutable payload")
        record = StoredObject(
            org_id=tenant,
            object_key=key,
            storage_object_ref=ref,
            content_hash=content_hash,
            size_bytes=len(content),
            content_type=content_type,
            access_policy=PRIVATE_ACCESS_POLICY,
            metadata={str(name): str(value) for name, value in (metadata or {}).items()},
        )
        self._objects[ref] = (record, bytes(content))
        if idempotency_key:
            self._idempotency[(tenant, idempotency_key)] = (payload_hash, ref)
        return record

    def head(self, org_id: str, storage_object_ref: str) -> StoredObject:
        self._parse_reference(org_id, storage_object_ref)
        try:
            return self._objects[storage_object_ref][0]
        except KeyError as exc:
            raise StorageNotFoundError("storage object was not found") from exc

    def get(self, org_id: str, storage_object_ref: str) -> bytes:
        self._parse_reference(org_id, storage_object_ref)
        try:
            return bytes(self._objects[storage_object_ref][1])
        except KeyError as exc:
            raise StorageNotFoundError("storage object was not found") from exc

    def delete(self, org_id: str, storage_object_ref: str) -> None:
        self._parse_reference(org_id, storage_object_ref)
        if storage_object_ref not in self._objects:
            raise StorageNotFoundError("storage object was not found")
        del self._objects[storage_object_ref]
        for key, value in tuple(self._idempotency.items()):
            if value[1] == storage_object_ref:
                del self._idempotency[key]

    def list(self, org_id: str) -> tuple[StoredObject, ...]:
        tenant = _validate_org_id(org_id)
        return tuple(record for record, _ in self._objects.values() if record.org_id == tenant)

    def public_url(self, storage_object_ref: str) -> None:
        """Explicitly return no public URL; private objects require a later signer task."""
        if not storage_object_ref.startswith("private://"):
            raise StorageAccessError("only private storage references are supported")
        return None


fake_storage = FakeStorage
