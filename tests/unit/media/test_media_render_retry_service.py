from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest

from modules.media import (
    MediaRenderError,
    MediaRenderRetryError,
    MediaRenderRetryService,
    RenderRetryPolicy,
)


ROOT = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location("render_service_fixture", Path(__file__).with_name("test_media_render_service.py"))
assert _SPEC and _SPEC.loader
_FIXTURE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURE)


def _service():
    base, renderer, org, actor, script, visual, output, assets = _FIXTURE._service()
    retry = MediaRenderRetryService(base, policy=RenderRetryPolicy(backoff_base_ms=1000, backoff_cap_ms=2500, max_attempts=3))
    return base, retry, renderer, org, actor, script, visual, output, assets


def _job(retry_or_service, org, actor, script, visual, output, key="retry-job"):
    return retry_or_service.render_service.create_render_job(
        script_version=script, visual_asset_set_version=visual, output_spec_version=output,
        profile_key="square", org_id=org, actor_id=actor, idempotency_key=key,
    )["render_job"]


def test_retry_policy_is_bounded_and_reproducible() -> None:
    policy = RenderRetryPolicy(backoff_base_ms=100, backoff_cap_ms=250, max_attempts=4)
    assert [policy.delay_ms(i) for i in (1, 2, 3, 4)] == [100, 200, 250, 250]
    assert policy.delay_ms(1, random_value=0) == 100


def test_failure_classification_idempotency_and_unknown_review() -> None:
    service, retry, _, org, actor, script, visual, output, _ = _service()
    job = _job(retry, org, actor, script, visual, output, key="failure-classify")
    first = retry.record_failure(media_render_job_id=job["id"], org_id=org, actor_id=actor,
                                 error_class="deterministic", error_code="RENDER_OUTPUT_INVALID",
                                 message_redacted="invalid output", idempotency_key="failure-1")
    assert first["status"] == "failed" and first["code"] == "RETRY_NOT_ALLOWED"
    replay = retry.record_failure(media_render_job_id=job["id"], org_id=org, actor_id=actor,
                                  error_class="deterministic", error_code="RENDER_OUTPUT_INVALID",
                                  message_redacted="invalid output", idempotency_key="failure-1")
    assert replay["failure"]["id"] == first["failure"]["id"]
    with pytest.raises(MediaRenderRetryError) as reused:
        retry.record_failure(media_render_job_id=job["id"], org_id=org, actor_id=actor,
                             error_class="unknown", error_code="OTHER", idempotency_key="failure-1")
    assert reused.value.code == "IDEMPOTENCY_KEY_REUSED"

    _, unknown_retry, _, _, _, _, _, _, _ = _service()
    unknown_job = _job(unknown_retry, org, actor, script, visual, output, key="failure-unknown")
    unknown = unknown_retry.record_failure(media_render_job_id=unknown_job["id"], org_id=org, actor_id=actor,
                                   error_class="unknown", error_code="RENDER_RESULT_UNKNOWN",
                                   idempotency_key="failure-unknown-1")
    assert unknown["status"] == "unknown"
    assert unknown["human_task"]["task_type"] == "unknown_result"
    assert len(unknown_retry.store.human_tasks) == 1


def test_transient_retry_is_scheduled_then_claimed_once() -> None:
    service, retry, renderer, org, actor, script, visual, output, _ = _service()
    job = _job(retry, org, actor, script, visual, output, key="failure-transient")
    now = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
    scheduled = retry.record_failure(media_render_job_id=job["id"], org_id=org, actor_id=actor,
                                     error_class="transient", error_code="RENDER_BACKEND_UNAVAILABLE",
                                     idempotency_key="failure-transient-1", occurred_at=now)
    assert scheduled["status"] == "retry_scheduled"
    assert scheduled["schedule"]["delay_ms"] == 1000
    due = retry.retry_due(media_render_job_id=job["id"], org_id=org, actor_id=actor,
                          now=now + timedelta(seconds=2), idempotency_key="retry-now")
    assert due["status"] == "succeeded"
    assert len(renderer.calls) == 1
    replay = retry.retry_due(media_render_job_id=job["id"], org_id=org, actor_id=actor,
                             now=now + timedelta(seconds=3), idempotency_key="retry-now")
    assert replay["duplicate"] is True
    assert len(renderer.calls) == 1


