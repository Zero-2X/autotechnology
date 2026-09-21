from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from modules.analytics import AnalyticsError, MetricDefinitionService, ObservationService


ORG = str(uuid4())
OTHER = str(uuid4())
ACTOR = str(uuid4())
NOW = datetime(2026, 9, 20, 14, 0, tzinfo=timezone.utc)


def context(org: str = ORG) -> dict[str, str]:
    return {"org_id": org, "actor_id": ACTOR, "trace_id": "observation-test"}


def active_metric(*, key: str = "publication.success_rate", metric_type: str = "number", quality_rules=None):
    metrics = MetricDefinitionService(clock=lambda: NOW)
    created = metrics.create_metric_definition(
        {
            "key": key,
            "metric_type": metric_type,
            "unit": "ratio" if metric_type == "number" else "state",
            "formula": "identity",
            "dimensions": ["market", "locale"],
            "window": "P7D",
            "data_source": "analytics.publication.observed",
            "dedupe_rule": "event_id",
            "quality_rules": quality_rules or {},
            "owner_actor_id": ACTOR,
        },
        context=context(), idempotency_key=f"metric-{key}",
    )
    return metrics.activate_metric_definition(
        created["id"], context=context(), idempotency_key=f"activate-{key}", expected_version=1,
    )


def observation(**overrides):
    value = {
        "source": "fake",
        "subject_type": "publication",
        "subject_id": str(uuid4()),
        "metric_value": 0.75,
        "observed_at": "2026-09-20T13:00:00Z",
        "locale": "en-us",
        "region": "us",
        "data_quality": "estimated",
        "dedupe_key": "fake:publication:success:one",
        "source_snapshot_ref": None,
    }
    return {**value, **overrides}


def test_record_normalizes_market_language_binds_metric_and_emits_safe_events() -> None:
    metric = active_metric()
    service = ObservationService(clock=lambda: NOW)
    created = service.record_observation(
        observation(), metric_definition=metric, context=context(), idempotency_key="record-one",
    )
    assert created["region"] == "US" and created["locale"] == "en-US"
    assert created["metric_definition_id"] == metric["id"]
    assert created["metric_name"] == metric["key"]
    assert created["observation_version"] == 1
    assert service.record_observation(
        observation(subject_id=created["subject_id"]), metric_definition=metric,
        context=context(), idempotency_key="record-one",
    ) == created
    assert [item["event_type"] for item in service.store.outbox] == [
        "observation.recorded", "analytics.publication.observed",
    ]
    assert all("metric_value" not in item["payload"] for item in service.store.outbox)
    assert "metric_value" not in service.store.audit[0]


def test_business_dedupe_and_revision_are_append_only_and_optimistically_locked() -> None:
    metric = active_metric()
    service = ObservationService(clock=lambda: NOW)
    subject = str(uuid4())
    first_input = observation(subject_id=subject)
    first = service.record_observation(
        first_input, metric_definition=metric, context=context(), idempotency_key="first",
    )
    assert service.record_observation(
        first_input, metric_definition=metric, context=context(), idempotency_key="same-other-key",
    ) == first
    with pytest.raises(AnalyticsError) as caught:
        service.record_observation(
            observation(subject_id=subject, metric_value=0.8), metric_definition=metric,
            context=context(), idempotency_key="conflict-current",
        )
    assert caught.value.code == "OBSERVATION_VERSION_CONFLICT"
    second = service.record_observation(
        observation(subject_id=subject, metric_value=0.8, observation_version=2),
        metric_definition=metric, context=context(), idempotency_key="second", expected_version=1,
    )
    assert second["observation_version"] == 2 and second["id"] != first["id"]
    assert [item["metric_value"] for item in service.list_observations(context=context(), dedupe_key=first["dedupe_key"])] == [0.75, 0.8]
    with pytest.raises(AnalyticsError) as caught:
        service.record_observation(
            observation(subject_id=subject, metric_value=0.9, observation_version=3),
            metric_definition=metric, context=context(), idempotency_key="stale", expected_version=1,
        )
    assert caught.value.code == "OPTIMISTIC_LOCK_CONFLICT"


