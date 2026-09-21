from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from modules.geo_content import (
    DeterministicComplianceSampler,
    GeoComplianceSamplingService,
    GeoQueryFixtureError,
    GeoQueryFixtureService,
)


STAMP = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


def _service() -> GeoQueryFixtureService:
    return GeoQueryFixtureService(clock=lambda: STAMP)


def _create(service: GeoQueryFixtureService, *, org_id=None, key="create", **kwargs):
    return service.create_fixture(
        org_id=org_id or uuid4(),
        actor_id=uuid4(),
        trace_id="trace-fixture",
        idempotency_key=key,
        query="Where can I learn about Acme?",
        locale="en-US",
        region="US",
        expected_entities=["Acme"],
        expected_claim_ids=[],
        **kwargs,
    )


def test_create_is_tenant_scoped_and_idempotent_across_clock_and_trace() -> None:
    service = _service()
    org_id = uuid4()
    first = _create(service, org_id=org_id)
    replay = service.create_fixture(
        org_id=org_id,
        actor_id=uuid4(),
        trace_id="different-trace",
        idempotency_key="create",
        query=first["query"],
        locale=first["locale"],
        region=first["region"],
        expected_entities=first["expected_entities"],
        expected_claim_ids=[],
    )
    assert replay == first
    assert len(service.store.fixture_versions[(str(org_id), first["id"])]) == 1


def test_idempotency_conflict_and_cross_tenant_read_are_rejected() -> None:
    service = _service()
    org_id = uuid4()
    first = _create(service, org_id=org_id)
    with pytest.raises(GeoQueryFixtureError) as conflict:
        service.create_fixture(
            org_id=org_id,
            actor_id=uuid4(),
            trace_id="trace",
            idempotency_key="create",
            query="different",
            locale="en-US",
            region="US",
            expected_entities=["Acme"],
            expected_claim_ids=[],
        )
    assert conflict.value.code == "IDEMPOTENCY_KEY_REUSED"
    with pytest.raises(GeoQueryFixtureError) as cross:
        service.get_fixture(org_id=uuid4(), fixture_id=first["id"])
    assert cross.value.code == "TENANT_SCOPE_VIOLATION"


def test_state_transitions_are_append_only_and_if_match_replays() -> None:
    service = _service()
    org_id = uuid4()
    first = _create(service, org_id=org_id)
    active = service.activate_fixture(
        org_id=org_id, fixture_id=first["id"], actor_id=uuid4(), trace_id="a",
        idempotency_key="activate", expected_version=1,
    )
    replay = service.activate_fixture(
        org_id=org_id, fixture_id=first["id"], actor_id=uuid4(), trace_id="other",
        idempotency_key="activate", expected_version=1,
    )
    assert active == replay
    retired = service.retire_fixture(
        org_id=org_id, fixture_id=first["id"], actor_id=uuid4(), trace_id="r",
        idempotency_key="retire", if_match='"2"', reason="replaced",
    )
    assert retired["status"] == "retired"
    assert [row["status"] for row in service.store.fixture_versions[(str(org_id), first["id"])]] == ["created", "active", "retired"]
    assert {event["event_type"] for event in service.store.events} == {"geo.fixture.activated", "geo.fixture.retired"}
    with pytest.raises(GeoQueryFixtureError) as stale:
        service.retire_fixture(
            org_id=org_id, fixture_id=first["id"], actor_id=uuid4(), trace_id="stale",
            idempotency_key="stale", expected_version=2,
        )
    assert stale.value.code == "VERSION_CONFLICT"


def test_predecessor_tenant_and_readiness_are_fail_closed() -> None:
    service = _service()
    org_id = uuid4()
    with pytest.raises(GeoQueryFixtureError) as cross:
        _create(service, org_id=org_id, predecessor_artifacts={"site_page": {"org_id": str(uuid4()), "status": "published"}})
    assert cross.value.code == "TENANT_SCOPE_VIOLATION"
    with pytest.raises(GeoQueryFixtureError) as pending:
        _create(service, org_id=org_id, predecessor_artifacts={"site_page": {"org_id": str(org_id), "status": "pending"}})
    assert pending.value.code == "PREDECESSOR_NOT_READY"
    ready = _create(
        service,
        org_id=org_id,
        key="completed",
        predecessor_artifacts={"site_page": {"org_id": str(org_id), "status": "completed"}},
    )
    assert ready["status"] == "created"
    with pytest.raises(GeoQueryFixtureError) as deeply_nested:
        _create(
            service,
            org_id=org_id,
            key="nested-cross-tenant",
            predecessor_artifacts={
                "sources": [[{"org_id": str(uuid4()), "status": "done"}]],
            },
        )
    assert deeply_nested.value.code == "TENANT_SCOPE_VIOLATION"


