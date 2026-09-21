"""Credential-free FakeOfficialAdapter for DIST-004."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker

from .service import DistributionError, _EVENT_VALIDATOR, _hash, _stamp, _text, _time, _uuid, _validate


_ROOT = Path(__file__).resolve().parents[2]
_CAPABILITY_VALIDATOR = Draft202012Validator(
    json.loads((_ROOT / "packages/contracts/jsonschema/publisher-capability.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
_ERROR_CODES = {
    "CAPABILITY_NOT_FOUND", "DRAFT_NOT_FOUND", "DRAFT_VERSION_CONFLICT", "UPLOAD_NOT_ALLOWED",
    "SCHEDULE_INVALID", "NOT_READY", "ALREADY_PUBLISHED", "PLATFORM_RATE_LIMITED", "PLATFORM_UNAVAILABLE",
    "INVALID_FAKE_REQUEST",
}


class FakeOfficialError(DistributionError):
    """Stable deterministic fake platform error."""


def _default_capability(platform_id: str) -> dict[str, Any]:
    return {
        "id": "00000000-0000-4000-8000-0000000000f4", "platform_id": platform_id, "version": 1,
        "actions": ["draft", "upload", "schedule", "publish", "metrics"], "limits": {},
        "policy_version": "fake-official-v1", "status": "active", "created_at": "2026-09-19T00:00:00Z",
    }


class FakeOfficialAdapter:
    """Simulate official publishing state transitions without credentials or HTTP."""

    adapter_ref = "fake:official@v1"
    provider_mode = "fake"

    def __init__(self, *, platform_id: UUID | str = "00000000-0000-4000-8000-000000000003",
                 capability: Mapping[str, Any] | None = None) -> None:
        self.platform_id = _uuid(platform_id, "platform_id")
        self.capability_snapshot = deepcopy(dict(capability or _default_capability(self.platform_id)))
        errors = list(_CAPABILITY_VALIDATOR.iter_errors(self.capability_snapshot))
        if errors:
            raise FakeOfficialError("INVALID_CAPABILITY", errors[0].message)
        self.drafts: dict[tuple[str, str], dict[str, Any]] = {}
        self.attempts: dict[tuple[str, str], dict[str, Any]] = {}
        self.records: dict[tuple[str, str], dict[str, Any]] = {}
        self.metrics: dict[tuple[str, str], dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self._commands: dict[tuple[str, str], tuple[str, Any]] = {}
        self._failures: dict[str, str] = {}
        self._lock = RLock()

    def get_capability(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
                       idempotency_key: str) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        digest = _hash({"operation": "get_capability", "platform_id": self.platform_id})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            value = deepcopy(self.capability_snapshot)
            self._commands[(tenant, key)] = (digest, deepcopy(value))
            self._audit("fake.capability.read", tenant, actor, trace, key, digest, value)
            return value

    def create_draft(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        publication_intent: Mapping[str, Any], policy_snapshot_id: UUID | str,
        execution_policy_decision_id: UUID | str, environment: str = "dev",
        content: Mapping[str, Any] | None = None, created_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        if not isinstance(publication_intent, Mapping) or publication_intent.get("org_id") != tenant:
            raise FakeOfficialError("TENANT_SCOPE_VIOLATION", "publication intent is outside this organization")
        intent_id = _uuid(publication_intent.get("id"), "publication_intent.id")
        policy, decision = _uuid(policy_snapshot_id, "policy_snapshot_id"), _uuid(execution_policy_decision_id, "execution_policy_decision_id")
        if environment not in {"dev", "staging", "prod"}:
            raise FakeOfficialError("INVALID_FAKE_REQUEST", "environment is invalid")
        payload = deepcopy(dict(content if content is not None else publication_intent.get("payload_snapshot", {})))
        if not isinstance(payload.get("title"), str) or not payload["title"].strip() or not isinstance(payload.get("body"), Mapping):
            raise FakeOfficialError("INVALID_FAKE_REQUEST", "draft content requires title and body")
        now = _time(created_at, "created_at") or datetime.now(timezone.utc)
        digest = _hash({"operation": "create_draft", "intent": publication_intent, "policy": policy,
                        "decision": decision, "environment": environment, "content": payload, "created_at": _stamp(now)})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            draft_id = str(uuid4())
            draft = {
                "id": draft_id, "org_id": tenant, "publication_intent_id": intent_id,
                "status": "draft", "version": 1, "content": payload, "media": [],
                "policy_snapshot_id": policy, "execution_policy_decision_id": decision,
                "environment": environment, "created_at": _stamp(now), "scheduled_at": None,
            }
            self.drafts[(tenant, draft_id)] = deepcopy(draft)
            self._commands[(tenant, key)] = (digest, deepcopy(draft))
            self._audit("fake.draft.created", tenant, actor, trace, key, digest, draft)
            self._event("distribution.draft.created", tenant, actor, trace, key, draft_id, {"status": "draft"}, now)
            return deepcopy(draft)

    def upload_media(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        draft_id: UUID | str, media: Mapping[str, Any], expected_version: int,
    ) -> dict[str, Any]:
        tenant, actor, identity = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id"), _uuid(draft_id, "draft_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        if not isinstance(media, Mapping) or not isinstance(media.get("asset_version_id"), (str, UUID)):
            raise FakeOfficialError("INVALID_FAKE_REQUEST", "media requires asset_version_id")
        asset = _uuid(media["asset_version_id"], "media.asset_version_id")
        source = media.get("storage_object_ref")
        if not isinstance(source, str) or not source.startswith("private://"):
            raise FakeOfficialError("UPLOAD_NOT_ALLOWED", "fake media upload requires private source")
        digest = _hash({"operation": "upload_media", "draft_id": identity, "asset_version_id": asset,
                        "storage_object_ref": source, "expected_version": expected_version})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            draft = self._get_draft(tenant, identity)
            self._check_failure(tenant)
            if draft["status"] != "draft":
                raise FakeOfficialError("UPLOAD_NOT_ALLOWED", "media can only be uploaded to a draft")
            if draft["version"] != expected_version:
                raise FakeOfficialError("DRAFT_VERSION_CONFLICT", "draft version does not match expected_version")
            draft["media"].append({"asset_version_id": asset, "storage_object_ref": source, "external_object_id": f"fake-media-{_hash(asset)[:12]}"})
            draft["version"] += 1
            self._commands[(tenant, key)] = (digest, deepcopy(draft))
            self._audit("fake.media.uploaded", tenant, actor, trace, key, digest, draft)
            self._event("distribution.media.uploaded", tenant, actor, trace, key, identity, {"version": draft["version"], "asset_version_id": asset}, _time(draft["created_at"], "created_at", required=True))
            return deepcopy(draft)

    def schedule(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        draft_id: UUID | str, expected_version: int, scheduled_at: datetime | str,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        tenant, actor, identity = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id"), _uuid(draft_id, "draft_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        scheduled = _time(scheduled_at, "scheduled_at", required=True)
        check = _time(now, "now") or datetime.now(timezone.utc)
        if scheduled <= check:
            raise FakeOfficialError("SCHEDULE_INVALID", "scheduled_at must be in the future")
        digest = _hash({"operation": "schedule", "draft_id": identity, "expected_version": expected_version, "scheduled_at": _stamp(scheduled)})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            draft = self._get_draft(tenant, identity)
            self._check_failure(tenant)
            if draft["version"] != expected_version:
                raise FakeOfficialError("DRAFT_VERSION_CONFLICT", "draft version does not match expected_version")
            if draft["status"] not in {"draft", "scheduled"}:
                raise FakeOfficialError("SCHEDULE_INVALID", "published draft cannot be scheduled")
            draft.update({"status": "scheduled", "scheduled_at": _stamp(scheduled), "version": draft["version"] + 1})
            self._commands[(tenant, key)] = (digest, deepcopy(draft))
            self._audit("fake.draft.scheduled", tenant, actor, trace, key, digest, draft)
            self._event("distribution.draft.scheduled", tenant, actor, trace, key, identity, {"status": "scheduled", "scheduled_at": draft["scheduled_at"]}, check)
            return deepcopy(draft)

    def publish(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        draft_id: UUID | str, expected_version: int, published_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        tenant, actor, identity = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id"), _uuid(draft_id, "draft_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        at = _time(published_at, "published_at") or datetime.now(timezone.utc)
        digest = _hash({"operation": "publish", "draft_id": identity, "expected_version": expected_version, "published_at": _stamp(at)})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            draft = self._get_draft(tenant, identity)
            self._check_failure(tenant)
            if draft["version"] != expected_version:
                raise FakeOfficialError("DRAFT_VERSION_CONFLICT", "draft version does not match expected_version")
            if draft["status"] == "scheduled" and draft["scheduled_at"] is not None and at < _time(draft["scheduled_at"], "scheduled_at", required=True):
                raise FakeOfficialError("NOT_READY", "scheduled draft is not ready to publish")
            if draft["status"] == "published":
                raise FakeOfficialError("ALREADY_PUBLISHED", "draft is already published")
            if draft["status"] not in {"draft", "scheduled"}:
                raise FakeOfficialError("NOT_READY", "draft is not publishable")
            attempt_no = 1
            external_request = f"fake-request-{_hash({'draft_id': identity, 'version': expected_version})[:16]}"
            external_object = f"fake-official-{_hash({'draft_id': identity, 'version': expected_version})[:16]}"
            attempt = {
                "id": str(uuid4()), "org_id": tenant, "publication_intent_id": draft["publication_intent_id"],
                "account_connection_id": None, "adapter_ref": self.adapter_ref, "provider_mode": "fake",
                "environment": draft["environment"], "policy_snapshot_id": draft["policy_snapshot_id"],
                "execution_policy_decision_id": draft["execution_policy_decision_id"], "adapter_version": "v1",
                "capability_snapshot": {}, "idempotency_key": key, "provider_idempotency_key": external_request,
                "attempt_no": attempt_no, "parent_attempt_id": None, "status": "succeeded", "retryable": False,
                "next_attempt_at": None, "max_attempts": 1, "started_at": _stamp(at), "completed_at": _stamp(at),
                "external_request_id": external_request, "external_object_id": external_object,
                "account_connection_snapshot": {}, "error_class": None, "last_error_code": None, "last_error_at": None,
                "resolution_reason": None, "resolved_by": None, "resolved_at": None, "created_at": _stamp(at),
            }
            record = {
                "id": str(uuid4()), "org_id": tenant, "publication_intent_id": draft["publication_intent_id"],
                "delivery_attempt_id": attempt["id"], "provider_mode": "fake", "external_request_id": external_request,
                "external_object_id": external_object, "external_url": f"private://fake-official/{tenant}/{external_object}",
                "status": "published", "result_snapshot": {"simulated": True, "replay_input_hash": _hash(draft), "attempt_no": attempt_no},
                "observed_at": _stamp(at), "last_observed_at": _stamp(at), "observation_source": "adapter",
                "unknown_reason": None, "resolution_reason": None, "resolved_by": None, "resolved_at": None,
                "resolution_evidence_ref": None,
            }
            _validate("delivery-attempt", attempt)
            _validate("publication-record", record)
            draft.update({"status": "published", "version": draft["version"] + 1, "published_at": _stamp(at), "external_object_id": external_object})
            self.attempts[(tenant, identity)] = deepcopy(attempt)
            self.records[(tenant, identity)] = deepcopy(record)
            self.metrics[(tenant, identity)] = {"views": 0, "likes": 0, "shares": 0, "observed_at": _stamp(at)}
            result = {"draft": deepcopy(draft), "delivery_attempt": deepcopy(attempt), "publication_record": deepcopy(record), "metrics": deepcopy(self.metrics[(tenant, identity)])}
            self._commands[(tenant, key)] = (digest, deepcopy(result))
            self._audit("fake.publication.published", tenant, actor, trace, key, digest, record)
            self._event("publication.recorded", tenant, actor, trace, key, draft["publication_intent_id"], {"external_object_id": external_object, "simulated": True}, at)
            return deepcopy(result)

    def get_metrics(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
                    draft_id: UUID | str) -> dict[str, Any]:
        tenant, actor, identity = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id"), _uuid(draft_id, "draft_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        digest = _hash({"operation": "metrics", "draft_id": identity})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            self._get_draft(tenant, identity)
            if (tenant, identity) not in self.metrics:
                raise FakeOfficialError("NOT_READY", "metrics are available after simulated publication")
            result = deepcopy(self.metrics[(tenant, identity)])
            self._commands[(tenant, key)] = (digest, deepcopy(result))
            self._audit("fake.metrics.read", tenant, actor, trace, key, digest, result)
            return result

    def fail_next(self, *, org_id: UUID | str, error_code: str) -> None:
        tenant = _uuid(org_id, "org_id")
        if error_code not in _ERROR_CODES:
            raise FakeOfficialError("INVALID_FAKE_REQUEST", "unknown fake error code")
        self._failures[tenant] = error_code

    def _check_failure(self, tenant: str) -> None:
        code = self._failures.pop(tenant, None)
        if code is not None:
            raise FakeOfficialError(code, f"fake official adapter simulated {code}")

    def _get_draft(self, tenant: str, identity: str) -> dict[str, Any]:
        draft = self.drafts.get((tenant, identity))
        if draft is None:
            raise FakeOfficialError("TENANT_SCOPE_VIOLATION", "draft is not available in organization")
        return draft

    def _prior(self, tenant: str, key: str, digest: str) -> Any | None:
        prior = self._commands.get((tenant, key))
        if prior is None:
            return None
        if prior[0] != digest:
            raise FakeOfficialError("IDEMPOTENCY_KEY_REUSED", "fake adapter command differs from prior request")
        return deepcopy(prior[1])

    def _audit(self, event_type: str, tenant: str, actor: str, trace: str, key: str, digest: str, output: Mapping[str, Any]) -> None:
        self.audit.append({"event_type": event_type, "org_id": tenant, "actor_id": actor, "trace_id": trace,
                           "idempotency_key": key, "input_hash": digest, "output_hash": _hash(output)})

    def _event(self, event_type: str, tenant: str, actor: str, trace: str, key: str, aggregate_id: str,
               payload: Mapping[str, Any], occurred_at: datetime) -> None:
        event_payload = {"aggregate_id": aggregate_id, "aggregate_version": 1, **dict(payload)}
        event = {"event_id": str(uuid4()), "event_type": event_type, "event_schema_version": 1,
                 "occurred_at": _stamp(occurred_at), "org_id": tenant, "trace_id": trace,
                 "aggregate_type": "publication_intent", "aggregate_id": aggregate_id, "aggregate_version": 1,
                 "actor_type": "service", "actor_id": actor, "idempotency_key": key,
                 "payload": event_payload, "payload_hash": _hash(event_payload)}
        errors = list(_EVENT_VALIDATOR.iter_errors(event))
        if errors:
            raise FakeOfficialError("INVALID_FAKE_EVENT", errors[0].message)
        self.events.append(event)


__all__ = ["FakeOfficialAdapter", "FakeOfficialError"]
