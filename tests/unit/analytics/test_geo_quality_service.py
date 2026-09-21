from uuid import uuid4

import pytest

from modules.analytics import GeoQualityError, GeoQualityService


ORG = str(uuid4())
CTX = {"org_id": ORG, "actor_id": str(uuid4()), "trace_id": "geo-quality-test"}


def observation(name, value, *, version=1, dedupe=None, quality="validated", locale="en-US", region="US", source="fake"):
    return {
        "id": str(uuid4()), "org_id": ORG, "source": source, "subject_type": "geo_run", "subject_id": str(uuid4()),
        "metric_definition_id": str(uuid4()), "metric_definition_version_no": 1, "metric_name": name,
        "metric_type": "boolean" if isinstance(value, bool) else "enum", "metric_value": value, "observed_at": "2026-09-21T12:00:00Z",
        "locale": locale, "region": region, "data_quality": quality, "dedupe_key": dedupe or str(uuid4()),
        "source_snapshot_ref": None, "observation_version": version,
    }


def calculate(rows, key="one", **kwargs):
    return GeoQualityService().calculate_snapshot(
        rows, context=CTX, idempotency_key=key,
        window_start="2026-09-21T00:00:00Z", window_end="2026-09-22T00:00:00Z", **kwargs,
    )


def test_content_and_region_are_separate_and_quality_is_explicit():
    result = calculate([
        observation("geo.content.mentioned", True),
        observation("geo.content.cited", False, quality="estimated"),
        observation("geo.region.compliant", True),
        observation("geo.region.restricted", True),
        observation("geo.region.allowed", "unknown"),
    ])
    assert result["status"] == "needs_review"
    assert result["content"]["metric_counts"]["mentioned"]["value"] == 1
    assert result["region_quality"]["metric_counts"]["compliant"]["value"] == 1
    assert result["region_quality"]["metric_counts"]["restricted"]["value"] == 1
    assert any(item["code"] == "UNKNOWN_VALUE_EXCLUDED" for item in result["quality_issues"])
    assert any(item["code"] == "ESTIMATED_INPUT_PRESENT" for item in result["quality_issues"])


def test_latest_revision_is_selected_before_window_and_dimension_aggregation():
    key = "same"
    old = observation("geo.content.mentioned", True, dedupe=key, version=1)
    new = {**old, "id": str(uuid4()), "observation_version": 2, "metric_value": False,
           "observed_at": "2026-09-22T00:00:00Z"}
    with pytest.raises(GeoQualityError) as error:
        calculate([old, new])
    assert error.value.code == "GEO_QUALITY_NO_SUPPORTED_INPUT"


def test_platform_and_tenant_idempotency_gates():
    row = observation("geo.content.correct", True, source="platform")
    with pytest.raises(GeoQualityError) as error:
        calculate([row])
    assert error.value.code == "EXT_ACCOUNT_UNAVAILABLE"
    service = GeoQualityService()
    first = service.calculate_snapshot([observation("geo.content.correct", True)], context=CTX,
                                       idempotency_key="same", window_start="2026-09-21T00:00:00Z", window_end="2026-09-22T00:00:00Z")
    with pytest.raises(GeoQualityError) as error:
        service.calculate_snapshot([observation("geo.content.correct", False)], context=CTX,
                                   idempotency_key="same", window_start="2026-09-21T00:00:00Z", window_end="2026-09-22T00:00:00Z")
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"
    assert service.get_snapshot(first["id"], context=CTX) == first


def test_cross_tenant_and_no_supported_input_rejected():
    with pytest.raises(GeoQualityError) as error:
        calculate([{**observation("geo.content.correct", True), "org_id": str(uuid4())}])
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    with pytest.raises(GeoQualityError) as error:
        calculate([observation("publication.success", True)])
    assert error.value.code == "GEO_QUALITY_NO_SUPPORTED_INPUT"