def test_retry_limit_dead_letters_without_schedule() -> None:
    service, retry, _, org, actor, script, visual, output, _ = _service()
    job = _job(retry, org, actor, script, visual, output, key="failure-dead")
    # Claim once so the failure attempt is explicit, then exhaust the policy.
    service.store.claim_running(org_id=org, job_id=job["id"], stamp="2026-09-20T12:00:00Z")
    service.store.jobs[job["id"]]["status"] = "failed"
    service.store.jobs[job["id"]]["max_attempts"] = 1
    result = retry.record_failure(media_render_job_id=job["id"], org_id=org, actor_id=actor,
                                  error_class="transient", error_code="RENDER_BACKEND_UNAVAILABLE",
                                  idempotency_key="failure-dead-1", max_attempts=1)
    assert result["status"] == "dead_letter"
    assert result["human_task"]["task_type"] == "support_escalation"
    assert not retry.store.retry_schedules


def test_shot_rerender_reuses_confirmed_natural_key() -> None:
    service, retry, renderer, org, actor, script, visual, output, _ = _service()
    job = _job(retry, org, actor, script, visual, output, key="shot-rerender")
    first = retry.rerender_shot(media_render_job_id=job["id"], org_id=org, actor_id=actor,
                                stage="scene", shot_sequence=2, idempotency_key="shot-1")
    assert first["status"] == "succeeded"
    assert first["artifact"]["stage"] == "scene"
    assert first["artifact"]["shot_sequence"] == 2
    assert len(renderer.calls) == 1
    replay = retry.rerender_shot(media_render_job_id=job["id"], org_id=org, actor_id=actor,
                                 stage="scene", shot_sequence=2, idempotency_key="shot-2")
    assert replay["duplicate"] is True
    assert replay["artifact"]["id"] == first["artifact"]["id"]
    assert len(renderer.calls) == 1


def test_tenant_and_expected_version_are_checked_before_retry_write() -> None:
    service, retry, _, org, actor, script, visual, output, _ = _service()
    job = _job(retry, org, actor, script, visual, output, key="scope-retry")
    with pytest.raises(MediaRenderRetryError) as foreign:
        retry.record_failure(media_render_job_id=job["id"], org_id=str(uuid4()), actor_id=actor,
                             error_class="transient", error_code="RENDER_BACKEND_UNAVAILABLE", idempotency_key="foreign")
    assert foreign.value.code == "TENANT_SCOPE_VIOLATION"
    version = service.store.version(org_id=org, job_id=job["id"])
    with pytest.raises(MediaRenderRetryError) as stale:
        retry.record_failure(media_render_job_id=job["id"], org_id=org, actor_id=actor,
                             error_class="transient", error_code="RENDER_BACKEND_UNAVAILABLE", idempotency_key="stale",
                             expected_version=version + 1)
    assert stale.value.code == "VERSION_CONFLICT"
    assert not retry.store.failures


def test_unknown_resolution_requires_evidence_and_never_calls_renderer() -> None:
    service, retry, renderer, org, actor, script, visual, output, _ = _service()
    job = _job(retry, org, actor, script, visual, output, key="unknown-resolve")
    retry.record_failure(media_render_job_id=job["id"], org_id=org, actor_id=actor,
                         error_class="unknown", error_code="RENDER_RESULT_UNKNOWN", idempotency_key="unknown-failure")
    with pytest.raises(MediaRenderRetryError) as missing:
        retry.resolve_unknown(media_render_job_id=job["id"], org_id=org, actor_id=actor,
                              outcome="succeeded", evidence_ref="", idempotency_key="resolve-1")
    assert missing.value.code == "INVALID_UNKNOWN_RESOLUTION"
    resolved = retry.resolve_unknown(media_render_job_id=job["id"], org_id=org, actor_id=actor,
                                     outcome="dead_letter", evidence_ref="review/ticket-1", idempotency_key="resolve-2")
    assert resolved["status"] == "dead_letter"
    assert renderer.calls == []
