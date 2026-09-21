"""Account-free Redis capability ports and a deterministic in-memory substitute.

This module intentionally has no Redis client or network code. Redis remains an
optional acceleration facility; PostgreSQL and object storage remain facts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import os
import re
from typing import Callable, Mapping, Protocol
from urllib.parse import urlsplit


DEFAULT_NAMESPACE_PREFIX = "foundation"
DEFAULT_CACHE_TTL_SECONDS = 300
DEFAULT_LOCK_TTL_SECONDS = 30
DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60
DEFAULT_RATE_LIMIT_CAPACITY = 60
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class RedisConfigurationError(ValueError):
    """Raised when optional Redis configuration is invalid or unsafe."""


class RedisAccessError(ValueError):
    """Raised when a capability key or tenant context is invalid."""


@dataclass(frozen=True)
class RedisSettings:
    endpoint_url: str | None = None
    namespace_prefix: str = DEFAULT_NAMESPACE_PREFIX
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS
    lock_ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS
    rate_limit_window_seconds: int = DEFAULT_RATE_LIMIT_WINDOW_SECONDS
    rate_limit_capacity: int = DEFAULT_RATE_LIMIT_CAPACITY
    source: str = "environment"

    def __post_init__(self) -> None:
        if self.endpoint_url is not None:
            parsed = urlsplit(self.endpoint_url)
            if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
                raise RedisConfigurationError("REDIS_URL must be a redis:// or rediss:// URL with a host")
            if parsed.username or parsed.password:
                raise RedisConfigurationError("REDIS_URL must not contain credentials")
            if parsed.query or parsed.fragment:
                raise RedisConfigurationError("REDIS_URL must not contain query or fragment")
            try:
                port = parsed.port
            except ValueError as exc:
                raise RedisConfigurationError("REDIS_URL has an invalid port") from exc
            if port is not None and not 1 <= port <= 65535:
                raise RedisConfigurationError("REDIS_URL port must be between 1 and 65535")
        if not _NAME.fullmatch(self.namespace_prefix) or self.namespace_prefix in {".", ".."}:
            raise RedisConfigurationError("REDIS_NAMESPACE_PREFIX contains an invalid character")
        if self.cache_ttl_seconds <= 0 or self.cache_ttl_seconds > 86400:
            raise RedisConfigurationError("cache_ttl_seconds must be between 1 and 86400")
        if self.lock_ttl_seconds <= 0 or self.lock_ttl_seconds > 300:
            raise RedisConfigurationError("lock_ttl_seconds must be between 1 and 300")
        if self.rate_limit_window_seconds <= 0 or self.rate_limit_window_seconds > 86400:
            raise RedisConfigurationError("rate_limit_window_seconds must be between 1 and 86400")
        if self.rate_limit_capacity <= 0:
            raise RedisConfigurationError("rate_limit_capacity must be greater than zero")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "RedisSettings":
        values = os.environ if environ is None else environ

        def positive(name: str, default: int) -> int:
            raw = (values.get(name) or str(default)).strip()
            try:
                return int(raw)
            except ValueError as exc:
                raise RedisConfigurationError(f"{name} must be an integer") from exc

        endpoint = (values.get("REDIS_URL") or "").strip() or None
        return cls(
            endpoint_url=endpoint,
            namespace_prefix=(values.get("REDIS_NAMESPACE_PREFIX") or DEFAULT_NAMESPACE_PREFIX).strip(),
            cache_ttl_seconds=positive("REDIS_CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL_SECONDS),
            lock_ttl_seconds=positive("REDIS_LOCK_TTL_SECONDS", DEFAULT_LOCK_TTL_SECONDS),
            rate_limit_window_seconds=positive("REDIS_RATE_LIMIT_WINDOW_SECONDS", DEFAULT_RATE_LIMIT_WINDOW_SECONDS),
            rate_limit_capacity=positive("REDIS_RATE_LIMIT_CAPACITY", DEFAULT_RATE_LIMIT_CAPACITY),
        )

    @classmethod
    def synthetic_fixture(cls) -> "RedisSettings":
        return cls(endpoint_url=None, source="synthetic")

    def as_contract(self) -> dict[str, object]:
        """Return a redacted snapshot; never expose the endpoint or credentials."""
        scheme = urlsplit(self.endpoint_url).scheme if self.endpoint_url else None
        return {
            "configured": self.endpoint_url is not None,
            "endpoint_scheme": scheme,
            "namespace_prefix": self.namespace_prefix,
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "lock_ttl_seconds": self.lock_ttl_seconds,
            "rate_limit_window_seconds": self.rate_limit_window_seconds,
            "rate_limit_capacity": self.rate_limit_capacity,
            "source": self.source,
            "configuration_hash": sha256(
                repr((scheme, self.namespace_prefix, self.cache_ttl_seconds, self.lock_ttl_seconds, self.rate_limit_window_seconds, self.rate_limit_capacity)).encode()
            ).hexdigest(),
        }

    def health(self) -> dict[str, object]:
        return {
            "component": "redis",
            "status": "configured" if self.endpoint_url else "not_configured",
            "probe": "not_attempted",
            "details": self.as_contract(),
        }


class CachePort(Protocol):
    def set_cache(self, org_id: str, key: str, value: bytes, *, ttl_seconds: int | None = None) -> None: ...
    def get_cache(self, org_id: str, key: str) -> bytes | None: ...
    def delete_cache(self, org_id: str, key: str) -> bool: ...


class LockPort(Protocol):
    def acquire_lock(self, org_id: str, key: str, token: str, *, ttl_seconds: int | None = None) -> bool: ...
    def release_lock(self, org_id: str, key: str, token: str) -> bool: ...


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: int


class RateLimitPort(Protocol):
    def allow_rate(self, org_id: str, key: str, *, cost: int = 1, limit: int | None = None, window_seconds: int | None = None) -> RateLimitDecision: ...


@dataclass
class _Entry:
    value: bytes
    expires_at: datetime


@dataclass
class _RateBucket:
    used: int
    expires_at: datetime


def _required(value: str, label: str) -> str:
    if not isinstance(value, str) or not value or not _NAME.fullmatch(value):
        raise RedisAccessError(f"{label} contains an invalid value")
    return value


class FakeRedis(CachePort, LockPort, RateLimitPort):
    """Deterministic, tenant-scoped memory substitute for tests and local runs."""

    def __init__(self, settings: RedisSettings | None = None, *, now: Callable[[], datetime] | None = None) -> None:
        self.settings = settings or RedisSettings.synthetic_fixture()
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._cache: dict[str, _Entry] = {}
        self._locks: dict[str, _Entry] = {}
        self._rates: dict[str, _RateBucket] = {}

    def _time(self) -> datetime:
        current = self._now()
        if current.tzinfo is None or current.utcoffset() is None:
            raise RedisAccessError("clock must return a timezone-aware datetime")
        return current

    def _key(self, org_id: str, capability: str, key: str) -> str:
        return "/".join((self.settings.namespace_prefix, _required(org_id, "org_id"), capability, _required(key, "key")))

    def _ttl(self, value: int | None, default: int, label: str) -> int:
        ttl = default if value is None else value
        if ttl <= 0:
            raise RedisAccessError(f"{label} must be greater than zero")
        return ttl

    def _live(self, store: dict[str, _Entry], key: str) -> _Entry | None:
        entry = store.get(key)
        if entry is not None and entry.expires_at <= self._time():
            del store[key]
            return None
        return entry

    def set_cache(self, org_id: str, key: str, value: bytes, *, ttl_seconds: int | None = None) -> None:
        if not isinstance(value, bytes):
            raise RedisAccessError("cache value must be bytes")
        ttl = self._ttl(ttl_seconds, self.settings.cache_ttl_seconds, "cache ttl")
        cache_key = self._key(org_id, "cache", key)
        self._cache[cache_key] = _Entry(bytes(value), self._time() + timedelta(seconds=ttl))

    def get_cache(self, org_id: str, key: str) -> bytes | None:
        entry = self._live(self._cache, self._key(org_id, "cache", key))
        return None if entry is None else bytes(entry.value)

    def delete_cache(self, org_id: str, key: str) -> bool:
        return self._cache.pop(self._key(org_id, "cache", key), None) is not None

    def acquire_lock(self, org_id: str, key: str, token: str, *, ttl_seconds: int | None = None) -> bool:
        if not token or not _NAME.fullmatch(token):
            raise RedisAccessError("lock token contains an invalid value")
        ttl = self._ttl(ttl_seconds, self.settings.lock_ttl_seconds, "lock ttl")
        lock_key = self._key(org_id, "lock", key)
        if self._live(self._locks, lock_key) is not None:
            return False
        self._locks[lock_key] = _Entry(token.encode("utf-8"), self._time() + timedelta(seconds=ttl))
        return True

    def release_lock(self, org_id: str, key: str, token: str) -> bool:
        lock_key = self._key(org_id, "lock", key)
        entry = self._live(self._locks, lock_key)
        if entry is None or entry.value != token.encode("utf-8"):
            return False
        del self._locks[lock_key]
        return True

    def allow_rate(self, org_id: str, key: str, *, cost: int = 1, limit: int | None = None, window_seconds: int | None = None) -> RateLimitDecision:
        if cost <= 0:
            raise RedisAccessError("rate cost must be greater than zero")
        capacity = self.settings.rate_limit_capacity if limit is None else limit
        window = self.settings.rate_limit_window_seconds if window_seconds is None else window_seconds
        if capacity <= 0 or window <= 0:
            raise RedisAccessError("rate limit capacity and window must be greater than zero")
        rate_key = self._key(org_id, "rate", key)
        current = self._time()
        bucket = self._rates.get(rate_key)
        if bucket is None or bucket.expires_at <= current:
            bucket = _RateBucket(used=0, expires_at=current + timedelta(seconds=window))
            self._rates[rate_key] = bucket
        if bucket.used + cost > capacity:
            retry = max(1, int((bucket.expires_at - current).total_seconds() + 0.999))
            return RateLimitDecision(False, max(0, capacity - bucket.used), retry)
        bucket.used += cost
        return RateLimitDecision(True, capacity - bucket.used, 0)