def test_platform_is_account_gated_and_snapshot_sources_are_required() -> None:
    metric = active_metric()
    service = ObservationService(clock=lambda: NOW)
    live = observation(
        source="platform", source_snapshot_ref="private://analytics/platform/result.json",
        dedupe_key="platform:publication:one",
    )
    with pytest.raises(AnalyticsError) as caught:
        service.record_observation(live, metric_definition=metric, context=context(), idempotency_key="live-denied")
    assert caught.value.code == "EXT_ACCOUNT_UNAVAILABLE"
    created = service.record_observation(
        live, metric_definition=metric, context=context(), idempotency_key="live-verified",
        account_evidence={"org_id": ORG, "status": "verified", "evidence_ref": "vault-metadata://account/one"},
    )
    assert created["source"] == "platform"
    assert service.store.metadata(created["id"])["account_evidence_hash"]
    with pytest.raises(AnalyticsError) as caught:
        service.record_observation(
            observation(source="qa", subject_type="asset", source_snapshot_ref=None, dedupe_key="qa:asset:one"),
            metric_definition={**metric, "data_source": "analytics.qa.observed"},
            context=context(), idempotency_key="qa-no-snapshot",
        )
    assert caught.value.code == "SOURCE_SNAPSHOT_REQUIRED"


def test_metric_scope_status_value_schema_and_sensitive_value_are_enforced() -> None:
    metric = active_metric(
        key="publication.quality",
        metric_type="enum",
        quality_rules={"value_schema": {"enum": ["good", "bad"]}},
    )
    service = ObservationService(clock=lambda: NOW)
    with pytest.raises(AnalyticsError) as caught:
        service.record_observation(
            observation(metric_value="unknown", dedupe_key="enum:bad"),
            metric_definition=metric, context=context(), idempotency_key="enum-bad",
        )
    assert caught.value.code == "METRIC_VALUE_REJECTED"
    with pytest.raises(AnalyticsError) as caught:
        service.record_observation(
            observation(metric_value={"token": "private"}, dedupe_key="sensitive"),
            metric_definition={**metric, "metric_type": "json", "key": "publication.json", "quality_rules": {"value_schema": {"type": "object"}}},
            context=context(), idempotency_key="sensitive",
        )
    assert caught.value.code == "SENSITIVE_OBSERVATION_REJECTED"
    with pytest.raises(AnalyticsError) as caught:
        service.record_observation(
            observation(metric_value="good", dedupe_key="other-tenant"),
            metric_definition={**metric, "org_id": OTHER}, context=context(), idempotency_key="other-tenant",
        )
    assert caught.value.code == "TENANT_SCOPE_VIOLATION"
    with pytest.raises(AnalyticsError) as caught:
        service.record_observation(
            observation(metric_value="good", dedupe_key="draft"),
            metric_definition={**metric, "status": "draft"}, context=context(), idempotency_key="draft",
        )
    assert caught.value.code == "METRIC_DEFINITION_NOT_ACTIVE"


def test_get_rejects_cross_tenant_without_disclosing_value() -> None:
    metric = active_metric()
    service = ObservationService(clock=lambda: NOW)
    created = service.record_observation(
        observation(), metric_definition=metric, context=context(), idempotency_key="get-one",
    )
    assert service.get_observation(created["id"], context=context()) == created
    with pytest.raises(AnalyticsError) as caught:
        service.get_observation(created["id"], context=context(OTHER))
    assert caught.value.code == "TENANT_SCOPE_VIOLATION"


def test_explicit_uuid_is_preserved_under_the_same_dedupe_rules() -> None:
    metric = active_metric()
    service = ObservationService(clock=lambda: NOW)
    identity = str(uuid4())
    created = service.record_observation(
        observation(id=identity, dedupe_key="explicit:id:one"),
        metric_definition=metric, context=context(), idempotency_key="explicit-id",
    )
    assert created["id"] == identity
