from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from modules.geo_content import (
    DeterministicComplianceSampler,
    FakeGeo,
    GeoQueryFixtureService,
    GeoRunError,
    GeoRunService,
)


STAMP = datetime(2026, 9, 20, 8, 0, tzinfo=timezone.utc)


def _active_fixture(*, org_id=None, clock=None):
    tenant = org_id or uuid4()
    service = GeoQueryFixtureService(clock=clock or (lambda: STAMP))
    fixture = service.create_fixture(
        org_id=tenant,
        actor_id=uuid4(),
        trace_id="fixture-create",
        idempotency_key="fixture-create",
        query="Where is Acme documented?",
        locale="en-US",
        region="US",
        expected_entities=["Acme"],
        expected_claim_ids=[],
    )
    fixture = service.activate_fixture(
        org_id=tenant,
        actor_id=uuid4(),
        trace_id="fixture-activate",
        idempotency_key="fixture-activate",
        fixture_id=fixture["id"],
        expected_version=1,
    )
    return tenant, service, fixture


def _run(service: GeoRunService, tenant, fixture, *, key="run", answers=None, **kwargs):
    return service.run(
        org_id=tenant,
        actor_id=uuid4(),
        trace_id="geo-run",
        idempotency_key=key,
        page_version_id=kwargs.pop("page_version_id", uuid4()),
        query_fixture_id=fixture["id"],
        locale="en-US",
        region="US",
        sample_count=kwargs.pop("sample_count", len(answers) if answers is not None else 2),
        answers=answers,
        **kwargs,
    )


def test_multi_sample_run_deduplicates_and_aggregates_deterministically() -> None:
    tenant, fixtures, fixture = _active_fixture()
    service = GeoRunService(fixture_service=fixtures, clock=lambda: STAMP)
    cited = {
        "answer": "Acme is documented here.",
        "citations": [{"url": "https://example.test/acme", "position": 2}],
        "correctness": "correct",
    }
    page_id = uuid4()
    value = _run(
        service,
        tenant,
        fixture,
        answers=[cited, {"answer": "Another company", "correctness": "incorrect"}, cited],
        page_version_id=page_id,
    )
    assert value == {
        "id": value["id"],
        "org_id": str(tenant),
        "page_version_id": str(page_id),
        "query_fixture_id": fixture["id"],
        "locale": "en-US",
        "region": "US",
        "sample_count": 3,
        "parser_version": "geo-compliance-002.v1",
        "mention_count": 1,
        "citation_count": 1,
        "position_values": [2],
        "correctness_values": ["correct", "incorrect"],
        "confidence": 0.333333,
        "data_quality": "estimated",
        "fixture_hash": fixture["fixture_hash"],
        "status": "succeeded",
        "created_at": "2026-09-20T08:00:00.000000Z",
    }
    # Captured answer bodies are never persisted.  Only observation digests
    # and stable parser facts are retained for the three attempts.
    assert len(service.store.observations) == 3
    assert "Acme is documented here" not in repr(service.store.__dict__)
    assert service.audit_for(org_id=tenant)[-1]["event_type"] == "geo.run.completed"


def test_duplicate_samples_do_not_inflate_counts_and_reduce_confidence() -> None:
    tenant, fixtures, fixture = _active_fixture()
    service = GeoRunService(fixture_service=fixtures, clock=lambda: STAMP)
    answer = {
        "answer": "Acme",
        "citations": [{"url": "https://example.test", "position": 1}],
        "correctness": True,
    }
    value = _run(service, tenant, fixture, answers=[answer, answer, answer])
    assert value["mention_count"] == 1
    assert value["citation_count"] == 1
    assert value["position_values"] == [1]
    assert value["confidence"] == 0.333333


