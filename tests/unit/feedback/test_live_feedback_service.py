from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from modules.feedback.live import LiveFeedbackError, LiveFeedbackService
from modules.analytics import ObservationService


NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def _kwargs():
    org_id, actor_id = uuid4(), uuid4()
    return dict(
        org_id=org_id, actor_id=actor_id, trace_id="trace-live", idempotency_key="live-1",
        account_connection_id=uuid4(), platform_id=uuid4(), external_account_id="platform-account-1",
        publication_id=uuid4(), window_start=NOW, window_end=NOW + timedelta(hours=1),
        attribution={"external_object_id": "object-1", "attribution_type": "direct"},
        interactions={"views": 10, "clicks": 2}, platform_cost=35,
        lead_quality={"qualified": True, "converted": False, "score": 0.8},
        source_snapshot_ref="private://platform/snapshot-1",
        account_evidence={"org_id": str(org_id), "connection_id": "PLACEHOLDER", "status": "verified"},
        locale="en-US", region="US", now=NOW,
    )


def test_live_window_emits_four_platform_observations_and_replays():
    service = LiveFeedbackService(observation_service=ObservationService(), clock=lambda: NOW)
    kwargs = _kwargs()
    kwargs["account_evidence"]["connection_id"] = str(kwargs["account_connection_id"])
    result = service.ingest_platform_window(**kwargs)
    assert len(result["observations"]) == 4
    assert {item["source"] for item in result["observations"]} == {"platform"}
    assert result["side_effect_triggered"] is False
    assert result["window_start"].endswith("Z")
    replay = service.ingest_platform_window(**kwargs)
    assert replay == result
    assert len(service.audit) == 1


def test_live_feedback_requires_verified_account_and_bounded_inputs():
    service = LiveFeedbackService(observation_service=ObservationService(), clock=lambda: NOW)
    kwargs = _kwargs()
    kwargs["account_evidence"]["connection_id"] = str(kwargs["account_connection_id"])
    kwargs["account_evidence"]["status"] = "missing"
    with pytest.raises(LiveFeedbackError) as error:
        service.ingest_platform_window(**kwargs)
    assert error.value.code == "EXT_ACCOUNT_UNAVAILABLE"
    kwargs = _kwargs()
    kwargs["account_evidence"]["connection_id"] = str(kwargs["account_connection_id"])
    kwargs["interactions"] = {"raw_comments": 1}
    with pytest.raises(LiveFeedbackError) as error:
        service.ingest_platform_window(**kwargs)
    assert error.value.code == "INVALID_INTERACTIONS"
    kwargs = _kwargs()
    kwargs["account_evidence"]["connection_id"] = str(kwargs["account_connection_id"])
    kwargs["source_snapshot_ref"] = "https://platform.example/raw"
    with pytest.raises(LiveFeedbackError) as error:
        service.ingest_platform_window(**kwargs)
    assert error.value.code == "SOURCE_SNAPSHOT_REQUIRED"


def test_live_feedback_rejects_cross_tenant_evidence_and_invalid_window():
    service = LiveFeedbackService(observation_service=ObservationService(), clock=lambda: NOW)
    kwargs = _kwargs()
    kwargs["account_evidence"]["connection_id"] = str(kwargs["account_connection_id"])
    kwargs["account_evidence"]["org_id"] = str(uuid4())
    with pytest.raises(LiveFeedbackError) as error:
        service.ingest_platform_window(**kwargs)
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    kwargs = _kwargs()
    kwargs["account_evidence"]["connection_id"] = str(kwargs["account_connection_id"])
    kwargs["window_end"] = NOW
    with pytest.raises(LiveFeedbackError) as error:
        service.ingest_platform_window(**kwargs)
    assert error.value.code == "INVALID_INTERACTION_WINDOW"


@pytest.mark.parametrize("field", ["org_id", "connection_id"])
def test_live_feedback_rejects_unbound_evidence_without_writes(field):
    observations = ObservationService()
    service = LiveFeedbackService(observation_service=observations)
    kwargs = _kwargs()
    kwargs["account_evidence"]["connection_id"] = str(kwargs["account_connection_id"])
    del kwargs["account_evidence"][field]
    with pytest.raises(LiveFeedbackError) as error:
        service.ingest(**kwargs)
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    assert observations.store.audit == []
    assert service.audit == []


def test_partial_port_failure_recovers_through_canonical_idempotency():
    observations = ObservationService()

    class InterruptedPort:
        calls = 0

        def record_observation(self, **kwargs):
            self.calls += 1
            if self.calls == 3:
                raise ConnectionError("temporary observation-store failure")
            return observations.record_observation(**kwargs)

    service = LiveFeedbackService(observation_service=InterruptedPort())
    kwargs = _kwargs()
    kwargs["account_evidence"]["connection_id"] = str(kwargs["account_connection_id"])
    with pytest.raises(ConnectionError):
        service.ingest(**kwargs)
    assert not service.batches
    assert not service.audit
    result = service.ingest(**kwargs)
    assert len(result["observations"]) == 4
    assert len(observations.store.audit) == 4
    assert len(observations.store.outbox) == 8
    assert len(service.audit) == 1
    assert service.ingest(**kwargs) == result
    assert len(observations.store.outbox) == 8
