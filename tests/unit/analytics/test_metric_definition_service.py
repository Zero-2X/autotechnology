from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from uuid import uuid4

import pytest

from modules.analytics import AnalyticsError, CanonicalEventCatalog, MetricDefinitionService


ORG = str(uuid4())
OTHER = str(uuid4())
ACTOR = str(uuid4())
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def context(org: str = ORG) -> dict[str, str]:
    return {"org_id": org, "actor_id": ACTOR, "trace_id": "analytics-test"}


def definition(**overrides):
    value = {
        "key": "publication.success_rate",
        "metric_type": "number",
        "unit": "ratio",
        "formula": "successful / attempted",
        "dimensions": ["market", "locale"],
        "window": "P7D",
        "data_source": "analytics.publication.observed",
        "dedupe_rule": "event_id",
        "quality_rules": {},
        "owner_actor_id": ACTOR,
    }
    return {**value, **overrides}


def event(category: str, *, source: str = "fake", subject_type: str = "publication") -> dict:
    identity = str(uuid4())
    payload = {
        "aggregate_id": identity,
        "aggregate_version": 1,
        "category": category,
        "observation_id": identity,
        "metric_definition_id": str(uuid4()),
        "metric_definition_version_no": 1,
        "source": source,
        "subject_type": subject_type,
        "subject_id": str(uuid4()),
        "observed_at": "2026-09-20T12:00:00Z",
        "data_quality": "estimated",
        "snapshot_hash": "a" * 64,
    }
    return {
        "event_id": str(uuid4()),
        "event_type": f"analytics.{category}.observed",
        "event_schema_version": 1,
        "occurred_at": "2026-09-20T12:00:00Z",
        "org_id": ORG,
        "trace_id": "analytics-test",
        "correlation_id": None,
        "causation_id": None,
        "aggregate_type": "Observation",
        "aggregate_id": identity,
        "aggregate_version": 1,
        "actor_type": "system",
        "actor_id": None,
        "idempotency_key": "event-one",
        "payload": payload,
        "payload_hash": sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
    }


def test_catalog_defines_all_nine_families_and_gates_platform_sources() -> None:
    catalog = CanonicalEventCatalog()
    assert {item["category"] for item in catalog.list_definitions()} == {
        "content", "asset", "publication", "interaction", "geo", "support", "qa", "cost", "risk"
    }
    assert catalog.validate_event(event("publication"))["payload"]["source"] == "fake"
    live = event("publication", source="platform")
    with pytest.raises(AnalyticsError) as caught:
        catalog.validate_event(live)
    assert caught.value.code == "EXT_ACCOUNT_UNAVAILABLE"
    assert catalog.validate_event(live, external_account_available=True) == live


def test_create_is_tenant_scoped_schema_valid_and_idempotent() -> None:
    service = MetricDefinitionService(clock=lambda: NOW)
    created = service.create_metric_definition(definition(), context=context(), idempotency_key="create-one")
    assert created["org_id"] == ORG
    assert created["version_no"] == 1
    assert created["status"] == "draft"
    assert len(created["snapshot_hash"]) == 64
    assert service.create_metric_definition(definition(), context=context(), idempotency_key="create-one") == created
    with pytest.raises(AnalyticsError) as caught:
        service.create_metric_definition(definition(unit="percent"), context=context(), idempotency_key="create-one")
    assert caught.value.code == "IDEMPOTENCY_KEY_REUSED"
    with pytest.raises(AnalyticsError) as caught:
        service.get_metric_definition(created["id"], context=context(OTHER))
    assert caught.value.code == "TENANT_SCOPE_VIOLATION"
    assert [item["event_type"] for item in service.store.outbox] == ["metric.definition.created"]


def test_lifecycle_requires_later_active_replacement_and_preserves_snapshot() -> None:
    service = MetricDefinitionService(clock=lambda: NOW)
    first = service.create_metric_definition(definition(), context=context(), idempotency_key="create-v1")
    active_first = service.activate_metric_definition(
        first["id"], context=context(), idempotency_key="activate-v1", expected_version=1
    )
    second = service.create_metric_definition(
        definition(formula="successful / max(attempted, 1)"),
        context=context(), idempotency_key="create-v2", expected_version=1,
    )
    with pytest.raises(AnalyticsError) as caught:
        service.retire_metric_definition(
            first["id"], replacement_definition_id=second["id"], context=context(),
            idempotency_key="retire-too-soon", expected_version=1,
        )
    assert caught.value.code == "METRIC_REPLACEMENT_INVALID"
    active_second = service.activate_metric_definition(
        second["id"], context=context(), idempotency_key="activate-v2", expected_version=2
    )
    retired = service.retire_metric_definition(
        first["id"], replacement_definition_id=active_second["id"], context=context(),
        idempotency_key="retire-v1", expected_version=1,
    )
    assert retired["status"] == "retired"
    assert retired["snapshot_hash"] == first["snapshot_hash"] == active_first["snapshot_hash"]
    assert second["version_no"] == 2
    assert [item["event_type"] for item in service.store.outbox] == [
        "metric.definition.created", "metric.definition.activated", "metric.definition.created",
        "metric.definition.activated", "metric.definition.retired",
    ]


def test_global_definition_needs_explicit_permission_and_is_visible_to_tenants() -> None:
    service = MetricDefinitionService(clock=lambda: NOW)
    with pytest.raises(AnalyticsError) as caught:
        service.create_metric_definition(
            definition(org_id=None), context=context(), idempotency_key="global-denied"
        )
    assert caught.value.code == "GLOBAL_CATALOG_FORBIDDEN"
    created = service.create_global_metric_definition(
        definition(org_id=None), context=context(), idempotency_key="global-created"
    )
    assert created["org_id"] is None
    assert service.get_metric_definition(created["id"], context=context(OTHER)) == created
    with pytest.raises(AnalyticsError) as caught:
        service.activate_metric_definition(
            created["id"], context=context(OTHER), idempotency_key="global-activate-denied", expected_version=1
        )
    assert caught.value.code == "GLOBAL_CATALOG_FORBIDDEN"
    active = service.activate_global_metric_definition(
        created["id"], context=context(), idempotency_key="global-activate", expected_version=1
    )
    assert active["status"] == "active"


def test_json_and_enum_definitions_require_self_contained_value_schema() -> None:
    service = MetricDefinitionService(clock=lambda: NOW)
    with pytest.raises(AnalyticsError):
        service.create_metric_definition(
            definition(metric_type="json"), context=context(), idempotency_key="json-invalid"
        )
    created = service.create_metric_definition(
        definition(
            key="qa.result",
            metric_type="enum",
            unit="state",
            quality_rules={"value_schema": {"enum": ["pass", "fail"]}},
        ),
        context=context(), idempotency_key="enum-valid",
    )
    assert created["metric_type"] == "enum"
