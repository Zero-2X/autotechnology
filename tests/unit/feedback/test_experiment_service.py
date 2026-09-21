from uuid import uuid4

import pytest

from modules.feedback.exp import ExperimentError, ExperimentService


ORG, ACTOR = str(uuid4()), str(uuid4())
CTX = {"org_id": ORG, "actor_id": ACTOR, "trace_id": "experiment"}


def make(service=None):
    service = service or ExperimentService()
    return service.create_experiment(hypothesis="variant improves correctness", groups=[{"key": "control", "label": "Control", "allocation_percent": 50}, {"key": "treatment", "label": "Treatment", "allocation_percent": 50}], metric_keys=["answer.correct", "cost.cents"], window_start="2026-09-21T00:00:00Z", window_end="2026-09-28T00:00:00Z", sample_target=2, context=CTX, idempotency_key="create-exp")


def test_experiment_lifecycle_samples_conclusion_and_rollback():
    service = ExperimentService(); experiment = make(service)
    running = service.start(experiment["id"], context=CTX, idempotency_key="start", expected_version=1)
    sample = service.record_sample(experiment["id"], group_key="control", metrics={"answer.correct": 1, "cost.cents": 2}, observation_ids=[str(uuid4())], source="manual", context=CTX, idempotency_key="sample")
    assert running["status"] == "running" and sample["source"] == "manual"
    concluded = service.conclude(experiment["id"], winner="control", summary="control passed threshold", metric_results={"answer.correct": {"value": 1}}, context=CTX, idempotency_key="conclude", expected_version=2)
    assert concluded["status"] == "concluded" and concluded["conclusion"]["winner"] == "control"
    rolled = service.rollback(experiment["id"], reason="post hoc safety review", context=CTX, idempotency_key="rollback", expected_version=3)
    assert rolled["status"] == "rolled_back" and rolled["rollback_reason"]


def test_account_free_source_and_idempotency_guards():
    service = ExperimentService(); experiment = make(service); service.start(experiment["id"], context=CTX, idempotency_key="start", expected_version=1)
    with pytest.raises(ExperimentError) as error:
        service.record_sample(experiment["id"], group_key="control", metrics={"x": 1}, observation_ids=[], source="platform", context=CTX, idempotency_key="platform")
    assert error.value.code == "SOURCE_NOT_ALLOWED"
    with pytest.raises(ExperimentError) as error:
        service.record_sample(experiment["id"], group_key="unknown", metrics={"x": 1}, observation_ids=[], source="manual", context=CTX, idempotency_key="unknown")
    assert error.value.code == "INVALID_EXPERIMENT_INPUT"
    with pytest.raises(ExperimentError) as error:
        service.start(experiment["id"], context=CTX, idempotency_key="stale", expected_version=1)
    assert error.value.code == "OPTIMISTIC_LOCK_CONFLICT"
