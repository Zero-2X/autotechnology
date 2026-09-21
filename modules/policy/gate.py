"""Deterministic PolicySnapshot evaluation for POLICY-001."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Sequence
from hashlib import sha256
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker



class QAError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _hash(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _uuid(value: UUID | str, name: str) -> str:
    from uuid import UUID as UUIDType
    try:
        return str(UUIDType(str(value)))
    except (TypeError, ValueError) as exc:
        raise QAError("INVALID_POLICY_INPUT", f"{name} must be a UUID") from exc


def _text(value: object, name: str, limit: int = 256) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise QAError("INVALID_POLICY_INPUT", f"{name} must be nonempty text")
    return value.strip()


def _time(value: Any, field: str) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


_ROOT = Path(__file__).resolve().parents[2]
_SNAPSHOT_VALIDATOR = Draft202012Validator(
    json.loads((_ROOT / "packages/contracts/jsonschema/policy-snapshot.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
_DECISION_VALIDATOR = Draft202012Validator(
    json.loads((_ROOT / "packages/contracts/jsonschema/policy-decision.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
_RISK_ORDER = {f"R{index}": index for index in range(5)}
_RELEASE_MODES = {
    "architecture_mvp": {"manual_export", "simulation"},
    "distribution_pilot": {"manual_export", "simulation", "draft_only"},
    "scale": {"manual_export", "simulation", "draft_only", "authorized_api"},
}


def _unique(values: Sequence[str]) -> list[str]:
    return sorted({value for value in values if value})


class PolicyGateService:
    """Evaluate an immutable policy snapshot without creating side effects."""

    rule_version = "policy-001/v1"

    def __init__(self) -> None:
        self.audit: list[dict[str, Any]] = []
        self._results: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
        self._lock = RLock()

    def evaluate(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        subject_type: str, subject_id: UUID | str, policy_snapshot: Mapping[str, Any],
        context: Mapping[str, Any] | None = None, facts: Mapping[str, Any] | None = None,
        evaluated_at: datetime | str | None = None, decision_version: int = 1,
    ) -> dict[str, Any]:
        tenant = _uuid(org_id, "org_id")
        actor = _uuid(actor_id, "actor_id")
        trace = _text(trace_id, "trace_id")
        key = _text(idempotency_key, "idempotency_key", 200)
        kind = _text(subject_type, "subject_type", 128)
        subject = _uuid(subject_id, "subject_id")
        if not isinstance(policy_snapshot, Mapping):
            raise QAError("INVALID_POLICY_INPUT", "policy_snapshot must be an object")
        if context is not None and not isinstance(context, Mapping):
            raise QAError("INVALID_POLICY_INPUT", "context must be an object")
        if facts is not None and not isinstance(facts, Mapping):
            raise QAError("INVALID_POLICY_INPUT", "facts must be an object")
        merged_context = {**dict(facts or {}), **dict(context or {})}
        if type(decision_version) is not int or decision_version < 1:
            raise QAError("INVALID_POLICY_INPUT", "decision_version must be a positive integer")
        snapshot = deepcopy(dict(policy_snapshot))
        snapshot_errors = list(_SNAPSHOT_VALIDATOR.iter_errors(snapshot))
        if snapshot_errors:
            raise QAError("INVALID_POLICY_SNAPSHOT", snapshot_errors[0].message)
        snapshot_org = snapshot.get("org_id")
        if snapshot_org is not None and snapshot_org != tenant:
            raise QAError("TENANT_SCOPE_VIOLATION", "PolicySnapshot is outside this organization")
        if snapshot.get("subject_type") != kind:
            raise QAError("POLICY_SUBJECT_MISMATCH", "PolicySnapshot subject type does not match evaluation")
        snapshot_subject = snapshot.get("subject_id")
        if snapshot_subject is not None and snapshot_subject != subject:
            raise QAError("POLICY_SUBJECT_MISMATCH", "PolicySnapshot subject does not match evaluation")
        snapshot_id = _uuid(snapshot["id"], "policy_snapshot_id")
        check_time = _time(evaluated_at, "evaluated_at") if evaluated_at is not None else datetime.now(timezone.utc)
        if check_time is None:
            raise QAError("INVALID_POLICY_INPUT", "evaluated_at must be timezone-aware ISO-8601")
        request_hash = _hash({"subject_type": kind, "subject_id": subject, "snapshot": snapshot,
                              "context": merged_context, "evaluated_at": _stamp(check_time),
                              "decision_version": decision_version})
        with self._lock:
            prior = self._results.get((tenant, key))
            if prior is not None:
                if prior[0] != request_hash:
                    raise QAError("IDEMPOTENCY_KEY_REUSED", "Policy request differs from prior request")
                return deepcopy(prior[1])
            reasons: list[str] = []
            snapshot_denied = False

            def add(reason: str) -> None:
                if reason not in reasons:
                    reasons.append(reason)

            snapshot_status = snapshot.get("status")
            if snapshot_status != "active":
                add(f"POLICY_SNAPSHOT_{str(snapshot_status).upper()}")
                snapshot_denied = True
            effective_at = _time(snapshot.get("effective_at"), "snapshot.effective_at")
            expires_at = _time(snapshot.get("expires_at"), "snapshot.expires_at")
            review_due_at = _time(snapshot.get("review_due_at"), "snapshot.review_due_at")
            if effective_at is not None and check_time < effective_at:
                add("POLICY_SNAPSHOT_NOT_EFFECTIVE")
                snapshot_denied = True
            if expires_at is not None and check_time >= expires_at:
                add("POLICY_SNAPSHOT_EXPIRED")
                snapshot_denied = True
            if review_due_at is not None and check_time >= review_due_at and (expires_at is None or check_time < expires_at):
                add("POLICY_SNAPSHOT_REVIEW_DUE")

            policies: dict[str, str] = {
                "content_policy": "allow", "region_policy": "allow", "distribution_policy": "allow",
                "account_policy": "allow", "data_processing_policy": "allow", "model_policy": "allow",
            }
            if snapshot_denied:
                policies["content_policy"] = "deny"
                policies["region_policy"] = "deny"
                policies["distribution_policy"] = "deny"
            risk_values = merged_context.get("risk_levels", merged_context.get("risk_level"))
            if risk_values is None:
                risk_values = []
            if isinstance(risk_values, str):
                risk_values = [risk_values]
            if not isinstance(risk_values, Sequence) or isinstance(risk_values, (bytes, bytearray)):
                risk_values = []
                add("RISK_LEVEL_UNKNOWN")
            risk_values_list = list(risk_values)
            valid_risks = [str(value) for value in risk_values_list if str(value) in _RISK_ORDER]
            unknown_risk = not valid_risks or len(valid_risks) != len(risk_values_list)
            risk_level = max(valid_risks, key=lambda value: _RISK_ORDER[value]) if valid_risks else "R2"
            if unknown_risk:
                add("RISK_LEVEL_UNKNOWN")
            if risk_level in {"R3", "R4"}:
                policies["content_policy"] = "deny"
                policies["distribution_policy"] = "deny"
                add(f"RISK_{risk_level}_BLOCKED")
            elif risk_level == "R2":
                policies["content_policy"] = "manual_review"
                policies["distribution_policy"] = "manual_review"
                add("RISK_R2_REVIEW")

            qa_status = merged_context.get("qa_status", "unknown")
            if qa_status == "failed":
                policies["content_policy"] = "deny"
                add("QA_FAILED")
            elif qa_status in {"needs_review", "unknown", None}:
                policies["content_policy"] = "manual_review"
                add("QA_REVIEW_REQUIRED")

            rights_allowed = merged_context.get("rights_allowed")
            if rights_allowed is False:
                policies["distribution_policy"] = "deny"
                add("RIGHTS_DENIED")
            elif rights_allowed is not True:
                policies["distribution_policy"] = "manual_review"
                add("RIGHTS_UNKNOWN")

            region_decision = merged_context.get("region_decision", "unknown")
            if region_decision == "deny":
                policies["region_policy"] = "deny"
                policies["distribution_policy"] = "deny"
                add("REGION_DENIED")
            elif region_decision in {"manual_review", "unknown", None}:
                policies["region_policy"] = "manual_review"
                policies["distribution_policy"] = "manual_review"
                add("REGION_REVIEW_REQUIRED")

            release_level = merged_context.get("release_level", "architecture_mvp")
            release_mode = merged_context.get("release_mode", "manual_export")
            if release_level not in _RELEASE_MODES:
                policies["distribution_policy"] = "deny"
                add("RELEASE_LEVEL_UNKNOWN")
            elif release_mode not in _RELEASE_MODES[release_level]:
                policies["distribution_policy"] = "deny"
                add("RELEASE_MODE_NOT_ALLOWED")

            account_state = merged_context.get("account_state", "unknown")
            if account_state in {"denied", "revoked", "unhealthy"}:
                policies["account_policy"] = "deny"
                add("ACCOUNT_NOT_AUTHORIZED")
            elif account_state == "not_required" and release_level == "architecture_mvp" and release_mode in {"manual_export", "simulation"}:
                policies["account_policy"] = "allow"
            elif account_state not in {"healthy", "authorized"}:
                policies["account_policy"] = "unknown"
                policies["distribution_policy"] = "manual_review"
                add("ACCOUNT_UNKNOWN")

            data_allowed = merged_context.get("data_processing_allowed")
            if data_allowed is False:
                policies["data_processing_policy"] = "deny"
                add("DATA_PROCESSING_DENIED")
            elif data_allowed is not True:
                policies["data_processing_policy"] = "manual_review"
                add("DATA_PROCESSING_UNKNOWN")

            model_allowed = merged_context.get("model_allowed")
            if model_allowed is False:
                policies["model_policy"] = "deny"
                add("MODEL_DENIED")
            elif model_allowed is not True:
                policies["model_policy"] = "manual_review"
                add("MODEL_UNKNOWN")

            approval_required = bool(merged_context.get("approval_required", False))
            approvals = merged_context.get("approvals", 0)
            approval_quorum = merged_context.get("approval_quorum", 1)
            if isinstance(approvals, Sequence) and not isinstance(approvals, (str, bytes, bytearray)):
                approved_count = sum(1 for item in approvals if item == "approved" or (isinstance(item, Mapping) and item.get("status") == "approved"))
                if any(item == "denied" or (isinstance(item, Mapping) and item.get("status") == "denied") for item in approvals):
                    policies["distribution_policy"] = "deny"
                    add("APPROVAL_DENIED")
            else:
                approved_count = int(approvals) if isinstance(approvals, int) and not isinstance(approvals, bool) else 0
            if approval_required and (not isinstance(approval_quorum, int) or approval_quorum < 1 or approved_count < approval_quorum):
                policies["distribution_policy"] = "manual_review"
                add("APPROVAL_QUORUM_INSUFFICIENT")

            if merged_context.get("external_result_unknown") is True:
                policies["distribution_policy"] = "manual_review"
                add("EXTERNAL_RESULT_UNKNOWN")

            # Reapply hard blocks after softer checks so later unknown/manual
            # states can never downgrade a deterministic denial.
            if snapshot_denied:
                policies["content_policy"] = "deny"
                policies["region_policy"] = "deny"
                policies["distribution_policy"] = "deny"
            if "QA_FAILED" in reasons or "RISK_R3_BLOCKED" in reasons or "RISK_R4_BLOCKED" in reasons:
                policies["content_policy"] = "deny"
            if any(reason in reasons for reason in ("RISK_R3_BLOCKED", "RISK_R4_BLOCKED", "RIGHTS_DENIED", "REGION_DENIED", "RELEASE_MODE_NOT_ALLOWED", "APPROVAL_DENIED")):
                policies["distribution_policy"] = "deny"
            if "REGION_DENIED" in reasons:
                policies["region_policy"] = "deny"
            if "ACCOUNT_NOT_AUTHORIZED" in reasons:
                policies["account_policy"] = "deny"
            if "DATA_PROCESSING_DENIED" in reasons:
                policies["data_processing_policy"] = "deny"
            if "MODEL_DENIED" in reasons:
                policies["model_policy"] = "deny"

            if any(value == "deny" for value in policies.values()):
                final = "deny"
            elif any(value in {"manual_review", "unknown"} for value in policies.values()) or reasons:
                final = "manual_review"
            else:
                final = "allow"
            if not reasons and final == "allow":
                reasons.append("POLICY_CHECKS_PASSED")
            reasons = _unique(reasons)
            decision_payload = {
                "org_id": tenant, "subject_type": kind, "subject_id": subject,
                **policies, "final_decision": final, "reasons": reasons,
                "policy_snapshot_id": snapshot_id, "decision_version": decision_version,
                "evaluated_at": _stamp(check_time), "expires_at": snapshot.get("expires_at"),
            }
            decision = {"id": str(uuid4()), **decision_payload,
                        "decision_hash": _hash(decision_payload), "created_at": _stamp(check_time)}
            errors = list(_DECISION_VALIDATOR.iter_errors(decision))
            if errors:
                raise QAError("INVALID_POLICY_DECISION", errors[0].message)
            self.audit.append({"event_type": "policy.decision.created", "org_id": tenant, "actor_id": actor,
                               "trace_id": trace, "idempotency_key": key, "input_hash": request_hash,
                               "output_hash": _hash(decision), "final_decision": final,
                               "policy_snapshot_id": snapshot_id})
            self._results[(tenant, key)] = (request_hash, deepcopy(decision))
            return deepcopy(decision)


__all__ = ["PolicyGateService"]