def test_unknown_samples_fail_closed_and_emit_manual_review_audit() -> None:
    tenant, fixtures, fixture = _active_fixture()
    service = GeoRunService(fixture_service=fixtures, clock=lambda: STAMP)
    value = _run(
        service,
        tenant,
        fixture,
        answers=[{"status": "unknown"}, {"status": "pending"}],
    )
    assert value["status"] == "failed"
    assert value["correctness_values"] == ["unknown"]
    assert value["confidence"] == 0.0
    audit = service.audit_for(org_id=tenant)[-1]
    assert audit["event_type"] == "geo.run.manual_review"
    assert audit["status"] == "failed"


def test_replay_is_stable_across_clock_actor_trace_and_idempotency_keys() -> None:
    now = [STAMP]
    tenant, fixtures, fixture = _active_fixture(clock=lambda: now[0])
    service = GeoRunService(fixture_service=fixtures, clock=lambda: now[0])
    page_id = uuid4()
    answers = [{"answer": "Acme", "correctness": "correct"}, {"answer": "Other", "correctness": "incorrect"}]
    first = _run(service, tenant, fixture, key="first", page_version_id=page_id, answers=answers)
    now[0] += timedelta(days=1)
    same_key = service.run(
        tenant_context={"org_id": str(tenant), "actor_id": str(uuid4()), "trace_id": "changed"},
        idempotency_key="first",
        page_version_id=str(page_id),
        fixture_id=fixture["id"],
        locale="en-US",
        region="US",
        sample_count=2,
        answer_fixture={"answers": answers, "fixture_hash": fixture["fixture_hash"]},
    )
    other_key = _run(
        service,
        tenant,
        fixture,
        key="second",
        page_version_id=page_id,
        answers=answers,
    )
    assert same_key == first
    assert other_key == first
    assert len(service.store.runs) == 1
    assert len(service.store.audit) == 1


def test_same_key_replays_after_fixture_is_retired() -> None:
    tenant, fixtures, fixture = _active_fixture()
    service = GeoRunService(fixture_service=fixtures, clock=lambda: STAMP)
    page_id = uuid4()
    answers = ["Acme", "Other"]
    first = _run(
        service,
        tenant,
        fixture,
        key="stable-after-retire",
        page_version_id=page_id,
        answers=answers,
    )
    fixtures.retire_fixture(
        org_id=tenant,
        fixture_id=fixture["id"],
        idempotency_key="retire",
        expected_version=fixture["version"],
        reason="fixture replaced",
    )
    replay = _run(
        service,
        tenant,
        fixture,
        key="stable-after-retire",
        page_version_id=page_id,
        answers=answers,
    )
    assert replay == first
    with pytest.raises(GeoRunError) as changed:
        _run(
            service,
            tenant,
            fixture,
            key="stable-after-retire",
            page_version_id=page_id,
            answers=["Acme changed", "Other"],
        )
    assert changed.value.code == "IDEMPOTENCY_KEY_REUSED"


def test_idempotency_key_conflict_is_rejected_and_audited() -> None:
    tenant, fixtures, fixture = _active_fixture()
    service = GeoRunService(fixture_service=fixtures, clock=lambda: STAMP)
    page_id = uuid4()
    _run(service, tenant, fixture, key="same", page_version_id=page_id, answers=["Acme", "Other"])
    with pytest.raises(GeoRunError) as conflict:
        _run(
            service,
            tenant,
            fixture,
            key="same",
            page_version_id=page_id,
            answers=["Acme changed", "Other"],
        )
    assert conflict.value.code == "IDEMPOTENCY_KEY_REUSED"
    rejected = service.audit_for(org_id=tenant)[-1]
    assert rejected["event_type"] == "geo.run.rejected"
    assert rejected["input_hash"] is not None
    assert rejected["input_version"] == fixture["version"]


@pytest.mark.parametrize("count", [None, True, 1, 101, 2.0])
def test_sample_count_is_a_bounded_integer(count) -> None:
    tenant, fixtures, fixture = _active_fixture()
    service = GeoRunService(fixture_service=fixtures, clock=lambda: STAMP)
    with pytest.raises(GeoRunError) as invalid:
        _run(service, tenant, fixture, answers=["Acme", "Other"], sample_count=count)
    assert invalid.value.code == "INVALID_SAMPLE_COUNT"


