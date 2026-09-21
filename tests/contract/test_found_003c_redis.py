from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json

from jsonschema import Draft202012Validator, FormatChecker
import pytest
import yaml

from infra.foundation.redis import (
    FakeRedis,
    RedisConfigurationError,
    RedisSettings,
)


ROOT = Path(__file__).resolve().parents[2]


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 18, 10, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


def test_redis_baseline_schema_and_no_fact_capabilities() -> None:
    baseline = yaml.safe_load((ROOT / "docs/foundation/redis-baseline-v1.yaml").read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "packages/contracts/jsonschema/redis-config.schema.json").read_text(encoding="utf-8"))
    union = json.loads((ROOT / "packages/contracts/jsonschema/foundation.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(baseline)
    assert {item["$ref"] for item in union["oneOf"]} >= {"./redis-config.schema.json"}
    assert baseline["allowed_capabilities"] == ["cache", "short_lock", "rate_limit"]
    assert baseline["queue_dependency"] is False
    assert set(baseline["forbidden_capabilities"]) >= {"business_facts", "task_jobs", "outbox_events", "audit_log"}


def test_settings_redact_endpoint_and_reject_credentials_or_invalid_values() -> None:
    fixture = RedisSettings.from_env({})
    contract = fixture.as_contract()
    assert contract["configured"] is False
    assert contract["endpoint_scheme"] is None
    assert "endpoint_url" not in contract
    configured = RedisSettings.from_env({"REDIS_URL": "rediss://cache.example:6380/0"})
    assert configured.as_contract()["endpoint_scheme"] == "rediss"
    with pytest.raises(RedisConfigurationError, match="credentials"):
        RedisSettings.from_env({"REDIS_URL": "redis://:password@cache.example:6379/0"})
    with pytest.raises(RedisConfigurationError, match="integer"):
        RedisSettings.from_env({"REDIS_LOCK_TTL_SECONDS": "short"})
    with pytest.raises(RedisConfigurationError, match="NAMESPACE"):
        RedisSettings(namespace_prefix="tenant/one")


def test_fake_cache_is_tenant_isolated_and_ttl_expires() -> None:
    clock = Clock()
    redis = FakeRedis(now=clock)
    redis.set_cache("org-a", "article", b"a", ttl_seconds=5)
    redis.set_cache("org-b", "article", b"b", ttl_seconds=5)
    assert redis.get_cache("org-a", "article") == b"a"
    assert redis.get_cache("org-b", "article") == b"b"
    clock.advance(5)
    assert redis.get_cache("org-a", "article") is None
    with pytest.raises(ValueError):
        redis.get_cache("org/a", "article")
    with pytest.raises(ValueError):
        redis.set_cache("org-a", "article", "text")  # type: ignore[arg-type]


def test_lock_requires_owner_token_and_expires() -> None:
    clock = Clock()
    redis = FakeRedis(now=clock)
    assert redis.acquire_lock("org-a", "job", "worker-a", ttl_seconds=3)
    assert not redis.acquire_lock("org-a", "job", "worker-b", ttl_seconds=3)
    assert not redis.release_lock("org-a", "job", "worker-b")
    assert redis.release_lock("org-a", "job", "worker-a")
    assert redis.acquire_lock("org-a", "job", "worker-b", ttl_seconds=3)
    clock.advance(3)
    assert redis.acquire_lock("org-a", "job", "worker-c", ttl_seconds=3)
    assert not redis.release_lock("org-a", "job", "worker-b")


def test_rate_limit_rejects_after_capacity_and_recovers_after_window() -> None:
    clock = Clock()
    redis = FakeRedis(now=clock)
    assert redis.allow_rate("org-a", "api", limit=2, window_seconds=10).allowed
    second = redis.allow_rate("org-a", "api", limit=2, window_seconds=10)
    assert second.allowed and second.remaining == 0
    rejected = redis.allow_rate("org-a", "api", limit=2, window_seconds=10)
    assert not rejected.allowed and rejected.retry_after_seconds == 10
    assert redis.allow_rate("org-b", "api", limit=2, window_seconds=10).allowed
    clock.advance(10)
    assert redis.allow_rate("org-a", "api", limit=2, window_seconds=10).allowed
