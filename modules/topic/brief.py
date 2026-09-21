"""Versioned TopicBrief drafts with evidence and Policy-gated locking."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker

from .infrastructure.brief_schema import initialize
from .opportunity import TopicOpportunityError, TopicOpportunityService


ROOT = Path(__file__).resolve().parents[2]
BRIEF_VALIDATOR = Draft202012Validator(
    json.loads((ROOT / "packages/contracts/jsonschema/topic-brief.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
CONTENT_FIELDS = ("audience", "problem_statement", "core_claims", "evidence_plan",
                  "original_angle", "locales", "markets", "expected_channels")
LOCK_EXCLUDED_FIELDS = frozenset({
    "status", "approved_by", "approved_at", "locked_at", "locked_by", "lock_hash",
    "policy_snapshot_ref",
})


class TopicBriefError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class BriefPolicyGate(Protocol):
    def verify(self, *, org_id: str, policy_snapshot_ref: str,
               opportunity: Mapping[str, Any], brief: Mapping[str, Any]) -> bool: ...


def _uuid(value: UUID | str, name: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise TopicBriefError("INVALID_BRIEF_COMMAND", f"{name} must be a UUID") from exc


def _text(value: object, name: str, limit: int = 2048) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise TopicBriefError("INVALID_BRIEF_CONTENT", f"{name} must be nonempty and at most {limit} characters")
    return value.strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _hash(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode()).hexdigest()


def _strings(value: object, name: str) -> list[str]:
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Sequence) or not value:
        raise TopicBriefError("INVALID_BRIEF_CONTENT", f"{name} must be a nonempty array")
    result = [_text(item, name, 128) for item in value]
    if len(result) != len(set(result)):
        raise TopicBriefError("INVALID_BRIEF_CONTENT", f"{name} must be unique")
    return result


def _content(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(CONTENT_FIELDS):
        raise TopicBriefError("INVALID_BRIEF_CONTENT", "all brief content fields are required")
    audience = value["audience"]
    if not isinstance(audience, Mapping) or set(audience) != {"role", "experience_level", "job_to_be_done"}:
        raise TopicBriefError("INVALID_BRIEF_CONTENT", "audience fields are required")
    normalized_audience = {field: _text(audience[field], field, 256) for field in audience}
    plan = value["evidence_plan"]
    if isinstance(plan, (str, bytes, Mapping)) or not isinstance(plan, Sequence) or not plan:
        raise TopicBriefError("INVALID_BRIEF_CONTENT", "evidence_plan must be a nonempty array")
    plans = []
    for item in plan:
        if not isinstance(item, Mapping) or set(item) != {"key", "required", "evidence_refs"} or type(item["required"]) is not bool:
            raise TopicBriefError("INVALID_BRIEF_CONTENT", "each evidence plan needs key, required and evidence_refs")
        refs = item["evidence_refs"]
        if isinstance(refs, (str, bytes, Mapping)) or not isinstance(refs, Sequence):
            raise TopicBriefError("INVALID_BRIEF_CONTENT", "evidence_refs must be an array")
        normalized_refs = [_text(ref, "evidence_ref") for ref in refs]
        if len(normalized_refs) != len(set(normalized_refs)):
            raise TopicBriefError("INVALID_BRIEF_CONTENT", "evidence refs must be unique")
        plans.append({"key": _text(item["key"], "evidence_plan.key", 128),
                      "required": item["required"], "evidence_refs": normalized_refs})
    plan_keys = [item["key"] for item in plans]
    if len(plan_keys) != len(set(plan_keys)):
        raise TopicBriefError("INVALID_BRIEF_CONTENT", "evidence plan keys must be unique")
    claims = value["core_claims"]
    if isinstance(claims, (str, bytes, Mapping)) or not isinstance(claims, Sequence) or not claims:
        raise TopicBriefError("INVALID_BRIEF_CONTENT", "core_claims must be a nonempty array")
    normalized_claims = []
    for item in claims:
        if not isinstance(item, Mapping) or set(item) != {"claim_key", "statement", "evidence_plan_keys"}:
            raise TopicBriefError("INVALID_BRIEF_CONTENT", "each claim needs key, statement and evidence_plan_keys")
        refs = _strings(item["evidence_plan_keys"], "evidence_plan_keys")
        if not set(refs) <= set(plan_keys):
            raise TopicBriefError("CLAIM_EVIDENCE_PLAN_MISSING", "claim refers to an unknown evidence plan")
        normalized_claims.append({"claim_key": _text(item["claim_key"], "claim_key", 128),
                                  "statement": _text(item["statement"], "statement"),
                                  "evidence_plan_keys": refs})
    claim_keys = [item["claim_key"] for item in normalized_claims]
    if len(claim_keys) != len(set(claim_keys)):
        raise TopicBriefError("INVALID_BRIEF_CONTENT", "claim keys must be unique")
    return {
        "audience": normalized_audience,
        "problem_statement": _text(value["problem_statement"], "problem_statement"),
        "core_claims": normalized_claims, "evidence_plan": plans,
        "original_angle": _text(value["original_angle"], "original_angle"),
        "locales": _strings(value["locales"], "locales"),
        "markets": _strings(value["markets"], "markets"),
        "expected_channels": _strings(value["expected_channels"], "expected_channels"),
    }


def _brief(tenant: str, opportunity: Mapping[str, Any], actor: str, content: dict[str, Any],
           *, version_no: int, supersedes: str | None = None) -> dict[str, Any]:
    content_hash = _hash({"opportunity_score_hash": opportunity["score_snapshot_hash"], "content": content})
    claim_specs = [{"claim_key": item["claim_key"], "statement": item["statement"],
                    "priority": "normal", "evidence_plan_refs": item["evidence_plan_keys"]}
                   for item in content["core_claims"]]
    result = {
        "id": str(uuid4()), "org_id": tenant, "opportunity_id": opportunity["id"],
        "status": "draft", "version_no": version_no, "audience": content["audience"],
        "problem": content["problem_statement"], "claim_specs": claim_specs, "claim_ids": [],
        "evidence_plan": content["evidence_plan"], "original_angle": content["original_angle"],
        "locales": content["locales"], "markets": content["markets"],
        "expected_channels": content["expected_channels"], "approved_by": None,
        "approved_at": None, "locked_at": None, "locked_by": None, "lock_hash": None,
        "input_snapshot_hash": content_hash, "deferred_reason": None,
        "problem_statement": content["problem_statement"], "core_claims": content["core_claims"],
        "owner_id": actor, "created_by": actor, "created_at": _now(), "supersedes_version_id": supersedes,
        "policy_snapshot_ref": None,
    }
    BRIEF_VALIDATOR.validate(result)
    return result


class TopicBriefService:
    def __init__(self, opportunities: TopicOpportunityService, policy_gate: BriefPolicyGate | None = None) -> None:
        self.opportunities = opportunities
        self.policy_gate = policy_gate
        self._connection = opportunities._connection
        self._lock = opportunities._lock
        initialize(self._connection)

    def _prior(self, tenant: str, key: str, digest: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT payload_hash, response FROM topic_brief_commands WHERE org_id = ? AND idempotency_key = ?",
            (tenant, key),
        ).fetchone()
        if row is None:
            return None
        if row["payload_hash"] != digest:
            raise TopicBriefError("IDEMPOTENCY_KEY_REUSED", "brief command payload differs")
        return json.loads(row["response"])

    def _command(self, tenant: str, key: str, digest: str, actor: str, trace: str,
                 response: dict[str, Any]) -> None:
        self._connection.execute(
            "INSERT INTO topic_brief_commands (org_id, idempotency_key, payload_hash, actor_id, trace_id, response) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tenant, key, digest, actor, trace, json.dumps(response, ensure_ascii=False, sort_keys=True)),
        )

    def _event(self, tenant: str, actor: str, trace: str, key: str,
               event_type: str, brief: Mapping[str, Any]) -> None:
        event_id = str(uuid4())
        payload = {"aggregate_id": brief["id"], "aggregate_version": brief["version_no"],
                   "snapshot_hash": brief["lock_hash"] or brief["input_snapshot_hash"],
                   "input_snapshot_hash": brief["input_snapshot_hash"],
                   "lock_hash": brief.get("lock_hash")}
        envelope = {"event_id": event_id, "event_type": event_type, "event_schema_version": 1,
                    "occurred_at": _now(), "org_id": tenant, "trace_id": trace,
                    "correlation_id": None, "causation_id": None, "aggregate_type": "TopicBrief",
                    "aggregate_id": brief["id"], "aggregate_version": brief["version_no"],
                    "actor_type": "user", "actor_id": actor, "idempotency_key": key,
                    "payload": payload, "payload_hash": _hash(payload)}
        self._connection.execute(
            "INSERT INTO topic_brief_events (event_id, org_id, event_type, envelope) VALUES (?, ?, ?, ?)",
            (event_id, tenant, event_type, json.dumps(envelope, sort_keys=True)),
        )

    def _identity(self, org_id: UUID | str, actor_id: UUID | str,
                  trace_id: str, idempotency_key: str) -> tuple[str, str, str, str]:
        return (_uuid(org_id, "org_id"), _uuid(actor_id, "actor_id"),
                _text(trace_id, "trace_id", 256), _text(idempotency_key, "idempotency_key", 200))

    def create(self, *, org_id: UUID | str, opportunity_id: UUID | str, actor_id: UUID | str,
               trace_id: str, idempotency_key: str, content: Mapping[str, Any]) -> dict[str, Any]:
        tenant, actor, trace, key = self._identity(org_id, actor_id, trace_id, idempotency_key)
        identity = _uuid(opportunity_id, "opportunity_id")
        normalized = _content(content)
        digest = _hash({"opportunity_id": identity, "content": normalized})
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                try:
                    opportunity = self.opportunities.get(org_id=tenant, opportunity_id=identity)
                except TopicOpportunityError as exc:
                    raise TopicBriefError("TENANT_SCOPE_VIOLATION", "opportunity is not in this organization") from exc
                exists = self._connection.execute(
                    "SELECT id FROM topic_briefs WHERE org_id = ? AND opportunity_id = ? LIMIT 1",
                    (tenant, identity),
                ).fetchone()
                if exists is not None:
                    raise TopicBriefError("BRIEF_ALREADY_EXISTS", "brief already exists; use supersede")
                brief = _brief(tenant, opportunity, actor, normalized, version_no=1)
                self._connection.execute(
                    "INSERT INTO topic_briefs (id, org_id, opportunity_id, version_no, status, lock_hash, "
                    "input_snapshot_hash, locked_at, locked_by, supersedes_version_id, created_by, created_at, payload) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (brief["id"], tenant, identity, 1, "draft", None, brief["input_snapshot_hash"],
                     None, None, brief["supersedes_version_id"], brief["created_by"], brief["created_at"],
                     json.dumps(brief, ensure_ascii=False, sort_keys=True)),
                )
                self._event(tenant, actor, trace, key + ":created", "topic.brief.created", brief)
                response = {"brief": brief}
                self._command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except Exception:
                self._connection.rollback()
                raise

    def _policy(self, tenant: str, opportunity: Mapping[str, Any], brief: Mapping[str, Any],
                policy_snapshot_ref: str) -> None:
        if self.policy_gate is None or not self.policy_gate.verify(
            org_id=tenant, policy_snapshot_ref=policy_snapshot_ref, opportunity=opportunity, brief=brief
        ):
            raise TopicBriefError("POLICY_DENIED", "Policy did not permit locking this brief")

    def _check_lock(self, tenant: str, brief: Mapping[str, Any], policy_ref: str) -> dict[str, Any]:
        try:
            opportunity = self.opportunities.assert_brief_eligible(
                org_id=tenant, opportunity_id=brief["opportunity_id"]
            )
        except TopicOpportunityError as exc:
            raise TopicBriefError("TOPIC_BRIEF_NOT_ELIGIBLE", "opportunity is not shortlisted or has expired") from exc
        for plan in brief["evidence_plan"]:
            if plan["required"] and not plan["evidence_refs"]:
                raise TopicBriefError("EVIDENCE_PLAN_INCOMPLETE", "required evidence plan has no evidence")
        self._policy(tenant, opportunity, brief, policy_ref)
        return opportunity

    def _lock_hash(self, brief: Mapping[str, Any], policy_ref: str | None) -> str:
        payload = {key: brief[key] for key in sorted(brief) if key not in LOCK_EXCLUDED_FIELDS}
        material: dict[str, Any] = {
            "brief_payload": payload,
            "input_snapshot_hash": brief["input_snapshot_hash"],
            "version_no": brief["version_no"],
        }
        # The legacy internal lock included the policy reference. Keep that
        # compatibility behavior while the public approval command uses the
        # task-defined payload/input/version formula.
        if policy_ref is not None:
            material["policy_snapshot_ref"] = policy_ref
        return _hash(material)

    def recompute_lock_hash(self, brief: Mapping[str, Any]) -> str:
        """Recompute the public approval hash from the immutable draft payload."""
        return self._lock_hash(brief, None)

    @staticmethod
    def _ensure_complete(brief: Mapping[str, Any]) -> None:
        errors = sorted(BRIEF_VALIDATOR.iter_errors(brief), key=lambda error: list(error.path))
        if errors:
            raise TopicBriefError("TOPIC_BRIEF_INCOMPLETE", errors[0].message)
        required = ("audience", "problem_statement", "core_claims", "evidence_plan",
                    "original_angle", "locales", "markets")
        if any(not brief.get(field) for field in required):
            raise TopicBriefError("TOPIC_BRIEF_INCOMPLETE", "required TopicBrief fields are incomplete")

    @staticmethod
    def _if_match_version(if_match: str | None) -> int | None:
        if if_match is None:
            return None
        value = if_match.strip()
        if value.startswith("W/"):
            value = value[2:].strip()
        value = value.strip('"')
        if value.startswith("v"):
            value = value[1:]
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise TopicBriefError("OPTIMISTIC_LOCK_CONFLICT", "If-Match must contain a brief version") from exc
        if parsed < 1:
            raise TopicBriefError("OPTIMISTIC_LOCK_CONFLICT", "If-Match must contain a positive version")
        return parsed

    def lock(self, *, org_id: UUID | str, brief_id: UUID | str, actor_id: UUID | str,
             trace_id: str, idempotency_key: str, expected_version_no: int,
             policy_snapshot_ref: str) -> dict[str, Any]:
        tenant, actor, trace, key = self._identity(org_id, actor_id, trace_id, idempotency_key)
        identity = _uuid(brief_id, "brief_id")
        policy_ref = _text(policy_snapshot_ref, "policy_snapshot_ref")
        if type(expected_version_no) is not int or expected_version_no < 1:
            raise TopicBriefError("VERSION_CONFLICT", "expected_version_no must be positive")
        digest = _hash({"brief_id": identity, "expected_version_no": expected_version_no,
                        "policy_snapshot_ref": policy_ref})
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                brief = self.get(org_id=tenant, brief_id=identity)
                if brief["version_no"] != expected_version_no:
                    raise TopicBriefError("VERSION_CONFLICT", "brief version changed")
                lock_hash = self._lock_hash(brief, policy_ref)
                if brief["status"] in {"locked", "approved"}:
                    expected_hash = lock_hash if brief["status"] == "locked" else self.recompute_lock_hash(brief)
                    if brief["lock_hash"] != expected_hash:
                        raise TopicBriefError("BRIEF_ALREADY_LOCKED", "locked brief payload differs")
                    response = {"brief": brief}
                    self._command(tenant, key, digest, actor, trace, response)
                    self._connection.commit()
                    return response
                if brief["status"] != "draft":
                    raise TopicBriefError("INVALID_BRIEF_STATE", "only draft briefs can be locked")
                self._ensure_complete(brief)
                self._check_lock(tenant, brief, policy_ref)
                stamp = _now()
                brief.update(status="locked", approved_by=actor, approved_at=stamp, locked_by=actor,
                             locked_at=stamp, lock_hash=lock_hash, policy_snapshot_ref=policy_ref)
                BRIEF_VALIDATOR.validate(brief)
                updated = self._connection.execute(
                    "UPDATE topic_briefs SET status = 'locked', lock_hash = ?, input_snapshot_hash = ?, "
                    "locked_at = ?, locked_by = ?, payload = ? "
                    "WHERE id = ? AND org_id = ? AND version_no = ? AND status = 'draft'",
                    (lock_hash, brief["input_snapshot_hash"], stamp, actor,
                     json.dumps(brief, ensure_ascii=False, sort_keys=True), identity, tenant, expected_version_no),
                )
                if updated.rowcount != 1:
                    raise TopicBriefError("VERSION_CONFLICT", "brief changed while locking")
                self._event(tenant, actor, trace, key + ":locked", "topic.brief.approved", brief)
                response = {"brief": brief}
                self._command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except Exception:
                self._connection.rollback()
                raise

    def approve(
        self, *, org_id: UUID | str, brief_id: UUID | str, actor_id: UUID | str,
        trace_id: str, idempotency_key: str, expected_version_no: int | None = None,
        if_match: str | None = None, policy_snapshot_ref: str = "policy/v1",
    ) -> dict[str, Any]:
        """Approve and immutably lock a draft in one optimistic transaction."""
        tenant, actor, trace, key = self._identity(org_id, actor_id, trace_id, idempotency_key)
        identity = _uuid(brief_id, "brief_id")
        matched = self._if_match_version(if_match)
        if expected_version_no is None:
            expected_version_no = matched
        elif type(expected_version_no) is not int or expected_version_no < 1:
            raise TopicBriefError("OPTIMISTIC_LOCK_CONFLICT", "expected_version_no must be positive")
        if expected_version_no is None:
            raise TopicBriefError("OPTIMISTIC_LOCK_CONFLICT", "If-Match or expected_version_no is required")
        if matched is not None and matched != expected_version_no:
            raise TopicBriefError("OPTIMISTIC_LOCK_CONFLICT", "If-Match does not match expected version")
        policy_ref = _text(policy_snapshot_ref, "policy_snapshot_ref")
        digest = _hash({"brief_id": identity, "expected_version_no": expected_version_no,
                        "if_match": matched, "policy_snapshot_ref": policy_ref})
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                brief = self.get(org_id=tenant, brief_id=identity)
                if brief["version_no"] != expected_version_no:
                    raise TopicBriefError("OPTIMISTIC_LOCK_CONFLICT", "brief version changed")
                if brief["status"] in {"approved", "locked"}:
                    if brief.get("lock_hash") != self.recompute_lock_hash(brief):
                        raise TopicBriefError("IMMUTABLE_VERSION", "approved brief payload is immutable")
                    raise TopicBriefError("OPTIMISTIC_LOCK_CONFLICT", "brief version was already approved")
                if brief["status"] != "draft":
                    raise TopicBriefError("IMMUTABLE_VERSION", "only draft brief versions can be approved")
                if str(brief.get("created_by") or brief.get("owner_id")) == actor:
                    raise TopicBriefError("BRIEF_CREATOR_CANNOT_APPROVE", "brief creator cannot approve its own version")
                self._ensure_complete(brief)
                self._check_lock(tenant, brief, policy_ref)
                stamp = _now()
                lock_hash = self.recompute_lock_hash(brief)
                brief.update(status="approved", approved_by=actor, approved_at=stamp,
                             locked_by=actor, locked_at=stamp, lock_hash=lock_hash,
                             policy_snapshot_ref=policy_ref)
                BRIEF_VALIDATOR.validate(brief)
                updated = self._connection.execute(
                    "UPDATE topic_briefs SET status = 'approved', lock_hash = ?, input_snapshot_hash = ?, "
                    "locked_at = ?, locked_by = ?, payload = ? "
                    "WHERE id = ? AND org_id = ? AND version_no = ? AND status = 'draft'",
                    (lock_hash, brief["input_snapshot_hash"], stamp, actor,
                     json.dumps(brief, ensure_ascii=False, sort_keys=True), identity, tenant, expected_version_no),
                )
                if updated.rowcount != 1:
                    raise TopicBriefError("OPTIMISTIC_LOCK_CONFLICT", "brief changed while approving")
                self._event(tenant, actor, trace, key + ":approved", "topic.brief.approved", brief)
                response = {"brief": brief}
                self._command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except Exception:
                self._connection.rollback()
                raise

    def supersede(self, *, org_id: UUID | str, brief_id: UUID | str, actor_id: UUID | str,
                  trace_id: str, idempotency_key: str, expected_version_no: int,
                  policy_snapshot_ref: str, content: Mapping[str, Any]) -> dict[str, Any]:
        tenant, actor, trace, key = self._identity(org_id, actor_id, trace_id, idempotency_key)
        identity = _uuid(brief_id, "brief_id")
        policy_ref = _text(policy_snapshot_ref, "policy_snapshot_ref")
        normalized = _content(content)
        digest = _hash({"brief_id": identity, "expected_version_no": expected_version_no,
                        "policy_snapshot_ref": policy_ref, "content": normalized})
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                old = self.get(org_id=tenant, brief_id=identity)
                if old["version_no"] != expected_version_no or old["status"] not in {"locked", "approved"}:
                    raise TopicBriefError("INVALID_BRIEF_STATE", "only current approved brief can be superseded")
                latest = self._connection.execute(
                    "SELECT MAX(version_no) FROM topic_briefs WHERE org_id = ? AND opportunity_id = ?",
                    (tenant, old["opportunity_id"]),
                ).fetchone()[0]
                if latest != expected_version_no:
                    raise TopicBriefError("VERSION_CONFLICT", "brief version changed")
                try:
                    opportunity = self.opportunities.assert_brief_eligible(
                        org_id=tenant, opportunity_id=old["opportunity_id"]
                    )
                except TopicOpportunityError as exc:
                    raise TopicBriefError("TOPIC_BRIEF_NOT_ELIGIBLE", "opportunity is not shortlisted or has expired") from exc
                newer = _brief(tenant, opportunity, actor, normalized,
                               version_no=expected_version_no + 1, supersedes=identity)
                self._ensure_complete(newer)
                legacy_auto_lock = old["status"] == "locked"
                stamp = _now() if legacy_auto_lock else None
                if legacy_auto_lock:
                    self._check_lock(tenant, newer, policy_ref)
                    newer.update(status="locked", approved_by=actor, approved_at=stamp, locked_by=actor,
                                 locked_at=stamp, lock_hash=self._lock_hash(newer, policy_ref),
                                 policy_snapshot_ref=policy_ref)
                BRIEF_VALIDATOR.validate(newer)
                old["status"] = "superseded"
                self._connection.execute(
                    "UPDATE topic_briefs SET status = 'superseded', payload = ? WHERE id = ? AND org_id = ? "
                    "AND version_no = ? AND status IN ('locked', 'approved')",
                    (json.dumps(old, ensure_ascii=False, sort_keys=True), identity, tenant, expected_version_no),
                )
                self._connection.execute(
                    "INSERT INTO topic_briefs (id, org_id, opportunity_id, version_no, status, lock_hash, "
                    "input_snapshot_hash, locked_at, locked_by, supersedes_version_id, created_by, created_at, payload) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (newer["id"], tenant, newer["opportunity_id"], newer["version_no"], newer["status"],
                     newer["lock_hash"], newer["input_snapshot_hash"], newer["locked_at"], newer["locked_by"],
                     newer["supersedes_version_id"], newer["created_by"], newer["created_at"],
                     json.dumps(newer, ensure_ascii=False, sort_keys=True)),
                )
                self._event(tenant, actor, trace, key + ":superseded", "topic.brief.superseded", old)
                if legacy_auto_lock:
                    self._event(tenant, actor, trace, key + ":locked", "topic.brief.approved", newer)
                response = {"brief": newer, "superseded_version_id": identity}
                self._command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except Exception:
                self._connection.rollback()
                raise

    def get(self, *, org_id: UUID | str, brief_id: UUID | str) -> dict[str, Any]:
        tenant, identity = _uuid(org_id, "org_id"), _uuid(brief_id, "brief_id")
        row = self._connection.execute(
            "SELECT payload FROM topic_briefs WHERE org_id = ? AND id = ?", (tenant, identity)
        ).fetchone()
        if row is None:
            raise TopicBriefError("TENANT_SCOPE_VIOLATION", "brief is not in this organization")
        return json.loads(row["payload"])

    def latest_locked(self, *, org_id: UUID | str, opportunity_id: UUID | str) -> dict[str, Any]:
        tenant, identity = _uuid(org_id, "org_id"), _uuid(opportunity_id, "opportunity_id")
        row = self._connection.execute(
            "SELECT payload FROM topic_briefs WHERE org_id = ? AND opportunity_id = ? "
            "AND status IN ('locked', 'approved') ORDER BY version_no DESC LIMIT 1", (tenant, identity)
        ).fetchone()
        if row is None:
            raise TopicBriefError("BRIEF_NOT_LOCKED", "no locked brief version is available")
        return json.loads(row["payload"])

    def events(self, *, org_id: UUID | str) -> tuple[dict[str, Any], ...]:
        tenant = _uuid(org_id, "org_id")
        rows = self._connection.execute(
            "SELECT envelope FROM topic_brief_events WHERE org_id = ? ORDER BY event_id", (tenant,)
        ).fetchall()
        return tuple(json.loads(row["envelope"]) for row in rows)


__all__ = ["TopicBriefError", "BriefPolicyGate", "TopicBriefService"]