def test_answer_fixture_must_be_unambiguous_sufficient_and_bound() -> None:
    tenant, fixtures, fixture = _active_fixture()
    service = GeoRunService(fixture_service=fixtures, clock=lambda: STAMP)
    base = {
        "org_id": tenant,
        "actor_id": uuid4(),
        "trace_id": "answer-fixture",
        "page_version_id": uuid4(),
        "query_fixture_id": fixture["id"],
        "locale": "en-US",
        "region": "US",
        "sample_count": 2,
    }
    cases = [
        ({"answers": ["one"], "fixture_hash": fixture["fixture_hash"]}, "INSUFFICIENT_ANSWER_SAMPLES"),
        ({"answers": ["one", "two"], "results": ["one", "two"]}, "AMBIGUOUS_ANSWER_FIXTURE"),
        ({"answers": ["one", "two"], "fixture_hash": "f" * 64}, "ANSWER_FIXTURE_MISMATCH"),
        ({"org_id": str(uuid4()), "answers": ["one", "two"]}, "TENANT_SCOPE_VIOLATION"),
        ({"answers": [{"nested": {"tenant_id": str(uuid4())}}, "two"]}, "TENANT_SCOPE_VIOLATION"),
        ({"answers": ["one", float("nan")]}, "INVALID_ANSWER_FIXTURE"),
    ]
    for index, (answer_fixture, code) in enumerate(cases):
        with pytest.raises(GeoRunError) as error:
            service.run(idempotency_key=f"case-{index}", answer_fixture=answer_fixture, **base)
        assert error.value.code == code


def test_answer_fixture_uuid_bindings_are_canonicalized() -> None:
    tenant, fixtures, fixture = _active_fixture()
    service = GeoRunService(fixture_service=fixtures, clock=lambda: STAMP)
    wrapper = {
        "fixture_id": fixture["id"].upper(),
        "query_fixture_id": fixture["id"].upper(),
        "fixture_hash": fixture["fixture_hash"],
        "answers": ["Acme", "Other"],
    }
    value = service.run(
        org_id=tenant,
        idempotency_key="canonical-fixture-id",
        page_version_id=uuid4(),
        query_fixture_id=fixture["id"],
        locale="en-US",
        region="US",
        sample_count=2,
        answer_fixture=wrapper,
    )
    assert value["query_fixture_id"] == fixture["id"]


def test_injected_fixture_service_cannot_cross_tenant_boundary() -> None:
    tenant, fixtures, fixture = _active_fixture()

    class ForeignFixtureService:
        def get_fixture(self, **kwargs):
            return {**fixture, "org_id": str(uuid4())}

    service = GeoRunService(fixture_service=ForeignFixtureService(), clock=lambda: STAMP)
    with pytest.raises(GeoRunError) as error:
        service.run(
            org_id=tenant,
            idempotency_key="foreign-fixture-service",
            page_version_id=uuid4(),
            query_fixture_id=fixture["id"],
            locale="en-US",
            region="US",
            sample_count=2,
            answers=["Acme", "Other"],
        )
    assert error.value.code == "TENANT_SCOPE_VIOLATION"


