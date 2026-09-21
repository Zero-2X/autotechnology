from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / "docs/tasks/FOUND-004D.md"
FAILURE_SCHEMA = ROOT / "packages/contracts/jsonschema/task-failure.schema.json"
JOB_SCHEMA = ROOT / "packages/contracts/jsonschema/task-job.schema.json"
MIGRATION = ROOT / "packages/db/migrations/versions/20260916_found_004d_failure_retry.py"


def test_failure_contract_and_task_card_are_explicit() -> None:
    schema = json.loads(FAILURE_SCHEMA.read_text(encoding="utf-8"))
    job_schema = json.loads(JOB_SCHEMA.read_text(encoding="utf-8"))
    task = TASK.read_text(encoding="utf-8")
    assert set(schema["required"]) == {
        "id", "org_id", "job_id", "attempt_count", "error_class", "error_code",
        "message_redacted", "retryable", "trace_id", "occurred_at",
    }
    assert "retry_scheduled" in job_schema["properties"]["status"]["enum"]
    assert "dead_letter" in job_schema["properties"]["status"]["enum"]
    human_schema = json.loads(
        (ROOT / "packages/contracts/jsonschema/human-task.schema.json").read_text(encoding="utf-8")
    )
    assert human_schema["properties"]["input_snapshot"]["additionalProperties"] is True
    assert human_schema["properties"]["result"]["additionalProperties"] is True
    assert "20260916_found_004d_failure_retry.py" in task
    assert "UNKNOWN_RESULT_REQUIRES_REVIEW" in task
    assert MIGRATION.exists()


def test_retry_policy_is_bounded_and_jitter_is_injected() -> None:
    from infra.foundation.task_failure import InvalidTaskFailureError, RetryPolicy

    policy = RetryPolicy(backoff_base_ms=100, backoff_cap_ms=250)
    assert [policy.delay_ms(i) for i in (1, 2, 3, 4)] == [100, 200, 250, 250]
    jittered = RetryPolicy(backoff_base_ms=100, backoff_cap_ms=250, jitter=0.2)
    assert 80 <= jittered.delay_ms(1, random_value=0) <= 250
    assert jittered.delay_ms(4, random_value=1) == 250
    try:
        RetryPolicy(backoff_base_ms=10, backoff_cap_ms=9)
    except InvalidTaskFailureError as exc:
        assert "backoff_cap_ms" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("invalid policy must be rejected")
