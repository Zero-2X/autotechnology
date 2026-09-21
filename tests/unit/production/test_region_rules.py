from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from modules.production import ProductionError, RegionRuleService


STAMP = datetime(2026, 9, 19, tzinfo=timezone.utc)


def _inputs():
    tenant, actor = str(uuid4()), str(uuid4())
    region = {
        "id": str(uuid4()), "org_id": tenant, "region_profile_id": str(uuid4()),
        "version_no": 1, "region_code": "US", "locales": ["en-US"],
        "timezone": "America/New_York", "units": "imperial", "currency": "USD",
        "data_residency": "US", "status": "active",
        "valid_from": "2026-09-01T00:00:00Z", "valid_to": "2026-10-01T00:00:00Z",
        "policy_snapshot_ref": "policy/us-v1",
        "disclosure_rules": [{"id": "ad-disclosure", "required": True}],
        "restricted_topics": [{"topic": "gambling", "markets": ["US"]}],
        "platform_eligibility": ["site"],
    }
    variant = {
        "id": str(uuid4()), "org_id": tenant, "canonical_content_version_id": str(uuid4()),
        "locale": "en-US", "market": "US", "title": "Guide",
        "blocks": [{"block_id": "intro", "localized_text": "Evidence based guide.", "disclosure": None}],
    }
    context = {"units": "imperial", "currency": "USD", "timezone": "America/New_York",
               "data_region": "US", "platform": "site", "disclosure": "ad-disclosure"}
    return tenant, actor, region, variant, context


def test_matching_region_is_eligible_and_schema_valid() -> None:
    tenant, actor, region, variant, context = _inputs()
    service = RegionRuleService()
    decision = service.evaluate(org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="check",
                                region_profile_version=region, variant=variant, context=context,
                                evaluated_at=STAMP)
    assert decision["status"] == "eligible"
    assert decision["matched_restrictions"] == []
    assert decision["required_disclosures"] == ["ad-disclosure"]
    schema = json.loads((Path(__file__).resolve().parents[3] /
                         "packages/contracts/jsonschema/region-rule-decision.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(decision)
    assert all(item["status"] == "pass" for item in decision["checks"])


def test_mismatched_locale_units_currency_timezone_and_platform_block() -> None:
    tenant, actor, region, variant, context = _inputs()
    context.update(units="metric", currency="EUR", timezone="Asia/Shanghai", platform="marketplace")
    variant["locale"] = "fr-FR"
    service = RegionRuleService()
    decision = service.evaluate(org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="mismatch",
                                region_profile_version=region, variant=variant, context=context,
                                evaluated_at=STAMP)
    assert decision["status"] == "blocked"
    assert {item["code"] for item in decision["checks"] if item["status"] == "fail"} >= {
        "LOCALE_ALLOWED", "UNITS_ALLOWED", "CURRENCY_ALLOWED", "TIMEZONE_ALLOWED", "PLATFORM_ELIGIBLE",
    }


def test_restricted_topic_and_missing_disclosure_block_without_leaking_foreign_data() -> None:
    tenant, actor, region, variant, context = _inputs()
    variant["blocks"][0]["localized_text"] = "A gambling guide."
    context["disclosure"] = ""
    service = RegionRuleService()
    decision = service.evaluate(org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="restricted",
                                region_profile_version=region, variant=variant, context=context,
                                evaluated_at=STAMP)
    assert decision["status"] == "blocked"
    assert decision["matched_restrictions"] == ["gambling"]
    assert {item["code"] for item in decision["checks"] if item["status"] == "fail"} >= {
        "RESTRICTED_TOPIC", "DISCLOSURE_REQUIRED",
    }
    foreign = deepcopy(region)
    foreign["org_id"] = str(uuid4())
    with pytest.raises(ProductionError) as error:
        service.evaluate(org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="foreign",
                         region_profile_version=foreign, variant=variant, context=context, evaluated_at=STAMP)
    assert error.value.code == "TENANT_SCOPE_VIOLATION"


def test_expiry_and_idempotency_are_deterministic() -> None:
    tenant, actor, region, variant, context = _inputs()
    service = RegionRuleService()
    first = service.evaluate(org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="same",
                             region_profile_version=region, variant=variant, context=context,
                             evaluated_at=STAMP)
    assert service.evaluate(org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="same",
                            region_profile_version=region, variant=variant, context=context,
                            evaluated_at=STAMP) == first
    with pytest.raises(ProductionError) as error:
        service.evaluate(org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="same",
                         region_profile_version=region, variant=variant,
                         context={**context, "currency": "EUR"}, evaluated_at=STAMP)
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"
    region["valid_to"] = "2026-09-10T00:00:00Z"
    expired = service.evaluate(org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="expired",
                               region_profile_version=region, variant=variant, context=context,
                               evaluated_at=STAMP)
    assert expired["status"] == "blocked"
    assert any(item["code"] == "REGION_IN_VALIDITY" for item in expired["checks"])
