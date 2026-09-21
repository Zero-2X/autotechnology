from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path

import pytest

from modules.media import MediaRenderRetryService, RenderRetryPolicy


_SPEC = importlib.util.spec_from_file_location("render_retry_integration_fixture", Path(__file__).resolve().parents[1] / "unit/media/test_media_render_service.py")
assert _SPEC and _SPEC.loader
_FIXTURE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURE)


class _Task:
    def __init__(self, job_id: str, org_id: str, *, key: str, now=None):
        self.aggregate_id = job_id
        self.org_id = org_id
        self.id = key
        self.job_type = "media.render.retry"
        self.trace_id = "retry-worker"
        self.now = now


class _Context:
    def __init__(self):
        self.count = 0

    def checkpoint(self):
        self.count += 1


def _fixture():
    service, renderer, org, actor, script, visual, output, _ = _FIXTURE._service()
    retry = MediaRenderRetryService(service, policy=RenderRetryPolicy(backoff_base_ms=1, backoff_cap_ms=1, max_attempts=2))
    job = service.create_render_job(script_version=script, visual_asset_set_version=visual, output_spec_version=output,
                                    profile_key="square", org_id=org, actor_id=actor, idempotency_key="integration-retry")["render_job"]
    return service, retry, renderer, org, actor, script, visual, output, job


def test_retry_worker_claims_due_schedule_and_emits_contract_envelope() -> None:
    service, retry, renderer, org, actor, script, visual, output, job = _fixture()
    now = datetime.now(timezone.utc)
    retry.record_failure(media_render_job_id=job["id"], org_id=org, actor_id=actor,
                         error_class="transient", error_code="RENDER_BACKEND_UNAVAILABLE",
                         idempotency_key="integration-failure", occurred_at=now)
    context = _Context()
    result = retry.worker_handler(_Task(job["id"], org, key="integration-retry-command", now=now + timedelta(seconds=1)), context)
    assert result is not None and result["status"] == "succeeded"
    assert len(renderer.calls) == 1
    assert context.count == 2
    event = next(item for item in service.outbox_events if item["event_type"] == "asset.render_retry_scheduled")
    assert {"event_id", "aggregate_type", "actor_type", "payload_hash"} <= set(event)
    assert event["aggregate_type"] == "MediaRenderJob"


def test_unknown_result_cannot_be_automatically_retried_or_shot_rerendered() -> None:
    service, retry, renderer, org, actor, script, visual, output, job = _fixture()
    unknown = retry.record_failure(media_render_job_id=job["id"], org_id=org, actor_id=actor,
                                   error_class="unknown", error_code="RENDER_RESULT_UNKNOWN",
                                   idempotency_key="integration-unknown")
    assert unknown["status"] == "unknown"
    with pytest.raises(Exception) as error:
        retry.rerender_shot(media_render_job_id=job["id"], org_id=org, actor_id=actor,
                            stage="scene", shot_sequence=1, idempotency_key="integration-shot")
    assert getattr(error.value, "code", None) == "UNKNOWN_RESULT_REQUIRES_REVIEW"
    assert not retry.retry_due(org_id=org, now=datetime.now(timezone.utc))
    assert renderer.calls == []
