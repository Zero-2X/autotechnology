"""Minimal Graph State, references, migration and sensitive-field guards."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
import json
from typing import Any, Mapping, MutableMapping, TypedDict
from uuid import UUID, uuid4

class StateViolation(ValueError):
    pass


_FORBIDDEN_KEYS = frozenset({
    "token", "access_token", "refresh_token", "authorization", "cookie", "password",
    "secret", "private_key", "raw_content", "raw_output", "pii", "binary", "prompt",
})
_ALLOWED_TOP_LEVEL = frozenset({
    "run_id", "org_id", "actor_id", "workflow_key", "workflow_version", "input_refs",
    "current_node", "artifact_refs", "evidence_refs", "qa_refs", "policy_decision_ref",
    "human_interrupt_ref", "retry_context", "idempotency_key", "trace_id", "error_ref",
    "status", "result_refs", "resume_token", "state_version", "last_node",
})
_REFERENCE_PREFIXES = (
    "private://", "ref://", "artifact://", "evidence://", "policy://", "human://",
    "task://", "object://", "error://", "resume://",
)
_REFERENCE_MAP_FIELDS = ("input_refs", "artifact_refs", "result_refs")
_REFERENCE_LIST_FIELDS = ("evidence_refs", "qa_refs")
_REFERENCE_SCALAR_FIELDS = ("policy_decision_ref", "human_interrupt_ref", "error_ref", "resume_token")
_STATUSES = frozenset({"running", "waiting", "paused", "succeeded", "failed", "cancelled"})


def _uuid(value: Any, field: str) -> str:
    try:
        return str(value if isinstance(value, UUID) else UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise StateViolation(f"{field} must be a UUID") from exc


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise StateViolation("state must be finite JSON") from exc


def _check_sensitive(value: Any, *, path: str = "state") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key)
            if name.lower() in _FORBIDDEN_KEYS:
                raise StateViolation(f"sensitive state field is forbidden: {path}.{name}")
            _check_sensitive(item, path=f"{path}.{name}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _check_sensitive(item, path=f"{path}[{index}]")


def _check_reference(value: Any, *, field: str) -> None:
    if not isinstance(value, str) or not value.startswith(_REFERENCE_PREFIXES) or len(value) > 2048:
        raise StateViolation(f"{field} must be an opaque reference")


def validate_state(state: Mapping[str, Any], *, max_bytes: int = 64 * 1024) -> dict[str, Any]:
    if not isinstance(state, Mapping):
        raise StateViolation("state must be an object")
    if any(not isinstance(key, str) for key in state):
        raise StateViolation("state field names must be strings")
    unknown = set(state) - _ALLOWED_TOP_LEVEL
    if unknown:
        raise StateViolation(f"unsupported state fields: {sorted(unknown)}")
    result = deepcopy(dict(state))
    for field, label in (("run_id", "run_id"), ("org_id", "org_id"), ("actor_id", "actor_id")):
        if field in result:
            result[field] = _uuid(result[field], label)
    for field in ("workflow_version", "state_version"):
        if field in result and (isinstance(result[field], bool) or not isinstance(result[field], int) or result[field] < 1):
            raise StateViolation(f"{field} must be a positive integer")
    if "status" in result and result["status"] not in _STATUSES:
        raise StateViolation("status is not a valid graph state")
    for field in ("idempotency_key", "trace_id"):
        if field in result and (not isinstance(result[field], str) or not result[field].strip() or len(result[field]) > 200):
            raise StateViolation(f"{field} must be bounded text")
    _check_sensitive(result)
    for field in _REFERENCE_MAP_FIELDS:
        refs = result.get(field)
        if refs is not None:
            if not isinstance(refs, Mapping):
                raise StateViolation(f"{field} must be a reference map")
            for name, reference in refs.items():
                if not isinstance(name, str) or not name.strip() or len(name) > 128:
                    raise StateViolation(f"{field} keys must be bounded text")
                _check_reference(reference, field=f"{field}.{name}")
    for field in _REFERENCE_LIST_FIELDS:
        refs = result.get(field)
        if refs is not None:
            if not isinstance(refs, (list, tuple)):
                raise StateViolation(f"{field} must be a reference list")
            if len(refs) > 500:
                raise StateViolation(f"{field} exceeds the reference limit")
            for index, reference in enumerate(refs):
                _check_reference(reference, field=f"{field}[{index}]")
            result[field] = list(refs)
    for field in _REFERENCE_SCALAR_FIELDS:
        if field in result and result[field] is not None:
            _check_reference(result[field], field=field)
    encoded = _safe_json(result).encode("utf-8")
    if len(encoded) > max_bytes:
        raise StateViolation("graph state exceeds bounded size")
    return result


class BaseGraphState(TypedDict, total=False):
    run_id: str
    org_id: str
    actor_id: str
    workflow_key: str
    workflow_version: int
    input_refs: dict[str, str]
    current_node: str
    artifact_refs: dict[str, str]
    evidence_refs: list[str]
    qa_refs: list[str]
    policy_decision_ref: str
    human_interrupt_ref: str
    retry_context: dict[str, Any]
    idempotency_key: str
    trace_id: str
    error_ref: str
    status: str
    result_refs: dict[str, str]
    resume_token: str
    state_version: int
    last_node: str


ContentGraphState = BaseGraphState


@dataclass(frozen=True)
class ArtifactRef:
    id: str
    kind: str
    version: int = 1
    snapshot_hash: str | None = None
    org_id: str | None = None

    def as_contract(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "version": self.version,
                "snapshot_hash": self.snapshot_hash, "org_id": self.org_id}


@dataclass(frozen=True)
class EvidenceRef:
    id: str
    kind: str
    snapshot_hash: str
    source_ref: str | None = None

    def as_contract(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "snapshot_hash": self.snapshot_hash,
                "source_ref": self.source_ref}


@dataclass(frozen=True)
class PolicyRef:
    id: str
    version: int
    snapshot_hash: str

    def as_contract(self) -> dict[str, Any]:
        return {"id": self.id, "version": self.version, "snapshot_hash": self.snapshot_hash}


@dataclass(frozen=True)
class HumanInterruptRef:
    id: str
    kind: str
    status: str = "waiting"
    expires_at: str | None = None

    def as_contract(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "status": self.status, "expires_at": self.expires_at}


@dataclass(frozen=True)
class StateMigration:
    from_version: int
    to_version: int
    migrate: Any


def migrate_state(state: Mapping[str, Any], *, target_version: int,
                  migrations: list[StateMigration] | tuple[StateMigration, ...] = ()) -> dict[str, Any]:
    result = validate_state(state)
    current = int(result.get("state_version", 1))
    if current > target_version:
        raise StateViolation("state version is newer than requested target")
    by_source = {item.from_version: item for item in migrations}
    while current < target_version:
        migration = by_source.get(current)
        if migration is None or migration.to_version <= current:
            raise StateViolation(f"missing state migration from version {current}")
        result = validate_state(migration.migrate(deepcopy(result)))
        current = migration.to_version
        result["state_version"] = current
    result["state_version"] = target_version
    return validate_state(result)


def merge_state(base: Mapping[str, Any], *branches: Mapping[str, Any]) -> dict[str, Any]:
    result = validate_state(base)
    for branch in branches:
        candidate = validate_state(branch)
        for key, value in candidate.items():
            if key in result and result[key] != value and key not in {"artifact_refs", "evidence_refs", "qa_refs"}:
                raise StateViolation(f"parallel state conflict on {key}")
            if key == "artifact_refs":
                merged = dict(result.get(key, {})); merged.update(value); result[key] = merged
            elif key in {"evidence_refs", "qa_refs"}:
                result[key] = list(dict.fromkeys([*result.get(key, []), *value]))
            else:
                result[key] = deepcopy(value)
    return validate_state(result)


def state_hash(state: Mapping[str, Any]) -> str:
    return sha256(_safe_json(validate_state(state)).encode()).hexdigest()


__all__ = [
    "ArtifactRef", "BaseGraphState", "ContentGraphState", "EvidenceRef", "HumanInterruptRef",
    "PolicyRef", "StateMigration", "StateViolation", "merge_state", "migrate_state", "state_hash",
    "validate_state",
]