def test_sampling_records_mentions_citations_position_correctness_and_unknown_review() -> None:
    fixture_service = _service()
    org_id = uuid4()
    fixture = _create(fixture_service, org_id=org_id)
    fixture = fixture_service.activate_fixture(
        org_id=org_id, fixture_id=fixture["id"], actor_id=uuid4(), trace_id="a",
        idempotency_key="activate", expected_version=1,
    )
    sampling = GeoComplianceSamplingService(fixture_service=fixture_service, sampler=DeterministicComplianceSampler())
    result = sampling.sample(
        org_id=org_id, fixture_id=fixture["id"], actor_id=uuid4(), trace_id="sample",
        idempotency_key="sample", page_version_id=str(uuid4()),
        result={"answer": "Acme is documented here", "citations": [{"url": "https://example.test/a", "position": 3}]},
    )
    assert result["mentioned"] is True
    assert result["mention_count"] == 1
    assert result["citation_count"] == 1
    assert result["position"] == 3
    assert result["correctness"] == "correct"
    unknown = sampling.sample(
        org_id=org_id, fixture_id=fixture["id"], actor_id=uuid4(), trace_id="unknown",
        idempotency_key="unknown", result={"status": "unknown"},
    )
    assert unknown["status"] == "manual_review"
    assert unknown["unknown_external_result"] is True
    assert any(row["event_type"] == "geo.sample.manual_review" for row in fixture_service.store.audit)


def test_retire_requires_reason_and_does_not_mutate_on_rejection() -> None:
    service = _service()
    org_id = uuid4()
    fixture = _create(service, org_id=org_id)
    active = service.activate_fixture(
        org_id=org_id, fixture_id=fixture["id"], actor_id=uuid4(), trace_id="a",
        idempotency_key="activate", expected_version=1,
    )
    with pytest.raises(GeoQueryFixtureError) as missing:
        service.retire_fixture(
            org_id=org_id, fixture_id=fixture["id"], actor_id=uuid4(), trace_id="r",
            idempotency_key="retire-missing", expected_version=active["version"],
        )
    assert missing.value.code == "REASON_REQUIRED"
    assert service.get_fixture(org_id=org_id, fixture_id=fixture["id"])["status"] == "active"
    assert len(service.store.fixture_versions[(str(org_id), fixture["id"])]) == 2


def test_invalid_transition_is_audited_for_context_only_tenant() -> None:
    service = _service()
    org_id = uuid4()
    with pytest.raises(GeoQueryFixtureError) as invalid:
        service.transition(
            action="unknown", tenant_context={"org_id": str(org_id)},
            actor_id=uuid4(), trace_id="bad-action", idempotency_key="bad-action",
        )
    assert invalid.value.code == "INVALID_STATE_TRANSITION"
    rejected = service.audit_for(org_id=org_id)
    assert rejected[-1]["org_id"] == str(org_id)
    assert rejected[-1]["event_type"] == "geo.fixture.rejected"


def test_create_transition_and_sample_can_reuse_an_idempotency_key() -> None:
    fixture_service = _service()
    org_id = uuid4()
    fixture = _create(fixture_service, org_id=org_id, key="shared")
    active = fixture_service.activate_fixture(
        org_id=org_id, fixture_id=fixture["id"], actor_id=uuid4(), trace_id="a",
        idempotency_key="shared", expected_version=1,
    )
    sampling = GeoComplianceSamplingService(fixture_service=fixture_service)
    result = sampling.sample(
        org_id=org_id, fixture_id=active["id"], actor_id=uuid4(), trace_id="s",
        idempotency_key="shared", result={"status": "manual_review", "answer": "Acme"},
    )
    assert result["status"] == "manual_review"


