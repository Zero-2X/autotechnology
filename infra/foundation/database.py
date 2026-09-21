"""PostgreSQL configuration and account-free connection seams.

This module deliberately stops at configuration and an injectable health probe.
It does not import a PostgreSQL driver, open a network socket, or expose
credentials. A later persistence task owns the concrete driver and pool.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
import sqlite3
from typing import Any, Callable, Mapping
from urllib.parse import SplitResult, urlsplit


POSTGRES_SCHEMES = frozenset({"postgres", "postgresql"})
DEFAULT_APPLICATION_NAME = "ai-content-workflow"
DEFAULT_CONNECT_TIMEOUT_SECONDS = 3


class DatabaseConfigurationError(ValueError):
    """Raised when a configured PostgreSQL URL is malformed."""


def _parse_url(url: str) -> SplitResult:
    parsed = urlsplit(url)
    if parsed.scheme not in POSTGRES_SCHEMES:
        raise DatabaseConfigurationError(
            "DATABASE_URL must use the postgres:// or postgresql:// scheme"
        )
    if not parsed.hostname:
        raise DatabaseConfigurationError("DATABASE_URL must include a PostgreSQL host")
    if not parsed.path or parsed.path == "/":
        raise DatabaseConfigurationError(
            "DATABASE_URL must include a PostgreSQL database name"
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise DatabaseConfigurationError("DATABASE_URL has an invalid port") from exc
    if port is not None and not 1 <= port <= 65535:
        raise DatabaseConfigurationError("DATABASE_URL port must be between 1 and 65535")
    return parsed


def _positive_int(raw: str | None, *, name: str, default: int) -> int:
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise DatabaseConfigurationError(f"{name} must be an integer") from exc
    if value <= 0:
        raise DatabaseConfigurationError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True)
class DatabaseSettings:
    """Validated, non-secret PostgreSQL connection settings."""

    url: str | None
    connect_timeout_seconds: int = DEFAULT_CONNECT_TIMEOUT_SECONDS
    application_name: str = DEFAULT_APPLICATION_NAME
    source: str = "environment"

    def __post_init__(self) -> None:
        if self.url is not None:
            _parse_url(self.url)
        if self.connect_timeout_seconds <= 0:
            raise DatabaseConfigurationError(
                "connect_timeout_seconds must be greater than zero"
            )
        if not self.application_name.strip():
            raise DatabaseConfigurationError("application_name must not be empty")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "DatabaseSettings":
        values = os.environ if environ is None else environ
        raw_url = (values.get("DATABASE_URL") or "").strip() or None
        return cls(
            url=raw_url,
            connect_timeout_seconds=_positive_int(
                values.get("DATABASE_CONNECT_TIMEOUT_SECONDS"),
                name="DATABASE_CONNECT_TIMEOUT_SECONDS",
                default=DEFAULT_CONNECT_TIMEOUT_SECONDS,
            ),
            application_name=(
                values.get("DATABASE_APPLICATION_NAME") or DEFAULT_APPLICATION_NAME
            ).strip(),
            source="environment",
        )

    @classmethod
    def synthetic_fixture(cls) -> "DatabaseSettings":
        """Return a deterministic local fixture without real credentials."""
        return cls(
            url="postgresql://fixture@127.0.0.1:5432/foundation_fixture",
            connect_timeout_seconds=1,
            application_name="ai-content-workflow-fixture",
            source="synthetic_fixture",
        )

    @property
    def configured(self) -> bool:
        return self.url is not None

    @property
    def parsed(self) -> SplitResult | None:
        return _parse_url(self.url) if self.url else None

    @property
    def host(self) -> str | None:
        return self.parsed.hostname if self.parsed else None

    @property
    def port(self) -> int:
        return (self.parsed.port if self.parsed and self.parsed.port else 5432)

    @property
    def database_name(self) -> str | None:
        if not self.parsed:
            return None
        return self.parsed.path.lstrip("/") or None

    @property
    def ssl_mode(self) -> str:
        return (self.parsed.query and _query_value(self.parsed.query, "sslmode")) or "prefer"

    @property
    def redacted_url(self) -> str | None:
        """Return a URL safe for health responses and audit evidence."""
        parsed = self.parsed
        if parsed is None:
            return None
        userinfo = f"{parsed.username}@" if parsed.username else ""
        host = parsed.hostname or ""
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        port = f":{parsed.port}" if parsed.port else ""
        netloc = f"{userinfo}{host}{port}"
        return parsed._replace(netloc=netloc).geturl()

    @property
    def config_hash(self) -> str:
        payload = json.dumps(self.as_contract(), sort_keys=True, separators=(",", ":"))
        digest = sha256(payload.encode("utf-8")).hexdigest()
        return f"sha256:{digest}"

    def as_contract(self) -> dict[str, Any]:
        return {
            "engine": "postgresql",
            "configured": self.configured,
            "redacted_url": self.redacted_url,
            "host": self.host,
            "port": self.port if self.configured else None,
            "database_name": self.database_name,
            "ssl_mode": self.ssl_mode if self.configured else None,
            "connect_timeout_seconds": self.connect_timeout_seconds,
            "application_name": self.application_name,
            "source": self.source,
        }


def _query_value(query: str, key: str) -> str | None:
    for item in query.split("&"):
        name, separator, value = item.partition("=")
        if separator and name == key:
            return value or None
    return None


Probe = Callable[[DatabaseSettings], bool | Mapping[str, Any]]


def database_health(settings: DatabaseSettings, probe: Probe | None = None) -> dict[str, Any]:
    """Return a deterministic health snapshot without probing by default."""
    if not settings.configured:
        return {
            "status": "not_configured",
            "configured": False,
            "engine": "postgresql",
            "probe": "skipped",
            "reason": "DATABASE_URL is not set",
        }
    if probe is None:
        return {
            "status": "configured",
            "configured": True,
            "engine": "postgresql",
            "probe": "not_attempted",
            "reason": "No database driver or network probe is installed in the bootstrap",
            "host": settings.host,
            "port": settings.port,
            "database_name": settings.database_name,
            "ssl_mode": settings.ssl_mode,
            "config_hash": settings.config_hash,
        }
    try:
        result = probe(settings)
    except Exception as exc:  # pragma: no cover - concrete probes own exception policy
        return {
            "status": "unavailable",
            "configured": True,
            "engine": "postgresql",
            "probe": "failed",
            "reason": type(exc).__name__,
            "config_hash": settings.config_hash,
        }
    if isinstance(result, Mapping):
        return {"status": "ready", "configured": True, "engine": "postgresql", **dict(result)}
    return {
        "status": "ready" if result else "unavailable",
        "configured": True,
        "engine": "postgresql",
        "probe": "completed",
        "config_hash": settings.config_hash,
    }


@dataclass
class ConnectionFixture:
    """Minimal in-memory DB-API fixture with an explicit synthetic boundary."""

    settings: DatabaseSettings
    connection: sqlite3.Connection

    def __enter__(self) -> "ConnectionFixture":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.connection.close()


def create_connection_fixture() -> ConnectionFixture:
    return ConnectionFixture(DatabaseSettings.synthetic_fixture(), sqlite3.connect(":memory:"))


postgresql_connection_fixture = create_connection_fixture