def test_tenant_predecessor_fixture_state_and_locale_are_fail_closed() -> None:
    tenant, fixtures, fixture = _active_fixture()
    service = GeoRunService(fixture_service=fixtures, clock=lambda: STAMP)
    with pytest.raises(GeoRunError) as cross:
        _run(service, uuid4(), fixture, answers=["Acme", "Other"])
    assert cross.value.code == "TENANT_SCOPE_VIOLATION"
    with pytest.raises(GeoRunError) as nested:
        _run(
            service,
            tenant,
            fixture,
            key="nested",
            answers=["Acme", "Other"],
            predecessor_artifacts={"site": [[{"org_id": str(uuid4()), "status": "done"}]]},
        )
    assert nested.value.code == "TENANT_SCOPE_VIOLATION"
    with pytest.raises(GeoRunError) as policy:
        _run(
            service,
            tenant,
            fixture,
            key="policy-tenant",
            answers=["Acme", "Other"],
            policy_snapshot={"nested": {"tenant_id": str(uuid4())}},
        )
    assert policy.value.code == "TENANT_SCOPE_VIOLATION"
    with pytest.raises(GeoRunError) as locale:
        service.run(
            org_id=tenant,
            idempotency_key="locale",
            page_version_id=uuid4(),
            query_fixture_id=fixture["id"],
            locale="fr-FR",
            region="US",
            sample_count=2,
            answers=["Acme", "Other"],
        )
    assert locale.value.code == "FIXTURE_LOCALE_MISMATCH"

    draft_service = GeoQueryFixtureService(clock=lambda: STAMP)
    draft = draft_service.create_fixture(
        org_id=tenant,
        idempotency_key="draft",
        query="Acme?",
        locale="en-US",
        region="US",
        expected_entities=["Acme"],
        expected_claim_ids=[],
    )
    with pytest.raises(GeoRunError) as inactive:
        GeoRunService(fixture_service=draft_service).run(
            org_id=tenant,
            idempotency_key="inactive",
            page_version_id=uuid4(),
            query_fixture_id=draft["id"],
            locale="en-US",
            region="US",
            sample_count=2,
            answers=["Acme", "Other"],
        )
    assert inactive.value.code == "FIXTURE_NOT_ACTIVE"


def test_custom_ports_cannot_forge_result_binding_or_leak_failures() -> None:
    tenant, fixtures, fixture = _active_fixture()

    class ForgedSampler(DeterministicComplianceSampler):
        def sample(self, **kwargs):
            value = dict(super().sample(**kwargs))
            value["result_hash"] = "f" * 64
            return value

    forged = GeoRunService(fixture_service=fixtures, sampler=ForgedSampler(), clock=lambda: STAMP)
    with pytest.raises(GeoRunError) as mismatch:
        _run(forged, tenant, fixture, answers=["Acme", "Other"])
    assert mismatch.value.code == "INVALID_GEO_RUN_SAMPLE"

    class BrokenSampler(DeterministicComplianceSampler):
        def sample(self, **kwargs):
            raise RuntimeError("provider token=must-not-leak")

    broken = GeoRunService(fixture_service=fixtures, sampler=BrokenSampler(), clock=lambda: STAMP)
    with pytest.raises(GeoRunError) as failed:
        _run(broken, tenant, fixture, answers=["Acme", "Other"])
    assert failed.value.code == "SAMPLING_PORT_FAILED"
    assert "must-not-leak" not in repr(broken.store.audit)


def test_run_reads_are_tenant_scoped() -> None:
    tenant, fixtures, fixture = _active_fixture()
    service = GeoRunService(fixture_service=fixtures, clock=lambda: STAMP)
    value = _run(service, tenant, fixture, answers=["Acme", "Other"])
    assert service.get_run(org_id=tenant, run_id=value["id"]) == value
    with pytest.raises(GeoRunError) as cross:
        service.get_run(org_id=uuid4(), run_id=value["id"])
    assert cross.value.code == "TENANT_SCOPE_VIOLATION"


def test_fake_geo_can_own_the_offline_answer_fixture() -> None:
    tenant, fixtures, fixture = _active_fixture()
    fake_geo = FakeGeo(answer_fixture={
        "fixture_id": fixture["id"],
        "fixture_hash": fixture["fixture_hash"],
        "answers": ["Acme", {"status": "unknown"}],
    })
    service = GeoRunService(fixture_service=fixtures, fake_geo=fake_geo, clock=lambda: STAMP)
    value = service.run(
        org_id=tenant,
        idempotency_key="default-fixture",
        page_version_id=uuid4(),
        query_fixture_id=fixture["id"],
        locale="en-US",
        region="US",
        sample_count=2,
    )
    assert value["sample_count"] == 2
    assert value["data_quality"] == "estimated"
