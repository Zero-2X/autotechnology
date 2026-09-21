"""Failure classification, bounded retry and shot re-render for MEDIA-004B.

The service owns only render facts and orchestration decisions.  Renderer and
storage calls remain behind the ports exposed by :mod:`render_service`, and
all retry state is kept tenant scoped and replayable.  The in-memory store is
the account-free reference implementation used by the contract tests; a
database adapter can project the same records into the MEDIA-004B tables.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import random
import re
from typing import Any, Mapping
from uuid import UUID, uuid5

from jsonschema import Draft202012Validator, FormatChecker

from .render_service import (
    JOB_NAMESPACE,
    JOB_VALIDATOR,
    MediaRenderError,
    MediaRenderService,
    _bytes_hash,
    _context,
    _hash,
    _schema,
    _stamp,
    _text,
    _time,
    _uuid,
)


ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "packages" / "contracts" / "jsonschema"
FAILURE_VALIDATOR = Draft202012Validator(
    json.loads((CONTRACTS / "task-failure.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)

ERROR_CLASSES = frozenset({"deterministic", "transient", "unknown"})
ERROR_CODE_RE = re.compile(r"^[A-Z0-9_]{1,128}$")
STAGES = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
SENSITIVE = frozenset({"model", "provider", "credential", "token", "secret", "password", "authorization", "api_key", "raw_output"})


class MediaRenderRetryError(MediaRenderError):
    """Stable error codes exposed by retry and re-render commands."""


class RenderRetryError(MediaRenderRetryError):
    """Compatibility name for callers that use the shorter service name."""


@dataclass(frozen=True)
class RenderRetryPolicy:
    """Deterministic bounded exponential backoff.

    Jitter is opt-in and injected through ``random_value`` so account-free
    tests remain reproducible.  The result is always capped.
    """

    backoff_base_ms: int = 1_000
    backoff_cap_ms: int = 60_000
    max_attempts: int = 3
    jitter: float = 0.0
    jitter_ms: int = 0

    def __post_init__(self) -> None:
        if type(self.backoff_base_ms) is not int or self.backoff_base_ms <= 0:
            raise MediaRenderRetryError("INVALID_RETRY_POLICY", "backoff_base_ms must be greater than zero")
        if type(self.backoff_cap_ms) is not int or self.backoff_cap_ms < self.backoff_base_ms:
            raise MediaRenderRetryError("INVALID_RETRY_POLICY", "backoff_cap_ms must be at least backoff_base_ms")
        if type(self.max_attempts) is not int or self.max_attempts < 1:
            raise MediaRenderRetryError("INVALID_RETRY_POLICY", "max_attempts must be at least one")
        if type(self.jitter) is not float and type(self.jitter) is not int:
            raise MediaRenderRetryError("INVALID_RETRY_POLICY", "jitter must be numeric")
        if not 0 <= float(self.jitter) <= 1:
            raise MediaRenderRetryError("INVALID_RETRY_POLICY", "jitter must be between zero and one")
        if type(self.jitter_ms) is not int or self.jitter_ms < 0:
            raise MediaRenderRetryError("INVALID_RETRY_POLICY", "jitter_ms must be zero or greater")

    def delay_ms(self, attempt_count: int, *, random_value: float | None = None) -> int:
        if type(attempt_count) is not int or attempt_count < 1:
            raise MediaRenderRetryError("INVALID_RETRY_POLICY", "attempt_count must be at least one")
        bounded = min(self.backoff_cap_ms, self.backoff_base_ms * (2 ** (attempt_count - 1)))
        if self.jitter == 0 and self.jitter_ms == 0:
            return int(bounded)
        sample = random.random() if random_value is None else random_value
        if not 0 <= sample <= 1:
            raise MediaRenderRetryError("INVALID_RETRY_POLICY", "random_value must be between zero and one")
        factor = 1 + ((sample * 2) - 1) * float(self.jitter)
        value = bounded * factor + ((sample * 2) - 1) * self.jitter_ms
        return max(0, min(self.backoff_cap_ms, int(round(value))))

    compute_delay_ms = delay_ms
    backoff_delay_ms = delay_ms


RetryPolicy = RenderRetryPolicy


@dataclass(frozen=True)
class RenderFailure:
    id: str
    org_id: str
    job_id: str
    attempt_count: int
    error_class: str
    error_code: str
    message_redacted: str | None
    retryable: bool
    trace_id: str
    occurred_at: str

    def as_contract(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class RenderRetryDecision:
    failure: dict[str, Any] | None
    job: dict[str, Any]
    status: str
    code: str | None
    schedule: dict[str, Any] | None = None
    human_task: dict[str, Any] | None = None
    duplicate: bool = False
    artifact: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "failure": deepcopy(self.failure),
            "render_job": deepcopy(self.job),
            "status": self.status,
            "code": self.code,
            "schedule": deepcopy(self.schedule),
            "human_task": deepcopy(self.human_task),
            "duplicate": self.duplicate,
            "artifact": deepcopy(self.artifact),
        }


class MediaRenderRetryService:
    """Coordinate retry facts without repeating confirmed external effects."""

    def __init__(self, render_service: MediaRenderService | None = None, *, service: MediaRenderService | None = None,
                 policy: RenderRetryPolicy | None = None, retry_policy: RenderRetryPolicy | None = None,
                 clock: Any | None = None, max_attempts: int | None = None) -> None:
        self.render_service = render_service or service or MediaRenderService()
        self.store = self.render_service.store
        self.policy = policy or retry_policy or RenderRetryPolicy(max_attempts=max_attempts or 3)
        if max_attempts is not None and max_attempts != self.policy.max_attempts:
            self.policy = RenderRetryPolicy(
                backoff_base_ms=self.policy.backoff_base_ms,
                backoff_cap_ms=self.policy.backoff_cap_ms,
                max_attempts=max_attempts,
                jitter=self.policy.jitter,
                jitter_ms=self.policy.jitter_ms,
            )
        self.clock = clock or self.render_service.clock

    def _now(self, value: Any | None, field: str) -> datetime:
        return _time(value if value is not None else self.clock(), field)

    @staticmethod
    def _safe_message(value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise MediaRenderRetryError("INVALID_RENDER_FAILURE", "message_redacted must be text")
        result = value.strip()
        if not result or len(result) > 512 or any(ord(char) < 0x20 and char not in "\t\n\r" for char in result):
            raise MediaRenderRetryError("INVALID_RENDER_FAILURE", "message_redacted has an invalid value")
        if any(word in result.lower() for word in SENSITIVE):
            raise MediaRenderRetryError("SENSITIVE_INPUT_REJECTED", "failure message contains a restricted field")
        return result

    def _job(self, tenant: str, media_render_job_id: Any) -> dict[str, Any]:
        try:
            return self.store.get(org_id=tenant, job_id=_uuid(media_render_job_id, "media_render_job_id"))
        except MediaRenderError as exc:
            raise MediaRenderRetryError(exc.code, str(exc)) from exc

    @staticmethod
    def _classify_error(code: str) -> str:
        if code == "RENDER_RESULT_UNKNOWN" or code.endswith("_UNKNOWN"):
            return "unknown"
        if code in {
            "RENDER_BACKEND_UNAVAILABLE", "RENDER_TIMEOUT", "STORAGE_TEMPORARY_FAILURE",
            "STORAGE_UNAVAILABLE", "DEPENDENCY_UNAVAILABLE", "TIMEOUT", "TEMPORARY_FAILURE",
        } or code.endswith("_UNAVAILABLE") or code.endswith("_TIMEOUT"):
            return "transient"
        return "deterministic"

    def _expected_version(self, tenant: str, job_id: str, expected_version: Any | None) -> int:
        current = self.store.version(org_id=tenant, job_id=job_id)
        if expected_version is not None and (type(expected_version) is not int or expected_version < 1):
            raise MediaRenderRetryError("INVALID_EXPECTED_VERSION", "expected_version must be a positive integer")
        if expected_version is not None and expected_version != current:
            raise MediaRenderRetryError("VERSION_CONFLICT", "render job version does not match expected_version")
        return current

    def _command_replay(self, *, tenant: str, namespace: str, key: str, request_hash: str) -> dict[str, Any] | None:
        with self.store._lock:
            prior = self.store.retry_commands.get((tenant, namespace, key))
            if prior is None:
                return None
            if prior["request_hash"] != request_hash:
                raise MediaRenderRetryError("IDEMPOTENCY_KEY_REUSED", "command payload differs from prior request")
            result = deepcopy(prior["response"])
            result["duplicate"] = True
            return result

    def _save_command(self, *, tenant: str, namespace: str, key: str, request_hash: str, response: Mapping[str, Any]) -> dict[str, Any]:
        with self.store._lock:
            self.store.retry_commands[(tenant, namespace, key)] = {"request_hash": request_hash, "response": deepcopy(dict(response))}
        return deepcopy(dict(response))

    def _event(self, event_type: str, *, tenant: str, job: Mapping[str, Any], actor: str, trace: str,
               key: str, payload: Mapping[str, Any], occurred_at: str) -> None:
        event_payload = {"aggregate_id": str(job["id"]), "aggregate_version": self.store.version(org_id=tenant, job_id=str(job["id"])), **dict(payload)}
        event_id = str(uuid5(JOB_NAMESPACE, f"media-render-event:{event_type}:{job['id']}:{event_payload['aggregate_version']}:{key}"))
        self.store.outbox.append({"event_id": event_id, "event_type": event_type, "event_schema_version": 1, "org_id": tenant,
                                  "aggregate_id": str(job["id"]), "aggregate_version": event_payload["aggregate_version"],
                                  "aggregate_type": "MediaRenderJob", "trace_id": trace, "actor_type": "service", "actor_id": actor, "idempotency_key": key,
                                  "occurred_at": occurred_at, "payload": event_payload, "payload_hash": _hash(event_payload)})

    def _validate_failure(self, failure: Mapping[str, Any]) -> None:
        errors = sorted(FAILURE_VALIDATOR.iter_errors(dict(failure)), key=lambda item: list(item.absolute_path))
        if errors:
            raise MediaRenderRetryError("INVALID_RENDER_FAILURE", errors[0].message)

    def _failure_record(self, *, tenant: str, job_id: str, attempt_count: int, error_class: str,
                        error_code: str, message_redacted: str | None, trace: str, occurred_at: str) -> dict[str, Any]:
        failure_id = str(uuid5(JOB_NAMESPACE, f"media-render-failure:{tenant}:{job_id}:{attempt_count}:{error_code}"))
        failure = RenderFailure(
            id=failure_id, org_id=tenant, job_id=job_id, attempt_count=attempt_count,
            error_class=error_class, error_code=error_code, message_redacted=message_redacted,
            retryable=error_class == "transient", trace_id=trace, occurred_at=occurred_at,
        ).as_contract()
        self._validate_failure(failure)
        return failure

    def _human_task(self, *, tenant: str, job: Mapping[str, Any], failure: Mapping[str, Any], actor: str,
                    occurred_at: str, reason: str) -> dict[str, Any]:
        key = (tenant, str(job["id"]), failure["error_class"])
        with self.store._lock:
            prior = self.store.human_tasks.get(key)
            if prior is not None:
                return deepcopy(prior)
            task_id = str(uuid5(JOB_NAMESPACE, f"media-render-human-task:{tenant}:{job['id']}:{failure['error_class']}"))
            task = {
                "id": task_id, "org_id": tenant, "task_type": "unknown_result" if failure["error_class"] == "unknown" else "support_escalation",
                "aggregate_type": "MediaRenderJob", "aggregate_id": str(job["id"]), "input_version": int(job.get("attempt_count", 0)),
                "status": "queued", "priority": "urgent" if failure["error_class"] == "unknown" else "high",
                "input_snapshot": {"render_job_id": str(job["id"]), "input_hash": job["input_hash"], "failure_id": failure["id"], "reason": reason, "side_effect_blocked": True},
                "result": {}, "created_by": actor, "created_at": occurred_at, "completed_at": None,
            }
            self.store.human_tasks[key] = deepcopy(task)
            return task

    def record_failure(self, *, media_render_job_id: Any, error_class: str, error_code: str,
                       org_id: Any = None, tenant_context: Any = None, actor_id: Any = None,
                       trace_id: str = "media-render-failure", idempotency_key: str,
                       message_redacted: str | None = None, occurred_at: Any | None = None,
                       expected_version: int | None = None, attempt_count: int | None = None,
                       max_attempts: int | None = None) -> dict[str, Any]:
        tenant, actor = _context(org_id=org_id, actor_id=actor_id, tenant_context=tenant_context)
        trace_id = _text(trace_id, "trace_id", 256)
        trace, key = _text(trace_id, "trace_id", 256), _text(idempotency_key, "idempotency_key", 200)
        if error_class not in ERROR_CLASSES:
            raise MediaRenderRetryError("INVALID_RENDER_FAILURE", "error_class must be deterministic, transient or unknown")
        if not isinstance(error_code, str) or not ERROR_CODE_RE.fullmatch(error_code.strip()):
            raise MediaRenderRetryError("INVALID_RENDER_FAILURE", "error_code has an invalid value")
        code = error_code.strip()
        message = self._safe_message(message_redacted)
        at = self._now(occurred_at, "occurred_at")
        job = self._job(tenant, media_render_job_id)
        job_id = str(job["id"])
        request_hash = _hash({"operation": "record_failure", "job_id": job_id, "error_class": error_class, "error_code": code,
                              "message_redacted": message, "attempt_count": attempt_count, "max_attempts": max_attempts,
                              "expected_version": expected_version})
        replay = self._command_replay(tenant=tenant, namespace="failure", key=key, request_hash=request_hash)
        if replay is not None:
            return replay
        if job.get("status") == "succeeded" or job.get("artifacts"):
            raise MediaRenderRetryError("RENDER_JOB_ALREADY_CONFIRMED", "confirmed render artifacts cannot be failed")
        current_version = self._expected_version(tenant, job_id, expected_version)
        attempt = attempt_count if attempt_count is not None else max(1, int(job.get("attempt_count", 0)))
        if type(attempt) is not int or attempt < 1 or attempt > max(1, int(job.get("attempt_count", attempt))):
            raise MediaRenderRetryError("INVALID_RENDER_FAILURE", "attempt_count does not match the render job")
        configured_max = max_attempts if max_attempts is not None else int(job.get("max_attempts", self.policy.max_attempts))
        if type(configured_max) is not int or configured_max < 1:
            raise MediaRenderRetryError("INVALID_RETRY_POLICY", "max_attempts must be at least one")
        failure = self._failure_record(tenant=tenant, job_id=job_id, attempt_count=attempt,
                                       error_class=error_class, error_code=code, message_redacted=message,
                                       trace=trace, occurred_at=_stamp(at))
        natural = (tenant, job_id, attempt, code)
        with self.store._lock:
            prior_failure = self.store.failures.get(natural)
            if prior_failure is not None:
                prior_response = self._result_for_failure(prior_failure, job)
                prior_response["duplicate"] = True
                return self._save_command(tenant=tenant, namespace="failure", key=key, request_hash=request_hash, response=prior_response)
            self.store.failures[natural] = deepcopy(failure)
        job = deepcopy(job)
        job["max_attempts"] = configured_max
        job["failure_count"] = int(job.get("failure_count", 0)) + 1
        job["last_failure_id"] = failure["id"]
        job["failure_code"] = code
        job["updated_at"] = _stamp(at)
        schedule = None
        human_task = None
        if error_class == "deterministic":
            status, decision_code = "failed", "RETRY_NOT_ALLOWED"
            job["status"], job["next_retry_at"] = status, None
        elif error_class == "unknown":
            status, decision_code = "unknown", "UNKNOWN_RESULT_REQUIRES_REVIEW"
            job["status"], job["next_retry_at"] = status, None
            human_task = self._human_task(tenant=tenant, job=job, failure=failure, actor=actor, occurred_at=_stamp(at), reason=decision_code)
        elif attempt >= configured_max:
            status, decision_code = "dead_letter", "MAX_ATTEMPTS_EXCEEDED"
            job["status"], job["next_retry_at"], job["dead_letter_reason"] = status, None, decision_code
            human_task = self._human_task(tenant=tenant, job=job, failure=failure, actor=actor, occurred_at=_stamp(at), reason=decision_code)
        else:
            status, decision_code = "retry_scheduled", None
            delay = self.policy.delay_ms(attempt)
            available = at + timedelta(milliseconds=delay)
            schedule = {
                "id": str(uuid5(JOB_NAMESPACE, f"media-render-schedule:{tenant}:{job_id}:{attempt}")),
                "org_id": tenant, "render_job_id": job_id, "attempt_count": attempt,
                "available_at": _stamp(available), "status": "scheduled", "failure_id": failure["id"],
                "delay_ms": delay, "created_at": _stamp(at),
            }
            with self.store._lock:
                self.store.retry_schedules[(tenant, job_id, attempt)] = deepcopy(schedule)
            job["status"], job["next_retry_at"] = status, schedule["available_at"]
        self.store.save(org_id=tenant, job=job)
        self.store.bump_version(org_id=tenant, job_id=job_id)
        event_name = {"retry_scheduled": "asset.render_retry_scheduled", "dead_letter": "asset.render_dead_lettered", "unknown": "asset.render_unknown", "failed": "asset.render_failed"}[status]
        self._event(event_name, tenant=tenant, job=job, actor=actor, trace=trace, key=key, occurred_at=_stamp(at),
                    payload={"from_state": "running", "to_state": status, "command": "record_failure", "failure_id": failure["id"], "error_code": code},)
        self.store.audit.append({"operation": "record_render_failure", "org_id": tenant, "job_id": job_id, "failure_id": failure["id"],
                                 "status": status, "error_code": code, "error_class": error_class, "actor_id": actor,
                                 "trace_id": trace, "idempotency_key": key, "expected_version": current_version, "created_at": _stamp(at)})
        result = {"operation": "record_failure", "status": status, "code": decision_code, "duplicate": False,
                  "render_job": deepcopy(job), "failure": deepcopy(failure), "schedule": deepcopy(schedule),
                  "shot_target": None, "artifact": None, "human_task": deepcopy(human_task),
                  "next_retry_at": None if schedule is None else schedule["available_at"]}
        return self._save_command(tenant=tenant, namespace="failure", key=key, request_hash=request_hash, response=result)

    def _result_for_failure(self, failure: Mapping[str, Any], job: Mapping[str, Any]) -> dict[str, Any]:
        schedule = self.store.retry_schedules.get((str(job["org_id"]), str(job["id"]), int(failure["attempt_count"])))
        status = "retry_scheduled" if schedule and schedule.get("status") == "scheduled" else str(job.get("status"))
        return {"operation": "record_failure", "status": status, "code": None if status == "retry_scheduled" else ("UNKNOWN_RESULT_REQUIRES_REVIEW" if failure["error_class"] == "unknown" else "RETRY_NOT_ALLOWED"),
                "duplicate": True, "render_job": deepcopy(dict(job)), "failure": deepcopy(dict(failure)),
                "schedule": deepcopy(schedule), "shot_target": None, "artifact": None, "human_task": None,
                "next_retry_at": None if schedule is None else schedule.get("available_at")}

    def retry_due(self, *, org_id: Any = None, tenant_context: Any = None, actor_id: Any = None,
                  media_render_job_id: Any | None = None, now: Any | None = None,
                  trace_id: str = "media-render-retry", idempotency_key: str | None = None,
        expected_version: int | None = None) -> dict[str, Any] | list[dict[str, Any]]:
        tenant, actor = _context(org_id=org_id, actor_id=actor_id, tenant_context=tenant_context)
        trace_id = _text(trace_id, "trace_id", 256)
        at = self._now(now, "now")
        if media_render_job_id is not None:
            job_id = _uuid(media_render_job_id, "media_render_job_id")
            candidates = [self.store.retry_schedules.get((tenant, job_id, attempt)) for attempt in sorted({key[2] for key in self.store.retry_schedules if key[0] == tenant and key[1] == job_id})]
            candidates = [item for item in candidates if item is not None]
        else:
            candidates = [value for key, value in self.store.retry_schedules.items() if key[0] == tenant]
        due = [value for value in candidates if value.get("status") == "scheduled" and _time(value["available_at"], "available_at") <= at]
        if not due:
            # A completed command is replayable even though its schedule is no
            # longer in the due set.  This check deliberately happens before
            # RETRY_NOT_DUE so an at-least-once delivery can safely ack.
            if media_render_job_id is not None and idempotency_key:
                latest = candidates[-1] if candidates else None
                if latest is not None:
                    request_hash = _hash({"operation": "retry", "job_id": str(latest["render_job_id"]), "schedule_id": latest["id"], "expected_version": expected_version})
                    replay = self._command_replay(tenant=tenant, namespace="retry", key=idempotency_key, request_hash=request_hash)
                    if replay is not None:
                        return replay
            if media_render_job_id is not None:
                raise MediaRenderRetryError("RETRY_NOT_DUE", "no scheduled retry is currently due")
            return []
        results: list[dict[str, Any]] = []
        for schedule in due:
            job_id = str(schedule["render_job_id"])
            key = _text(idempotency_key, "idempotency_key", 200) if idempotency_key else f"retry:{job_id}:{schedule['attempt_count']}"
            request_hash = _hash({"operation": "retry", "job_id": job_id, "schedule_id": schedule["id"], "expected_version": expected_version})
            replay = self._command_replay(tenant=tenant, namespace="retry", key=key, request_hash=request_hash)
            if replay is not None:
                results.append(replay)
                continue
            # Validate the optimistic version before changing schedule state;
            # stale commands therefore leave no claimed row behind.
            self._expected_version(tenant, job_id, expected_version)
            with self.store._lock:
                current_schedule = self.store.retry_schedules.get((tenant, job_id, int(schedule["attempt_count"])))
                if current_schedule is None or current_schedule.get("status") != "scheduled":
                    raise MediaRenderRetryError("RETRY_ALREADY_CLAIMED", "scheduled retry was already claimed")
                current_schedule["status"] = "claimed"
                current_schedule["claimed_at"] = _stamp(at)
            try:
                result = self.render_service.execute_render_job(media_render_job_id=job_id, org_id=tenant, actor_id=actor,
                                                                trace_id=trace_id, executed_at=at, allow_retry=True)
                with self.store._lock:
                    current_schedule["status"] = "completed"
                    current_schedule["completed_at"] = _stamp(at)
                response = {"operation": "retry", "status": "succeeded", "code": None, "duplicate": False,
                            "render_job": deepcopy(result["render_job"]), "failure": None, "schedule": deepcopy(current_schedule),
                            "shot_target": None, "artifact": deepcopy(result["artifacts"][-1] if result.get("artifacts") else None),
                            "human_task": None, "next_retry_at": None}
            except MediaRenderError as exc:
                current_job = self.store.get(org_id=tenant, job_id=job_id)
                try:
                    failure_response = self.record_failure(media_render_job_id=job_id, org_id=tenant, actor_id=actor,
                                                           trace_id=trace_id, idempotency_key=f"{key}:failure",
                                                           error_class=self._classify_error(exc.code),
                                                           error_code=exc.code, message_redacted=str(exc), occurred_at=at)
                except MediaRenderRetryError:
                    raise
                response = {"operation": "retry", "status": failure_response["status"], "code": failure_response["code"], "duplicate": False,
                            "render_job": failure_response["render_job"], "failure": failure_response["failure"],
                            "schedule": deepcopy(current_schedule), "shot_target": None, "artifact": None,
                            "human_task": failure_response.get("human_task"), "next_retry_at": failure_response.get("next_retry_at")}
            saved = self._save_command(tenant=tenant, namespace="retry", key=key, request_hash=request_hash, response=response)
            results.append(saved)
        return results[0] if media_render_job_id is not None else results

    retry_render_job = retry_due
    retry = retry_due
    retry_due_jobs = retry_due

    def _recover_shot_artifact(self, *, tenant: str, job: Mapping[str, Any], stage: str,
                               shot_sequence: int, profile: str, at: datetime) -> dict[str, Any] | None:
        """Confirm a stable shot object left by a previous interrupted write."""
        object_key = f"render/{job['id']}/{profile}/{stage}/{shot_sequence}.bin"
        reference_factory = getattr(self.render_service.storage, "_reference", None)
        try:
            reference = reference_factory(tenant, object_key) if callable(reference_factory) else f"private://media-render/{tenant}/{object_key}"
            head = self.render_service.storage.head(tenant, reference)
            body = self.render_service.storage.get(tenant, reference)
        except Exception:
            return None
        body_hash = _bytes_hash(body)
        if getattr(head, "org_id", tenant) != tenant or head.storage_object_ref != reference or head.access_policy != "private" or head.content_hash.lower() != body_hash or head.size_bytes != len(body):
            raise MediaRenderRetryError("ARTIFACT_VERIFICATION_FAILED", "pending shot artifact failed hash verification")
        artifact = {"id": str(uuid5(JOB_NAMESPACE, f"{job['id']}:{object_key}")), "sequence": len(job.get("artifacts", [])) + 1,
                    "stage": stage, "shot_sequence": shot_sequence, "output_profile_key": profile,
                    "storage_object_ref": reference, "content_hash": body_hash, "size_bytes": len(body),
                    "content_type": head.content_type, "input_hash": job["input_hash"], "created_at": _stamp(at)}
        _schema(JOB_VALIDATOR, {**dict(job), "artifacts": [*job.get("artifacts", []), artifact], "artifact_count": len(job.get("artifacts", [])) + 1}, "INVALID_RENDER_JOB")
        confirmed = self.store.add_artifact(org_id=tenant, job_id=str(job["id"]), artifact=artifact)
        updated = deepcopy(dict(job))
        if not any(item.get("id") == confirmed["id"] for item in updated.get("artifacts", [])):
            updated["artifacts"] = [*updated.get("artifacts", []), confirmed]
            updated["artifact_count"] = len(updated["artifacts"])
        updated["updated_at"] = _stamp(at)
        self.store.save(org_id=tenant, job=updated)
        self.store.bump_version(org_id=tenant, job_id=str(job["id"]))
        return {"operation": "rerender_shot", "status": "succeeded", "code": None, "duplicate": True,
                "render_job": updated, "failure": None, "schedule": None,
                "shot_target": {"org_id": tenant, "render_job_id": str(job["id"]), "stage": stage,
                                 "shot_sequence": shot_sequence, "output_profile_key": profile,
                                 "input_hash": job["input_hash"], "status": "confirmed", "artifact_id": confirmed["id"],
                                 "created_at": _stamp(at)}, "artifact": confirmed, "human_task": None, "next_retry_at": None}

    def rerender_shot(self, *, media_render_job_id: Any, stage: str, shot_sequence: int,
                      org_id: Any = None, tenant_context: Any = None, actor_id: Any = None,
                      trace_id: str = "media-render-shot-rerender", idempotency_key: str,
                      profile_key: str | None = None, expected_version: int | None = None,
                      requested_at: Any | None = None) -> dict[str, Any]:
        tenant, actor = _context(org_id=org_id, actor_id=actor_id, tenant_context=tenant_context)
        trace = _text(trace_id, "trace_id", 256)
        job_id = _uuid(media_render_job_id, "media_render_job_id")
        stage = _text(stage, "stage", 64)
        if not STAGES.fullmatch(stage):
            raise MediaRenderRetryError("INVALID_SHOT_TARGET", "stage has an invalid value")
        if type(shot_sequence) is not int or shot_sequence < 1:
            raise MediaRenderRetryError("INVALID_SHOT_TARGET", "shot_sequence must be positive")
        profile = _text(profile_key or "", "profile_key", 64) if profile_key is not None else None
        at = self._now(requested_at, "requested_at")
        job = self._job(tenant, job_id)
        profile = profile or str(job["output_profile_key"])
        if profile != job["output_profile_key"]:
            raise MediaRenderRetryError("OUTPUT_PROFILE_MISMATCH", "shot rerender must use the locked output profile")
        request_hash = _hash({"operation": "rerender_shot", "job_id": job_id, "stage": stage, "shot_sequence": shot_sequence,
                              "profile_key": profile, "input_hash": job["input_hash"], "expected_version": expected_version})
        key = _text(idempotency_key, "idempotency_key", 200)
        replay = self._command_replay(tenant=tenant, namespace="rerender_shot", key=key, request_hash=request_hash)
        if replay is not None:
            return replay
        current_version = self._expected_version(tenant, job_id, expected_version)
        existing = self.store.artifact_for(org_id=tenant, job_id=job_id, stage=stage, shot_sequence=shot_sequence, output_profile_key=profile)
        if existing is not None:
            if existing.get("input_hash") != job.get("input_hash"):
                raise MediaRenderRetryError("ARTIFACT_KEY_CONFLICT", "confirmed shot artifact belongs to a different input hash")
            target = {"org_id": tenant, "render_job_id": job_id, "stage": stage, "shot_sequence": shot_sequence,
                      "output_profile_key": profile, "input_hash": job["input_hash"], "status": "confirmed",
                      "artifact_id": existing["id"], "created_at": _stamp(at)}
            response = {"operation": "rerender_shot", "status": "succeeded", "code": None, "duplicate": True,
                        "render_job": deepcopy(job), "failure": None, "schedule": None, "shot_target": target,
                        "artifact": existing, "human_task": None, "next_retry_at": None}
            return self._save_command(tenant=tenant, namespace="rerender_shot", key=idempotency_key, request_hash=request_hash, response=response)
        if job.get("status") == "running":
            raise MediaRenderRetryError("RENDER_JOB_IN_PROGRESS", "render job is currently running")
        if job.get("status") == "unknown":
            raise MediaRenderRetryError("UNKNOWN_RESULT_REQUIRES_REVIEW", "unknown result requires manual resolution before shot rerender")
        if job.get("status") == "dead_letter":
            raise MediaRenderRetryError("RENDER_JOB_NOT_EXECUTABLE", "dead-letter render job requires an explicit replay command")
        recovered = self._recover_shot_artifact(tenant=tenant, job=job, stage=stage, shot_sequence=shot_sequence,
                                                profile=profile, at=at)
        if recovered is not None:
            return self._save_command(tenant=tenant, namespace="rerender_shot", key=key,
                                      request_hash=request_hash, response=recovered)
        scoped_job = deepcopy(job)
        scoped_job["render_scope"] = {"stage": stage, "shot_sequence": shot_sequence}
        try:
            result = self.render_service._renderer_result(scoped_job, expected_stage=stage, expected_shot_sequence=shot_sequence)
            object_key = f"render/{job_id}/{profile}/{stage}/{shot_sequence}.bin"
            stored = self.render_service.storage.put(tenant, object_key, result["content"], content_type=result["content_type"],
                                                     metadata={"input_hash": job["input_hash"], "stage": stage, "shot_sequence": str(shot_sequence)},
                                                     idempotency_key=f"render:{job_id}:{stage}:{shot_sequence}")
            head = self.render_service.storage.head(tenant, stored.storage_object_ref)
            body = self.render_service.storage.get(tenant, stored.storage_object_ref)
            body_hash = _bytes_hash(body)
            if getattr(head, "org_id", tenant) != tenant or head.storage_object_ref != stored.storage_object_ref or head.access_policy != "private" or head.content_hash.lower() != body_hash or head.size_bytes != len(body) or head.content_type != result["content_type"]:
                raise MediaRenderRetryError("ARTIFACT_VERIFICATION_FAILED", "stored shot artifact failed hash verification")
            artifact = {"id": str(uuid5(JOB_NAMESPACE, f"{job_id}:{object_key}")), "sequence": len(job.get("artifacts", [])) + 1,
                        "stage": stage, "shot_sequence": shot_sequence, "output_profile_key": profile,
                        "storage_object_ref": stored.storage_object_ref, "content_hash": body_hash, "size_bytes": len(body),
                        "content_type": head.content_type, "input_hash": job["input_hash"], "created_at": _stamp(at)}
            _schema(JOB_VALIDATOR, {**job, "artifacts": [*job.get("artifacts", []), artifact], "artifact_count": len(job.get("artifacts", [])) + 1}, "INVALID_RENDER_JOB")
            artifact = self.store.add_artifact(org_id=tenant, job_id=job_id, artifact=artifact)
            updated = deepcopy(job)
            if not any(item.get("id") == artifact["id"] for item in updated.get("artifacts", [])):
                updated["artifacts"] = [*updated.get("artifacts", []), artifact]
                updated["artifact_count"] = len(updated["artifacts"])
            updated["updated_at"] = _stamp(at)
            self.store.save(org_id=tenant, job=updated)
            self.store.bump_version(org_id=tenant, job_id=job_id)
            target = {"org_id": tenant, "render_job_id": job_id, "stage": stage, "shot_sequence": shot_sequence,
                      "output_profile_key": profile, "input_hash": job["input_hash"], "status": "confirmed",
                      "artifact_id": artifact["id"], "created_at": _stamp(at)}
            with self.store._lock:
                self.store.rerender_targets[(tenant, job_id, stage, shot_sequence, profile)] = deepcopy(target)
            self._event("asset.render_shot_rerendered", tenant=tenant, job=updated, actor=actor, trace=trace,
                        key=key, occurred_at=_stamp(at), payload={"from_state": job.get("status"), "to_state": job.get("status"),
                                                                              "command": "rerender_shot", "stage": stage, "shot_sequence": shot_sequence,
                                                                              "artifact_id": artifact["id"]})
            self.store.audit.append({"operation": "rerender_shot", "org_id": tenant, "job_id": job_id, "status": "succeeded",
                                     "stage": stage, "shot_sequence": shot_sequence, "output_hash": body_hash,
                                     "actor_id": actor, "trace_id": trace, "idempotency_key": key,
                                     "expected_version": current_version, "created_at": _stamp(at)})
            response = {"operation": "rerender_shot", "status": "succeeded", "code": None, "duplicate": False,
                        "render_job": updated, "failure": None, "schedule": None, "shot_target": target,
                        "artifact": artifact, "human_task": None, "next_retry_at": None}
            return self._save_command(tenant=tenant, namespace="rerender_shot", key=key, request_hash=request_hash, response=response)
        except MediaRenderRetryError:
            raise
        except MediaRenderError:
            raise
        except Exception as exc:
            raise MediaRenderRetryError("RENDER_RESULT_UNKNOWN", "shot renderer result is unknown") from exc

    rerender_single_shot = rerender_shot
    rerender = rerender_shot

    def dead_letter(self, *, media_render_job_id: Any, org_id: Any = None, tenant_context: Any = None,
                    actor_id: Any = None, trace_id: str = "media-render-dead-letter", idempotency_key: str,
                    reason: str = "manual dead-letter", expected_version: int | None = None,
                    occurred_at: Any | None = None, force: bool = False) -> dict[str, Any]:
        tenant, actor = _context(org_id=org_id, actor_id=actor_id, tenant_context=tenant_context)
        trace_id = _text(trace_id, "trace_id", 256)
        idempotency_key = _text(idempotency_key, "idempotency_key", 200)
        job_id = _uuid(media_render_job_id, "media_render_job_id")
        reason = _text(reason, "reason", 256)
        at = self._now(occurred_at, "occurred_at")
        job = self._job(tenant, job_id)
        request_hash = _hash({"operation": "dead_letter", "job_id": job_id, "reason": reason, "force": force, "expected_version": expected_version})
        replay = self._command_replay(tenant=tenant, namespace="dead_letter", key=idempotency_key, request_hash=request_hash)
        if replay is not None:
            return replay
        current_version = self._expected_version(tenant, job_id, expected_version)
        if job.get("status") == "succeeded" or job.get("artifacts"):
            raise MediaRenderRetryError("RENDER_JOB_ALREADY_CONFIRMED", "confirmed render artifacts cannot be dead-lettered")
        if job.get("status") == "unknown" and not force:
            raise MediaRenderRetryError("UNKNOWN_RESULT_REQUIRES_REVIEW", "unknown result requires manual resolution")
        if not force and int(job.get("attempt_count", 0)) < int(job.get("max_attempts", self.policy.max_attempts)):
            raise MediaRenderRetryError("MAX_ATTEMPTS_NOT_REACHED", "render retry limit has not been reached")
        updated = deepcopy(job)
        updated.update({"status": "dead_letter", "failure_code": "MAX_ATTEMPTS_EXCEEDED", "dead_letter_reason": reason,
                        "next_retry_at": None, "updated_at": _stamp(at), "max_attempts": int(job.get("max_attempts", self.policy.max_attempts))})
        self.store.save(org_id=tenant, job=updated)
        self.store.bump_version(org_id=tenant, job_id=job_id)
        self._event("asset.render_dead_lettered", tenant=tenant, job=updated, actor=actor, trace=trace_id,
                    key=idempotency_key, occurred_at=_stamp(at), payload={"from_state": job.get("status"), "to_state": "dead_letter", "command": "dead_letter", "reason": reason})
        self.store.audit.append({"operation": "dead_letter_render_job", "org_id": tenant, "job_id": job_id, "status": "dead_letter",
                                 "reason": reason, "actor_id": actor, "trace_id": trace_id, "idempotency_key": idempotency_key,
                                 "expected_version": current_version, "created_at": _stamp(at)})
        result = {"operation": "dead_letter", "status": "dead_letter", "code": "MAX_ATTEMPTS_EXCEEDED", "duplicate": False,
                  "render_job": updated, "failure": None, "schedule": None, "shot_target": None, "artifact": None,
                  "human_task": None, "next_retry_at": None}
        return self._save_command(tenant=tenant, namespace="dead_letter", key=idempotency_key, request_hash=request_hash, response=result)

    mark_dead_letter = dead_letter
    dead_letter_render_job = dead_letter
    schedule_retry = record_failure
    handle_failure = record_failure
    record_render_failure = record_failure

    def resolve_unknown(self, *, media_render_job_id: Any, outcome: str, evidence_ref: str,
                        org_id: Any = None, tenant_context: Any = None, actor_id: Any = None,
                        trace_id: str = "media-render-unknown-resolve", idempotency_key: str,
                        expected_version: int | None = None, resolved_at: Any | None = None) -> dict[str, Any]:
        """Close an unknown result with human evidence without calling a renderer."""
        tenant, actor = _context(org_id=org_id, actor_id=actor_id, tenant_context=tenant_context)
        trace = _text(trace_id, "trace_id", 256)
        key = _text(idempotency_key, "idempotency_key", 200)
        outcome = _text(outcome, "outcome", 32)
        if outcome not in {"succeeded", "failed", "dead_letter"}:
            raise MediaRenderRetryError("INVALID_UNKNOWN_RESOLUTION", "outcome must be succeeded, failed or dead_letter")
        try:
            evidence = _text(evidence_ref, "evidence_ref", 512)
        except MediaRenderError as exc:
            raise MediaRenderRetryError("INVALID_UNKNOWN_RESOLUTION", str(exc)) from exc
        at = self._now(resolved_at, "resolved_at")
        job_id = _uuid(media_render_job_id, "media_render_job_id")
        job = self._job(tenant, job_id)
        request_hash = _hash({"operation": "resolve_unknown", "job_id": job_id, "outcome": outcome, "evidence_ref": evidence, "expected_version": expected_version})
        replay = self._command_replay(tenant=tenant, namespace="resolve_unknown", key=key, request_hash=request_hash)
        if replay is not None:
            return replay
        current_version = self._expected_version(tenant, job_id, expected_version)
        if job.get("status") != "unknown":
            raise MediaRenderRetryError("UNKNOWN_RESOLUTION_REQUIRED", "render job is not awaiting unknown resolution")
        if outcome == "succeeded" and not job.get("artifacts"):
            raise MediaRenderRetryError("ARTIFACT_REQUIRED_FOR_SUCCESS", "manual success requires a confirmed artifact")
        updated = deepcopy(job)
        updated["status"] = outcome
        updated["failure_code"] = None if outcome == "succeeded" else ("MANUAL_UNKNOWN_FAILED" if outcome == "failed" else "MANUAL_DEAD_LETTER")
        updated["dead_letter_reason"] = evidence if outcome == "dead_letter" else None
        updated["next_retry_at"] = None
        updated["updated_at"] = _stamp(at)
        self.store.save(org_id=tenant, job=updated)
        self.store.bump_version(org_id=tenant, job_id=job_id)
        with self.store._lock:
            for task_key, task in self.store.human_tasks.items():
                if task_key[0] == tenant and task_key[1] == job_id and task.get("task_type") == "unknown_result":
                    task["status"] = "completed"
                    task["completed_by"] = actor
                    task["completed_at"] = _stamp(at)
                    task["result"] = {"outcome": outcome, "evidence_ref": evidence}
        self._event("asset.render_unknown_resolved", tenant=tenant, job=updated, actor=actor, trace=trace,
                    key=key, occurred_at=_stamp(at), payload={"from_state": "unknown", "to_state": outcome,
                                                               "command": "resolve_unknown", "reason": evidence})
        self.store.audit.append({"operation": "resolve_unknown_render_job", "org_id": tenant, "job_id": job_id,
                                 "status": outcome, "evidence_ref": evidence, "actor_id": actor, "trace_id": trace,
                                 "idempotency_key": key, "expected_version": current_version, "created_at": _stamp(at)})
        result = {"operation": "resolve_unknown", "status": outcome, "code": None, "duplicate": False,
                  "render_job": updated, "failure": None, "schedule": None, "shot_target": None, "artifact": None,
                  "human_task": None, "next_retry_at": None, "evidence_ref": evidence}
        return self._save_command(tenant=tenant, namespace="resolve_unknown", key=key, request_hash=request_hash, response=result)

    resolve = resolve_unknown
    resolve_unknown_result = resolve_unknown

    def worker_handler(self, task_job: Any, context: Any) -> dict[str, Any] | None:
        if hasattr(context, "checkpoint"):
            context.checkpoint()
        job_id = getattr(task_job, "aggregate_id", None) or getattr(task_job, "render_job_id", None) or getattr(task_job, "id", None)
        org_id = getattr(task_job, "org_id", None)
        job_type = str(getattr(task_job, "job_type", "media.render.retry"))
        if job_type in {"media.render.rerender_shot", "render.rerender_shot"}:
            payload = getattr(task_job, "payload", None) or getattr(task_job, "payload_json", None) or {}
            if isinstance(payload, str):
                payload = json.loads(payload)
            result = self.rerender_shot(media_render_job_id=job_id, org_id=org_id, actor_id=None,
                                        trace_id=getattr(task_job, "trace_id", "media-render-worker"),
                                        idempotency_key=str(payload.get("idempotency_key") or getattr(task_job, "id", job_id)),
                                        stage=payload["stage"], shot_sequence=payload["shot_sequence"], profile_key=payload.get("profile_key"))
        else:
            result = self.retry_due(media_render_job_id=job_id, org_id=org_id, actor_id=None,
                                    trace_id=getattr(task_job, "trace_id", "media-render-worker"),
                                    idempotency_key=str(getattr(task_job, "id", f"retry:{job_id}")),
                                    now=getattr(task_job, "now", None))
        if hasattr(context, "checkpoint"):
            context.checkpoint()
        return result if isinstance(result, dict) else None


MediaRenderRetryJobService = MediaRenderRetryService
RenderFailureService = MediaRenderRetryService
RenderRetryService = MediaRenderRetryService


__all__ = [
    "MediaRenderRetryError", "RenderRetryError", "RenderRetryPolicy", "RetryPolicy", "RenderFailure",
    "RenderRetryDecision", "MediaRenderRetryService", "MediaRenderRetryJobService", "RenderFailureService", "RenderRetryService",
]
