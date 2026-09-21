"""Tenant-scoped human approval desk projections for APPROVAL-001."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Protocol, Sequence
from uuid import UUID, uuid4
from hashlib import sha256

from jsonschema import Draft202012Validator, FormatChecker


_ROOT = Path(__file__).resolve().parents[2]
_APPROVAL_VALIDATOR = Draft202012Validator(
    json.loads((_ROOT / "packages/contracts/jsonschema/approval.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
_DECISION_VALIDATOR = Draft202012Validator(
    json.loads((_ROOT / "packages/contracts/jsonschema/approval-decision.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
_AGGREGATES = {"canonical", "variant", "asset", "publication_intent", "rights_version"}
_APPROVAL_TYPES = {"content", "asset", "distribution", "rights"}


class ApprovalError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ReviewerAuthorizationPort(Protocol):
    def authorize(self, *, org_id: str, reviewer_id: str, approval: Mapping[str, Any]) -> bool: ...


def _hash(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _uuid(value: UUID | str, name: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise ApprovalError("INVALID_APPROVAL_INPUT", f"{name} must be a UUID") from exc


def _text(value: object, name: str, limit: int = 2048) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise ApprovalError("INVALID_APPROVAL_INPUT", f"{name} must be nonempty text")
    return value.strip()


def _time(value: Any, name: str, *, required: bool = False) -> datetime | None:
    if value is None:
        if required:
            raise ApprovalError("INVALID_APPROVAL_INPUT", f"{name} is required")
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ApprovalError("INVALID_APPROVAL_INPUT", f"{name} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ApprovalError("INVALID_APPROVAL_INPUT", f"{name} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _diff(before: Any, after: Any, path: str = "") -> list[dict[str, Any]]:
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        changes: list[dict[str, Any]] = []
        for key in sorted(set(before) | set(after)):
            child = f"{path}/{key}" if path else f"/{key}"
            if key not in before:
                changes.append({"path": child, "operation": "add", "before": None, "after": deepcopy(after[key])})
            elif key not in after:
                changes.append({"path": child, "operation": "remove", "before": deepcopy(before[key]), "after": None})
            else:
                changes.extend(_diff(before[key], after[key], child))
        return changes
    if isinstance(before, list) and isinstance(after, list):
        if before == after:
            return []
        return [{"path": path or "/", "operation": "replace", "before": deepcopy(before), "after": deepcopy(after)}]
    if before != after:
        return [{"path": path or "/", "operation": "replace", "before": deepcopy(before), "after": deepcopy(after)}]
    return []


class ApprovalDeskService:
    """Create and review immutable approval projections with an auditable desk view."""

    def __init__(self, *, reviewer_authorizer: ReviewerAuthorizationPort | None = None) -> None:
        self.reviewer_authorizer = reviewer_authorizer
        self.audit: list[dict[str, Any]] = []
        self._approvals: dict[tuple[str, str], dict[str, Any]] = {}
        self._metadata: dict[tuple[str, str], dict[str, Any]] = {}
        self._versions: dict[tuple[str, str], int] = {}
        self._commands: dict[tuple[str, str], tuple[str, Any]] = {}
        self._lock = RLock()

    def request(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        aggregate_type: str, aggregate_id: UUID | str, aggregate_version: int, approval_type: str,
        policy_snapshot_id: UUID | str, evidence_refs: Sequence[UUID | str] = (),
        input_snapshot: Mapping[str, Any] | None = None, previous_snapshot: Mapping[str, Any] | None = None,
        current_snapshot: Mapping[str, Any] | None = None, risk_reasons: Sequence[str] = (),
        evidence_panel: Sequence[Mapping[str, Any]] = (), comments: Sequence[str] = (),
        assigned_to: UUID | str | None = None, quorum_required: int = 1,
        risk_level: str | None = None,
        expires_at: datetime | str | None = None, override_expires_at: datetime | str | None = None,
        created_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        if aggregate_type not in _AGGREGATES or approval_type not in _APPROVAL_TYPES:
            raise ApprovalError("INVALID_APPROVAL_INPUT", "aggregate_type or approval_type is invalid")
        aggregate = _uuid(aggregate_id, "aggregate_id")
        policy = _uuid(policy_snapshot_id, "policy_snapshot_id")
        if type(aggregate_version) is not int or aggregate_version < 1:
            raise ApprovalError("INVALID_APPROVAL_INPUT", "aggregate_version must be positive")
        if quorum_required not in {1, 2}:
            raise ApprovalError("INVALID_APPROVAL_INPUT", "quorum_required must be 1 or 2")
        risk_level = str(risk_level or next((item for item in risk_reasons if str(item) in {"R0", "R1", "R2", "R3", "R4"}), ""))
        if risk_level not in {"", "R0", "R1", "R2", "R3", "R4"}:
            raise ApprovalError("INVALID_APPROVAL_INPUT", "risk_level is invalid")
        if risk_level in {"R3", "R4"}:
            quorum_required = 2
        evidence = [_uuid(value, "evidence_ref") for value in evidence_refs]
        if len(set(evidence)) != len(evidence):
            raise ApprovalError("INVALID_APPROVAL_INPUT", "evidence_refs must be unique")
        payload = deepcopy(dict(input_snapshot or {}))
        assigned = None if assigned_to is None else _uuid(assigned_to, "assigned_to")
        expires = _time(expires_at, "expires_at")
        override = _time(override_expires_at, "override_expires_at")
        now = _time(created_at, "created_at") or datetime.now(timezone.utc)
        if expires is not None and expires <= now:
            status = "expired"
        else:
            status = "pending"
        if override is not None and override <= now:
            raise ApprovalError("INVALID_OVERRIDE_EXPIRY", "override_expires_at must be in the future")
        request_payload = {
            "aggregate_type": aggregate_type, "aggregate_id": aggregate, "aggregate_version": aggregate_version,
            "approval_type": approval_type, "policy_snapshot_id": policy, "evidence_refs": evidence,
            "input_snapshot": payload, "previous_snapshot": previous_snapshot, "current_snapshot": current_snapshot,
            "risk_reasons": list(risk_reasons), "evidence_panel": list(evidence_panel), "comments": list(comments),
            "assigned_to": assigned, "quorum_required": quorum_required, "expires_at": _stamp(expires) if expires else None,
            "risk_level": risk_level,
            "override_expires_at": _stamp(override) if override else None,
            "created_at": _stamp(_time(created_at, "created_at")) if created_at is not None else None,
        }
        request_hash = _hash(request_payload)
        with self._lock:
            prior = self._commands.get((tenant, key))
            if prior is not None:
                if prior[0] != request_hash:
                    raise ApprovalError("IDEMPOTENCY_KEY_REUSED", "approval request differs from prior request")
                return deepcopy(prior[1])
            approval_id = str(uuid4())
            approval: dict[str, Any] = {
                "id": approval_id, "org_id": tenant, "aggregate_type": aggregate_type, "aggregate_id": aggregate,
                "aggregate_version": aggregate_version, "approval_type": approval_type, "status": status,
                "requested_by": actor, "reviewer_id": None, "decision": None, "policy_snapshot_id": policy,
                "evidence_refs": evidence, "input_snapshot_hash": _hash(payload), "quorum_required": quorum_required,
                "quorum_reached": 0, "decision_ids": [], "reason": None,
                "expires_at": _stamp(expires) if expires else None,
                "created_at": _stamp(now), "decided_at": None,
            }
            self._validate_approval(approval)
            self._approvals[(tenant, approval_id)] = approval
            self._versions[(tenant, approval_id)] = 1
            self._metadata[(tenant, approval_id)] = {
                "diff": _diff(previous_snapshot or {}, current_snapshot or payload),
                "evidence_panel": deepcopy(list(evidence_panel)), "risk_reasons": sorted(set(str(item) for item in risk_reasons)),
                "comments": [{"id": str(uuid4()), "author_id": actor, "body": _text(item, "comment"), "created_at": _stamp(now)} for item in comments],
                "assigned_to": assigned, "input_snapshot": payload,
                "override_expires_at": _stamp(override) if override else None,
                "risk_level": risk_level,
            }
            if status == "expired":
                approval["reason"] = "APPROVAL_EXPIRED"
            self._commands[(tenant, key)] = (request_hash, deepcopy(approval))
            self._record("approval.requested", tenant, actor, trace, key, request_hash, approval)
            return deepcopy(approval)

    def assign(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
               approval_id: UUID | str, assigned_to: UUID | str | None, expected_version: int) -> dict[str, Any]:
        tenant, actor, identity = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id"), _uuid(approval_id, "approval_id")
        assignee = None if assigned_to is None else _uuid(assigned_to, "assigned_to")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        digest = _hash({"operation": "assign", "approval_id": identity, "assigned_to": assignee,
                        "expected_version": expected_version})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            approval = self._get(tenant, identity)
            self._check_version(tenant, identity, expected_version)
            if approval["status"] != "pending":
                raise ApprovalError("APPROVAL_NOT_PENDING", "only pending approvals can be assigned")
            approval_version = self._versions[(tenant, identity)]
            self._metadata[(tenant, identity)]["assigned_to"] = assignee
            self._versions[(tenant, identity)] = approval_version + 1
            self._record("approval.assigned", tenant, actor, trace, key, digest, approval)
            self._commands[(tenant, key)] = (digest, deepcopy(approval))
            return deepcopy(approval)

    def comment(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
                approval_id: UUID | str, body: str, expected_version: int) -> dict[str, Any]:
        tenant, actor, identity = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id"), _uuid(approval_id, "approval_id")
        trace, key, text = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200), _text(body, "body")
        digest = _hash({"operation": "comment", "approval_id": identity, "body": text,
                        "expected_version": expected_version})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            approval = self._get(tenant, identity)
            self._check_version(tenant, identity, expected_version)
            if approval["status"] not in {"pending", "approved"}:
                raise ApprovalError("APPROVAL_CLOSED", "closed approval cannot receive comments")
            self._metadata[(tenant, identity)]["comments"].append({"id": str(uuid4()), "author_id": actor, "body": text,
                                                                     "created_at": _stamp(datetime.now(timezone.utc))})
            self._versions[(tenant, identity)] += 1
            self._record("approval.comment.added", tenant, actor, trace, key, digest, approval)
            self._commands[(tenant, key)] = (digest, deepcopy(approval))
            return deepcopy(approval)

    def decide(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
               approval_id: UUID | str, reviewer_id: UUID | str, decision: str, reason: str | None,
               expected_version: int, override_expires_at: datetime | str | None = None,
               decided_at: datetime | str | None = None) -> dict[str, Any]:
        tenant, actor, identity = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id"), _uuid(approval_id, "approval_id")
        reviewer = _uuid(reviewer_id, "reviewer_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        if decision not in {"approved", "rejected", "withdrawn"}:
            raise ApprovalError("INVALID_APPROVAL_DECISION", "decision is invalid")
        if decision in {"rejected", "withdrawn"} and (reason is None or not str(reason).strip()):
            raise ApprovalError("DECISION_REASON_REQUIRED", "rejection and withdrawal require a reason")
        at = _time(decided_at, "decided_at") or datetime.now(timezone.utc)
        override = _time(override_expires_at, "override_expires_at")
        digest = _hash({"operation": "decide", "approval_id": identity, "reviewer_id": reviewer,
                        "decision": decision, "reason": reason, "expected_version": expected_version,
                        "override_expires_at": _stamp(override) if override else None,
                        "decided_at": _stamp(_time(decided_at, "decided_at")) if decided_at is not None else None})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            approval = self._get(tenant, identity)
            self._expire_locked(tenant, identity, at)
            self._check_version(tenant, identity, expected_version)
            if approval["status"] != "pending":
                raise ApprovalError("APPROVAL_NOT_PENDING", "only pending approvals can be decided")
            if reviewer == approval["requested_by"]:
                raise ApprovalError("SELF_APPROVAL_FORBIDDEN", "requester cannot approve its own request")
            if self.reviewer_authorizer is not None:
                try:
                    authorized = self.reviewer_authorizer.authorize(org_id=tenant, reviewer_id=reviewer, approval=approval)
                except Exception as exc:
                    raise ApprovalError("FORBIDDEN", "reviewer authorization failed") from exc
                if authorized is not True:
                    raise ApprovalError("FORBIDDEN", "reviewer role is not authorized")
            prior_reviewers = self._metadata[(tenant, identity)].setdefault("reviewers", set())
            if reviewer in prior_reviewers:
                raise ApprovalError("REVIEWER_ALREADY_DECIDED", "reviewer already decided")
            if override is not None and override <= at:
                raise ApprovalError("INVALID_OVERRIDE_EXPIRY", "override_expires_at must be in the future")
            decision_record = {
                "id": str(uuid4()), "org_id": tenant, "approval_id": identity, "reviewer_id": reviewer,
                "decision": decision, "reason": None if reason is None else str(reason).strip(),
                "input_snapshot_hash": approval["input_snapshot_hash"], "policy_snapshot_id": approval["policy_snapshot_id"],
                "created_at": _stamp(at),
            }
            decision_errors = list(_DECISION_VALIDATOR.iter_errors(decision_record))
            if decision_errors:
                raise ApprovalError("INVALID_APPROVAL_DECISION", decision_errors[0].message)
            prior_reviewers.add(reviewer)
            approval["decision_ids"].append(decision_record["id"])
            approval["quorum_reached"] = sum(1 for item in self._metadata[(tenant, identity)].get("decisions", []) if item["decision"] == "approved") + (1 if decision == "approved" else 0)
            self._metadata[(tenant, identity)].setdefault("decisions", []).append(decision_record)
            if decision == "rejected":
                approval.update({"status": "rejected", "decision": "rejected", "reviewer_id": reviewer, "reason": str(reason).strip(), "decided_at": _stamp(at)})
            elif decision == "withdrawn":
                approval.update({"status": "revoked", "decision": "withdrawn", "reviewer_id": reviewer, "reason": str(reason).strip(), "decided_at": _stamp(at)})
            elif approval["quorum_reached"] >= approval["quorum_required"]:
                approval.update({"status": "approved", "decision": "approved", "reviewer_id": reviewer, "reason": None, "decided_at": _stamp(at)})
                if override is not None:
                    self._metadata[(tenant, identity)]["override_expires_at"] = _stamp(override)
            self._validate_approval(approval)
            self._versions[(tenant, identity)] += 1
            self._record("approval.decided", tenant, actor, trace, key, digest, approval, decision_record=decision_record)
            self._commands[(tenant, key)] = (digest, deepcopy(approval))
            return deepcopy(approval)

    def expire(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
               approval_id: UUID | str, at: datetime | str | None = None) -> dict[str, Any]:
        tenant, actor, identity = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id"), _uuid(approval_id, "approval_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        now = _time(at, "at") or datetime.now(timezone.utc)
        digest = _hash({"operation": "expire", "approval_id": identity,
                        "at": _stamp(_time(at, "at")) if at is not None else None})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            approval = self._get(tenant, identity)
            changed = self._expire_locked(tenant, identity, now)
            self._record("approval.expired.checked", tenant, actor, trace, key, digest, approval, changed=changed)
            self._commands[(tenant, key)] = (digest, deepcopy(approval))
            return deepcopy(approval)

    def view(self, *, org_id: UUID | str, approval_id: UUID | str, at: datetime | str | None = None) -> dict[str, Any]:
        tenant, identity = _uuid(org_id, "org_id"), _uuid(approval_id, "approval_id")
        now = _time(at, "at") or datetime.now(timezone.utc)
        with self._lock:
            self._expire_locked(tenant, identity, now)
            approval = self._get(tenant, identity)
            metadata = deepcopy(self._metadata[(tenant, identity)])
            metadata.pop("input_snapshot", None)
            metadata["approval_version"] = self._versions[(tenant, identity)]
            if isinstance(metadata.get("reviewers"), set):
                metadata["reviewers"] = sorted(metadata["reviewers"])
            return {"approval": deepcopy(approval), **metadata}

    def _get(self, tenant: str, identity: str) -> dict[str, Any]:
        approval = self._approvals.get((tenant, identity))
        if approval is None:
            raise ApprovalError("TENANT_SCOPE_VIOLATION", "approval does not exist in this organization")
        return approval

    def _prior(self, tenant: str, key: str, digest: str) -> dict[str, Any] | None:
        prior = self._commands.get((tenant, key))
        if prior is None:
            return None
        if prior[0] != digest:
            raise ApprovalError("IDEMPOTENCY_KEY_REUSED", "approval command differs from prior request")
        return deepcopy(prior[1])

    def _check_version(self, tenant: str, identity: str, expected: int) -> None:
        if expected != self._versions[(tenant, identity)]:
            raise ApprovalError("STALE_APPROVAL_VERSION", "expected approval version does not match")

    def _expire_locked(self, tenant: str, identity: str, at: datetime) -> bool:
        approval = self._get(tenant, identity)
        changed = False
        expires = _time(approval.get("expires_at"), "expires_at")
        override = _time(self._metadata[(tenant, identity)].get("override_expires_at"), "override_expires_at")
        if approval["status"] == "pending" and expires is not None and at >= expires:
            approval.update({"status": "expired", "reason": "APPROVAL_EXPIRED", "decided_at": _stamp(at)})
            self._versions[(tenant, identity)] += 1
            changed = True
        elif approval["status"] == "approved" and override is not None and at >= override:
            approval.update({"status": "revoked", "reason": "OVERRIDE_EXPIRED", "decided_at": _stamp(at)})
            self._versions[(tenant, identity)] += 1
            changed = True
        if changed:
            self._validate_approval(approval)
        return changed

    def _validate_approval(self, approval: Mapping[str, Any]) -> None:
        errors = list(_APPROVAL_VALIDATOR.iter_errors(dict(approval)))
        if errors:
            raise ApprovalError("INVALID_APPROVAL", errors[0].message)

    def _record(self, event_type: str, tenant: str, actor: str, trace: str, key: str, digest: str,
                approval: Mapping[str, Any], **extra: Any) -> None:
        event = {"event_type": event_type, "org_id": tenant, "actor_id": actor, "trace_id": trace,
                 "idempotency_key": key, "input_hash": digest, "output_hash": _hash(approval),
                 "approval_id": approval["id"], "status": approval["status"], **extra}
        self.audit.append(event)


__all__ = ["ApprovalDeskService", "ApprovalError", "ReviewerAuthorizationPort"]
