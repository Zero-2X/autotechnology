from __future__ import annotations

from uuid import uuid4

import pytest

from modules.feedback.core import FeedbackRecommendationError, FeedbackRecommendationService


ORG = "00000000-0000-4000-8000-000000000001"
OTHER_ORG = "00000000-0000-4000-8000-000000000009"
ACTOR = "00000000-0000-4000-8000-000000000002"
SUBJECT = "00000000-0000-4000-8000-000000000003"
METRIC = "00000000-0000-4000-8000-000000000004"
SCORING = "00000000-0000-4000-8000-000000000005"
STAMP = "2026-09-19T00:00:00Z"


def _observation(*, source: str = "manual", metric_name: str = "stale_days",
                 metric_type: str = "number", metric_value=45, quality: str = "validated",
                 org_id: str = ORG, dedupe_key: str = "manual:stale:1") -> dict:
    return {
        "id": str(uuid4()), "org_id": org_id, "source": source, "subject_type": "content",
        "subject_id": SUBJECT, "metric_definition_id": METRIC, "metric_definition_version_no": 1,
        "metric_name": metric_name, "metric_type": metric_type, "metric_value": metric_value,
        "observed_at": STAMP, "locale": "en-US", "region": "US", "data_quality": quality,
        "dedupe_key": dedupe_key, "source_snapshot_ref": None, "observation_version": 1,
    }


def _scoring(*, org_id: str = ORG, active: bool = True) -> dict:
    return {
        "id": SCORING, "org_id": org_id, "version": 1, "algorithm": "threshold-v1",
        "weights": {"stale_days_threshold": 30, "priority_delta_threshold": 0.2},
        "active": active, "created_at": STAMP,
    }


def _record(service: FeedbackRecommendationService, *, key: str, observation: dict,
            scoring: dict | None = None) -> dict:
    return service.record_and_recommend(
        org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key=key,
        observation=observation, scoring_version=scoring or _scoring(),
    )


def test_manual_staleness_creates_explainable_refresh_proposal_without_action() -> None:
    service = FeedbackRecommendationService()
    result = _record(service, key="refresh", observation=_observation())

    assert result["feedback_item"]["recommendation_type"] == "refresh"
    assert result["feedback_item"]["status"] == "proposed"
    assert result["recommendation"]["status"] == "proposed"
    assert result["feedback_item"]["reasoning_snapshot"]["evidence"] == [
        "metric stale_days=45", "rule >= 30", "source manual with validated quality",
    ]
    assert [event["event_type"] for event in result["events"]] == [
        "observation.recorded", "feedback.recommendation_created",
    ]
    assert result["production_rules_mutated"] is False
    assert result["action_created"] is False


def test_fake_priority_delta_creates_reprioritize_and_estimated_quality_lowers_confidence() -> None:
    service = FeedbackRecommendationService()
    validated = _record(
        service, key="reprioritize-validated",
        observation=_observation(source="fake", metric_name="priority_score_delta", metric_value=-0.5,
                                 dedupe_key="fake:priority:validated"),
    )
    estimated = _record(
        service, key="reprioritize-estimated",
        observation=_observation(source="fake", metric_name="priority_score_delta", metric_value=-0.5,
                                 quality="estimated", dedupe_key="fake:priority:estimated"),
    )

    assert validated["recommendation"]["recommendation_type"] == "reprioritize"
    assert validated["feedback_item"]["reasoning_snapshot"]["comparison"] == "absolute_greater_or_equal"
    assert estimated["feedback_item"]["confidence"] < validated["feedback_item"]["confidence"]


def test_raw_or_nontriggering_observation_is_recorded_without_recommendation() -> None:
    service = FeedbackRecommendationService()
    raw = _record(service, key="raw", observation=_observation(quality="raw", dedupe_key="manual:raw"))
    fresh = _record(service, key="fresh", observation=_observation(metric_value=3, dedupe_key="manual:fresh"))

    for result in (raw, fresh):
        assert result["feedback_item"] is None and result["recommendation"] is None
        assert [event["event_type"] for event in result["events"]] == ["observation.recorded"]
        assert result["production_rules_mutated"] is False


def test_idempotency_dedupe_tenant_source_and_scoring_guards() -> None:
    service = FeedbackRecommendationService()
    observation = _observation()
    first = _record(service, key="same", observation=observation)
    assert _record(service, key="same", observation=observation) == first
    assert _record(service, key="same-observation-new-command", observation=observation) == first
    assert len(service.observations) == 1 and len(service.feedback_items) == 1

    with pytest.raises(FeedbackRecommendationError) as error:
        _record(service, key="same", observation={**observation, "metric_value": 90})
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"
    with pytest.raises(FeedbackRecommendationError) as error:
        _record(service, key="dedupe-conflict", observation={**observation, "id": str(uuid4()), "metric_value": 90})
    assert error.value.code == "OBSERVATION_DEDUPE_CONFLICT"
    with pytest.raises(FeedbackRecommendationError) as error:
        _record(service, key="foreign", observation=_observation(org_id=OTHER_ORG, dedupe_key="foreign"))
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    with pytest.raises(FeedbackRecommendationError) as error:
        _record(service, key="platform", observation=_observation(source="platform", dedupe_key="platform"))
    assert error.value.code == "SOURCE_NOT_ALLOWED"
    with pytest.raises(FeedbackRecommendationError) as error:
        _record(service, key="inactive", observation=_observation(dedupe_key="inactive"), scoring=_scoring(active=False))
    assert error.value.code == "SCORING_VERSION_INACTIVE"
