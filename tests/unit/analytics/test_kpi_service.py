from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from modules.analytics import AnalyticsError, AnalyticsKpiService


ORG = str(uuid4())
CTX = {"org_id": ORG, "actor_id": str(uuid4()), "trace_id": "kpi-test"}
WINDOW = {"window_start": "2026-09-20T00:00:00Z", "window_end": "2026-09-21T00:00:00Z"}


def observation(name, value, kind=None, **changes):
    return {
        "id": str(uuid4()), "org_id": ORG, "source": "fake",
        "subject_type": "publication", "subject_id": str(uuid4()),
        "metric_definition_id": str(uuid4()), "metric_definition_version_no": 1,
        "metric_name": name, "metric_type": kind or ("boolean" if isinstance(value, bool) else "number"),
        "metric_value": value, "observed_at": "2026-09-20T12:00:00Z",
        "locale": "en-US", "region": "US", "data_quality": "validated",
        "dedupe_key": str(uuid4()), "source_snapshot_ref": None, "observation_version": 1,
        **changes,
    }


def calculate(service, rows, key="one", **kwargs):
    return service.calculate_snapshot(rows, context=CTX, idempotency_key=key, **WINDOW, **kwargs)


def test_seven_metrics_have_explicit_denominators_and_exact_costs():
    rows = [
        observation("publication.outcome", "published", "enum"),
        observation("publication.outcome", "failed", "enum"),
        observation("publication.outcome", "unknown", "enum"),
        observation("workflow.manual_intervention", True),
        observation("rights.rejected", False),
        observation("translation.passed", True),
        observation("answer.incorrect", False),
        observation("cost.cents", 10.1), observation("cost.cents", 20.2),
        observation("lead.attribution", {"channel": "website", "attributed": True, "qualified": True, "value_cents": 120}, "json"),
    ]
    result = calculate(AnalyticsKpiService(), rows)
    metrics = result["metrics"]
    assert result["status"] == "complete"
    assert metrics["publication_success_rate"] == {"numerator": 1, "denominator": 2, "value": .5}
    assert metrics["cost"] == {"total_cents": 30.3, "sample_count": 2, "average_cents": 15.15}
    assert metrics["lead_attribution"]["by_channel"] == {"website": 1}
    assert any(issue["code"] == "PUBLICATION_UNKNOWN_EXCLUDED" for issue in result["quality_issues"])


def test_repeated_snapshot_reuses_original_even_after_clock_and_actor_change():
    now = datetime(2026, 9, 20, 13, tzinfo=timezone.utc)
    service = AnalyticsKpiService(clock=lambda: now)
    rows = [observation("publication.success", True)]
    first = calculate(service, rows)
    now += timedelta(hours=1)
    assert calculate(service, rows, "different-command") == first
    assert len(service.store.outbox) == 1
    assert first["metrics"]["translation_pass_rate"]["value"] is None


def test_latest_revision_is_selected_before_window_filtering():
    first = observation("publication.success", True)
    revised = {**first, "id": str(uuid4()), "observation_version": 2, "observed_at": WINDOW["window_end"]}
    remaining = observation("publication.success", False)
    result = calculate(AnalyticsKpiService(), [first, revised, remaining])
    assert result["input_observation_ids"] == [remaining["id"]]
    assert result["metrics"]["publication_success_rate"]["value"] == 0


def test_quality_affecting_inputs_are_part_of_command_identity():
    service = AnalyticsKpiService()
    rows = [observation("publication.success", True)]
    calculate(service, rows)
    with pytest.raises(AnalyticsError) as error:
        calculate(service, rows + [observation("unknown.metric", 1)])
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1])
def test_invalid_costs_are_rejected(value):
    with pytest.raises(AnalyticsError):
        calculate(AnalyticsKpiService(), [observation("cost.cents", value)])


def test_cross_tenant_and_changed_revision_identity_are_rejected():
    first = observation("publication.success", True)
    changed = {**first, "id": str(uuid4()), "observation_version": 2, "subject_id": str(uuid4())}
    for rows, code in [([first, changed], "KPI_INPUT_CONFLICT"),
                       ([{**first, "org_id": str(uuid4())}], "TENANT_SCOPE_VIOLATION")]:
        with pytest.raises(AnalyticsError) as error:
            calculate(AnalyticsKpiService(), rows)
        assert error.value.code == code


def test_platform_inputs_require_account_evidence():
    row = observation("publication.success", True, source="platform")
    with pytest.raises(AnalyticsError) as error:
        calculate(AnalyticsKpiService(), [row])
    assert error.value.code == "EXT_ACCOUNT_UNAVAILABLE"
