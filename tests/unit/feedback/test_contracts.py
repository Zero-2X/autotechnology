from datetime import datetime, timezone
from uuid import uuid4

import pytest

from modules.feedback.core import (
    ContractError,
    FeedbackItem,
    Observation,
    validate_observation,
    validate_scoring_version,
)


def test_observation_factory_enforces_metric_discriminator_and_serializes_contract() -> None:
    org_id = uuid4()
    subject_id = uuid4()
    definition_id = uuid4()
    observation = Observation.create(
        id=uuid4(), org_id=org_id, source="manual", subject_type="content", subject_id=subject_id,
        metric_definition_id=definition_id, metric_definition_version_no=1, metric_name="quality",
        metric_type="number", metric_value=0.9, observed_at=datetime(2026, 9, 18, tzinfo=timezone.utc),
        locale="zh-CN", region="CN", data_quality="validated", dedupe_key="manual:quality:1",
        source_snapshot_ref=None,
    )
    contract = observation.as_contract()
    assert contract["org_id"] == str(org_id)
    assert contract["observed_at"].endswith("+00:00")
    with pytest.raises(ContractError):
        Observation.create(
            id=uuid4(), org_id=org_id, source="manual", subject_type="content", subject_id=subject_id,
            metric_definition_id=definition_id, metric_definition_version_no=1, metric_name="quality",
            metric_type="number", metric_value="0.9", observed_at=contract["observed_at"], locale=None,
            region=None, data_quality="validated", dedupe_key="bad", source_snapshot_ref=None,
        )


def test_feedback_item_requires_tenant_scoped_observations_and_valid_status() -> None:
    target_id = uuid4()
    reasoning = {
        "rule_version": "feedback-core-002/v1", "scoring_version_id": str(uuid4()),
        "scoring_version": 1, "source": "manual", "metric_name": "stale_days",
        "metric_value": 45, "comparison": "greater_or_equal", "threshold": 30,
        "target_id": str(target_id), "evidence": ["metric stale_days=45", "rule >= 30"],
    }
    item = FeedbackItem.create(
        id=uuid4(), org_id=uuid4(), observation_ids=[uuid4()], problem="stale content",
        recommendation_type="refresh", impact="medium", priority="high", confidence=0.8,
        reasoning_snapshot=reasoning, owner_actor_id=None, due_at=None, approver_id=None,
        expires_at=None, created_action_id=None, status="proposed",
        created_at="2026-09-18T00:00:00+00:00",
    )
    assert item.as_contract()["status"] == "proposed"
    with pytest.raises(ContractError):
        FeedbackItem.create(
            id=uuid4(), org_id=uuid4(), observation_ids=[], problem="bad", recommendation_type="refresh",
            impact="medium", priority="high", confidence=1.1, reasoning_snapshot=reasoning, owner_actor_id=None,
            due_at=None, approver_id=None, expires_at=None, created_action_id=None, status="invalid",
            created_at="2026-09-18T00:00:00+00:00",
        )


def test_scoring_version_schema_is_explicit_and_validator_rejects_unknown_fields() -> None:
    record = {"id": str(uuid4()), "org_id": str(uuid4()), "version": 1, "algorithm": "weighted-v1",
              "weights": {"quality": 0.7, "freshness": 0.3}, "active": True,
              "created_at": "2026-09-18T00:00:00+00:00"}
    assert validate_scoring_version(record)["algorithm"] == "weighted-v1"
    with pytest.raises(ContractError):
        validate_observation({"unknown": True})