def test_sampling_rejects_tampered_direct_fixture_and_explicit_review_state() -> None:
    fixture_service = _service()
    org_id = uuid4()
    fixture = _create(fixture_service, org_id=org_id)
    fixture = fixture_service.activate_fixture(
        org_id=org_id, fixture_id=fixture["id"], actor_id=uuid4(), trace_id="a",
        idempotency_key="activate", expected_version=1,
    )
    sampling = GeoComplianceSamplingService(fixture_service=fixture_service)
    tampered = dict(fixture, query="changed", prompt="changed")
    with pytest.raises(GeoQueryFixtureError) as invalid:
        sampling.sample(
            org_id=org_id, fixture=tampered, actor_id=uuid4(), trace_id="tampered",
            idempotency_key="tampered", result={"answer": "Acme"},
        )
    assert invalid.value.code == "INVALID_GEO_SAMPLE"
    review = sampling.sample(
        org_id=org_id, fixture_id=fixture["id"], actor_id=uuid4(), trace_id="review",
        idempotency_key="review", result={"status": "manual_review", "answer": "Acme"},
    )
    assert review["status"] == "manual_review"


def test_sampling_rejects_adapter_output_bound_to_another_fixture_hash() -> None:
    fixture_service = _service()
    org_id = uuid4()
    fixture = _create(fixture_service, org_id=org_id)
    fixture = fixture_service.activate_fixture(
        org_id=org_id, fixture_id=fixture["id"], actor_id=uuid4(), trace_id="a",
        idempotency_key="activate", expected_version=1,
    )

    class TamperedSampler(DeterministicComplianceSampler):
        def sample(self, **kwargs):
            value = dict(super().sample(**kwargs))
            value["fixture_hash"] = "f" * 64
            return value

    sampling = GeoComplianceSamplingService(
        fixture_service=fixture_service,
        sampler=TamperedSampler(),
    )
    with pytest.raises(GeoQueryFixtureError) as invalid:
        sampling.sample(
            tenant_context={"org_id": str(org_id)}, fixture_id=fixture["id"],
            actor_id=uuid4(), trace_id="tampered-port", idempotency_key="tampered-port",
            result={"answer": "Acme"},
        )
    assert invalid.value.code == "INVALID_GEO_SAMPLE"
    rejected = fixture_service.audit_for(org_id=org_id)
    assert rejected[-1]["event_type"] == "geo.sample.rejected"
    assert rejected[-1]["org_id"] == str(org_id)


def test_sampling_adapter_failure_is_redacted_and_audited() -> None:
    fixture_service = _service()
    org_id = uuid4()
    fixture = _create(fixture_service, org_id=org_id)
    fixture = fixture_service.activate_fixture(
        org_id=org_id, fixture_id=fixture["id"], actor_id=uuid4(), trace_id="a",
        idempotency_key="activate", expected_version=1,
    )

    class BrokenSampler(DeterministicComplianceSampler):
        def sample(self, **kwargs):
            raise RuntimeError("provider token=must-not-leak")

    sampling = GeoComplianceSamplingService(
        fixture_service=fixture_service,
        sampler=BrokenSampler(),
    )
    with pytest.raises(GeoQueryFixtureError) as failed:
        sampling.sample(
            org_id=org_id, fixture_id=fixture["id"], actor_id=uuid4(), trace_id="broken",
            idempotency_key="broken", result={"answer": "Acme"},
        )
    assert failed.value.code == "SAMPLING_PORT_FAILED"
    audit = fixture_service.audit_for(org_id=org_id)[-1]
    assert audit["event_type"] == "geo.sample.rejected"
    assert "must-not-leak" not in (audit["reason"] or "")


def test_explicit_unknown_correctness_sets_the_unknown_flag() -> None:
    fixture_service = _service()
    org_id = uuid4()
    fixture = _create(fixture_service, org_id=org_id)
    fixture = fixture_service.activate_fixture(
        org_id=org_id, fixture_id=fixture["id"], actor_id=uuid4(), trace_id="a",
        idempotency_key="activate", expected_version=1,
    )
    result = GeoComplianceSamplingService(fixture_service=fixture_service).sample(
        org_id=org_id,
        fixture_id=fixture["id"],
        idempotency_key="unknown-correctness",
        result={"answer": "Acme", "correctness": "unknown"},
    )
    assert result["status"] == "manual_review"
    assert result["unknown_external_result"] is True
    assert result["review_required"] is True
