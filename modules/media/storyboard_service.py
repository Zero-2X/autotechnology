"""Deterministic MEDIA-002 storyboards and rights-bound asset references."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from functools import wraps
from hashlib import sha256
import json
from pathlib import Path
import re
from threading import RLock
from typing import Any, Mapping, Protocol, Sequence
from uuid import UUID, uuid5

from jsonschema import Draft202012Validator, FormatChecker

from .script_service import (
    MediaScriptError,
    _canonical,
    _context as _script_context,
    _hash,
    _mapping,
    _schema_error,
    _stamp,
    _time as _script_time,
    _uuid as _script_uuid,
)


ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "packages" / "contracts" / "jsonschema"
STORYBOARD_VALIDATOR = Draft202012Validator(
    json.loads((CONTRACTS / "media-storyboard.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
STORYBOARD_VERSION_VALIDATOR = Draft202012Validator(
    json.loads((CONTRACTS / "media-storyboard-version.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
SCRIPT_VERSION_VALIDATOR = Draft202012Validator(
    json.loads((CONTRACTS / "media-script-version.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
ASSET_VERSION_VALIDATOR = Draft202012Validator(
    json.loads((CONTRACTS / "asset-version.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
RIGHTS_VERSION_VALIDATOR = Draft202012Validator(
    json.loads((CONTRACTS / "rights-record-version.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)

TEMPLATE_VERSION = "media-storyboard-v1"
SYSTEM_ACTOR = UUID("00000000-0000-4000-8000-000000000001")
STORYBOARD_NAMESPACE = UUID("7ddfd3d2-d23b-5e9e-b1cf-d06fa86e1f2e")
VERSION_NAMESPACE = UUID("c36ae5d2-8e6f-5ed5-a5ec-d2d9e4b09fd2")
HASH_RE = r"^[A-Fa-f0-9]{64}$"
ROLES = frozenset({"visual", "music", "font", "voiceover"})
MEDIA_TYPES = frozenset({"image", "audio", "video", "subtitle", "document", "thumbnail"})
ROLE_MEDIA = {
    "visual": frozenset({"image", "video", "thumbnail"}),
    "music": frozenset({"audio"}),
    "font": frozenset({"document"}),
    "voiceover": frozenset({"audio"}),
}


def _uuid(value: Any, field: str, *, code: str = "INVALID_STORYBOARD_INPUT") -> str:
    """Translate the MEDIA-001 helper's exception into this boundary's error type."""
    try:
        return _script_uuid(value, field, code=code)
    except MediaScriptError as exc:
        raise MediaStoryboardError(exc.code, str(exc)) from exc


def _time(value: Any, field: str) -> datetime:
    try:
        return _script_time(value, field)
    except MediaScriptError as exc:
        raise MediaStoryboardError(exc.code, str(exc)) from exc


def _context(*, org_id: UUID | str | None, actor_id: UUID | str | None, tenant_context: Any) -> tuple[str, str]:
    try:
        return _script_context(org_id=org_id, actor_id=actor_id, tenant_context=tenant_context)
    except MediaScriptError as exc:
        raise MediaStoryboardError(exc.code, str(exc)) from exc


class ScriptVersionPort(Protocol):
    def get_version(self, *, org_id: str, version_id: str) -> Mapping[str, Any]: ...


class AssetVersionPort(Protocol):
    def get_version(self, *, org_id: str, version_id: str) -> Mapping[str, Any]: ...


class RightsVersionPort(Protocol):
    def get_version(self, *, org_id: str, version_id: str) -> Mapping[str, Any]: ...


class MediaStoryboardError(ValueError):
    """Stable, non-sensitive MEDIA-002 application error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _error_schema(validator: Draft202012Validator, value: Mapping[str, Any], code: str) -> None:
    try:
        _schema_error(validator, value, code)
    except MediaScriptError as exc:
        raise MediaStoryboardError(exc.code, str(exc)) from exc


def _text(value: Any, field: str, maximum: int, *, code: str = "INVALID_STORYBOARD_INPUT") -> str:
    if not isinstance(value, str):
        raise MediaStoryboardError(code, f"{field} must be text")
    result = value.strip()
    if not result or len(result) > maximum:
        raise MediaStoryboardError(code, f"{field} has an invalid length")
    if any(ord(char) < 0x20 and char not in "\t\n\r" for char in result):
        raise MediaStoryboardError(code, f"{field} contains a control character")
    return result


def _safe_json(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return _stamp(value)
    if isinstance(value, Mapping):
        return {str(key): _safe_json(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_safe_json(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise MediaStoryboardError("INVALID_STORYBOARD_INPUT", "input contains a non-JSON value")


def _uuid_list(value: Any, field: str, *, required: bool = False) -> list[str]:
    if value is None:
        if required:
            raise MediaStoryboardError("RIGHTS_REFERENCE_REQUIRED", f"{field} is required")
        return []
    if isinstance(value, (str, bytes, Mapping)):
        raise MediaStoryboardError("RIGHTS_REFERENCE_INVALID", f"{field} must be an array")
    try:
        items = list(value)
    except TypeError as exc:
        raise MediaStoryboardError("RIGHTS_REFERENCE_INVALID", f"{field} must be an array") from exc
    result = sorted({_uuid(item, field, code="RIGHTS_REFERENCE_INVALID") for item in items})
    if required and not result:
        raise MediaStoryboardError("RIGHTS_REFERENCE_REQUIRED", f"{field} must not be empty")
    return result


def _collection(value: Any, field: str) -> dict[str, dict[str, Any]]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        items = [value] if "id" in value else list(value.values())
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items = list(value)
    else:
        raise MediaStoryboardError("REFERENCE_INVALID", f"{field} must be an object or array")
    result: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(items):
        try:
            candidate = _safe_json(_mapping(item, f"{field}[{index}]"))
        except MediaScriptError as exc:
            raise MediaStoryboardError("REFERENCE_INVALID", f"{field}[{index}] must be an object") from exc
        identity = _uuid(candidate.get("id"), f"{field}[{index}].id", code="REFERENCE_INVALID")
        if identity in result:
            raise MediaStoryboardError("REFERENCE_INVALID", f"{field} contains a duplicate id")
        result[identity] = candidate
    return result


def _audit_failures(method: Any) -> Any:
    @wraps(method)
    def wrapped(self: "MediaStoryboardService", *args: Any, **kwargs: Any) -> Any:
        try:
            return method(self, *args, **kwargs)
        except MediaStoryboardError as exc:
            context = kwargs.get("tenant_context")
            raw_org = kwargs.get("org_id")
            raw_actor = kwargs.get("actor_id")
            if isinstance(context, Mapping):
                raw_org = context.get("org_id") or context.get("tenant_id") or raw_org
                raw_actor = context.get("actor_id") or context.get("user_id") or raw_actor
            elif context is not None:
                raw_org = getattr(context, "org_id", None) or getattr(context, "tenant_id", None) or raw_org
                raw_actor = getattr(context, "actor_id", None) or getattr(context, "user_id", None) or raw_actor
            try:
                safe_org = _uuid(raw_org, "org_id") if raw_org is not None else None
            except Exception:
                safe_org = None
            try:
                safe_actor = _uuid(raw_actor, "actor_id") if raw_actor is not None else str(SYSTEM_ACTOR)
            except Exception:
                safe_actor = str(SYSTEM_ACTOR)
            try:
                safe_script = _uuid(kwargs.get("media_storyboard_id"), "media_storyboard_id") if kwargs.get("media_storyboard_id") else None
            except Exception:
                safe_script = None
            with self.store._lock:
                self.store.audit.append({
                    "operation": method.__name__, "org_id": safe_org, "media_storyboard_id": safe_script,
                    "version_no": kwargs.get("expected_version_no"), "status": "rejected",
                    "error_code": exc.code, "actor_id": safe_actor,
                    "trace_id": kwargs.get("trace_id") if isinstance(kwargs.get("trace_id"), str) else "media-storyboard",
                    "duration_ms": 0, "cost_units": 0,
                })
            raise
    return wrapped


class InMemoryMediaStoryboardStore:
    def __init__(self) -> None:
        self.storyboards: dict[str, dict[str, Any]] = {}
        self.versions: dict[str, dict[str, Any]] = {}
        self.versions_by_storyboard: dict[str, list[str]] = {}
        self.by_script: dict[tuple[str, str], str] = {}
        self.commands: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self._lock = RLock()

    def replay(self, *, org_id: str, namespace: str, key: str, request_hash: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.commands.get((org_id, namespace, key))
            if row is None:
                return None
            if row["request_hash"] != request_hash:
                raise MediaStoryboardError("IDEMPOTENCY_KEY_REUSED", "command payload differs from prior request")
            return deepcopy(row["response"])

    def create(self, *, root: Mapping[str, Any], version: Mapping[str, Any], namespace: str,
               key: str, request_hash: str, audit: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            command_key = (str(root["org_id"]), namespace, key)
            prior = self.commands.get(command_key)
            if prior is not None:
                if prior["request_hash"] != request_hash:
                    raise MediaStoryboardError("IDEMPOTENCY_KEY_REUSED", "command payload differs from prior request")
                return deepcopy(prior["response"])
            natural = (str(root["org_id"]), str(root["media_script_version_id"]))
            if natural in self.by_script:
                raise MediaStoryboardError("STORYBOARD_ALREADY_EXISTS", "storyboard already exists for this script version")
            root_copy, version_copy = deepcopy(dict(root)), deepcopy(dict(version))
            self.storyboards[root_copy["id"]] = root_copy
            self.versions[version_copy["id"]] = version_copy
            self.versions_by_storyboard[root_copy["id"]] = [version_copy["id"]]
            self.by_script[natural] = root_copy["id"]
            response = {"media_storyboard": root_copy, "version": version_copy}
            self.commands[command_key] = {"request_hash": request_hash, "response": deepcopy(response)}
            self.audit.append(deepcopy(dict(audit)))
            return deepcopy(response)

    def append(self, *, org_id: str, storyboard_id: str, expected_version_no: int,
               root: Mapping[str, Any], version: Mapping[str, Any], namespace: str,
               key: str, request_hash: str, audit: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            command_key = (org_id, namespace, key)
            prior = self.commands.get(command_key)
            if prior is not None:
                if prior["request_hash"] != request_hash:
                    raise MediaStoryboardError("IDEMPOTENCY_KEY_REUSED", "command payload differs from prior request")
                return deepcopy(prior["response"])
            current_root = self.storyboards.get(storyboard_id)
            if current_root is None or current_root["org_id"] != org_id:
                raise MediaStoryboardError("TENANT_SCOPE_VIOLATION", "storyboard is outside this organization")
            current = self.versions[current_root["current_version_id"]]
            if int(current["version_no"]) != expected_version_no:
                raise MediaStoryboardError("VERSION_CONFLICT", "storyboard current version changed")
            version_copy = deepcopy(dict(version))
            if version_copy["id"] in self.versions:
                raise MediaStoryboardError("STORYBOARD_VERSION_IMMUTABLE", "storyboard version already exists")
            root_copy = deepcopy(dict(root))
            self.versions[version_copy["id"]] = version_copy
            self.versions_by_storyboard[storyboard_id].append(version_copy["id"])
            self.storyboards[storyboard_id] = root_copy
            response = {"media_storyboard": root_copy, "version": version_copy}
            self.commands[command_key] = {"request_hash": request_hash, "response": deepcopy(response)}
            self.audit.append(deepcopy(dict(audit)))
            return deepcopy(response)

    def get_storyboard(self, *, org_id: str, storyboard_id: str) -> dict[str, Any]:
        with self._lock:
            value = self.storyboards.get(storyboard_id)
            if value is None or value["org_id"] != org_id:
                raise MediaStoryboardError("TENANT_SCOPE_VIOLATION", "storyboard is outside this organization")
            return deepcopy(value)

    def get_version(self, *, org_id: str, version_id: str) -> dict[str, Any]:
        with self._lock:
            value = self.versions.get(version_id)
            if value is None or value["org_id"] != org_id:
                raise MediaStoryboardError("TENANT_SCOPE_VIOLATION", "storyboard version is outside this organization")
            return deepcopy(value)

    def list_versions(self, *, org_id: str, storyboard_id: str) -> list[dict[str, Any]]:
        root = self.get_storyboard(org_id=org_id, storyboard_id=storyboard_id)
        with self._lock:
            return [deepcopy(self.versions[item]) for item in self.versions_by_storyboard[root["id"]]]


class MediaStoryboardService:
    def __init__(self, *, script_port: ScriptVersionPort | Any | None = None,
                 asset_port: AssetVersionPort | Any | None = None,
                 rights_port: RightsVersionPort | Any | None = None,
                 store: InMemoryMediaStoryboardStore | None = None,
                 clock: Any | None = None) -> None:
        self.script_port = script_port
        self.asset_port = asset_port
        self.rights_port = rights_port
        self.store = store or InMemoryMediaStoryboardStore()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def audit_log(self) -> tuple[dict[str, Any], ...]:
        with self.store._lock:
            return tuple(deepcopy(self.store.audit))

    def _now(self, value: Any | None, field: str) -> datetime:
        return _time(value if value is not None else self.clock(), field)

    def _script(self, *, tenant: str, value: Any, version_id: Any) -> dict[str, Any]:
        expected = _uuid(version_id, "media_script_version_id", code="SCRIPT_VERSION_NOT_FOUND") if version_id is not None else None
        candidate = value
        if candidate is None:
            if expected is None or self.script_port is None:
                raise MediaStoryboardError("SCRIPT_VERSION_NOT_FOUND", "an exact MediaScriptVersion is required")
            try:
                if hasattr(self.script_port, "get_version"):
                    candidate = self.script_port.get_version(org_id=tenant, version_id=expected)
                elif callable(self.script_port):
                    candidate = self.script_port(org_id=tenant, version_id=expected)
                else:
                    raise TypeError("script port has no get_version operation")
            except MediaStoryboardError:
                raise
            except Exception as exc:
                raise MediaStoryboardError("DEPENDENCY_UNAVAILABLE", "MediaScriptVersion lookup failed") from exc
        if isinstance(candidate, Mapping) and "version" in candidate:
            candidate = candidate["version"]
        try:
            script = _safe_json(_mapping(candidate, "media_script_version"))
        except Exception as exc:
            if isinstance(exc, MediaStoryboardError):
                raise
            raise MediaStoryboardError("SCRIPT_VERSION_INVALID", "MediaScriptVersion is invalid") from exc
        _error_schema(SCRIPT_VERSION_VALIDATOR, script, "SCRIPT_VERSION_INVALID")
        identity = _uuid(script.get("id"), "media_script_version.id", code="SCRIPT_VERSION_NOT_FOUND")
        if expected is not None and identity != expected:
            raise MediaStoryboardError("SCRIPT_VERSION_NOT_FOUND", "script port returned a different version")
        if _uuid(script.get("org_id"), "media_script_version.org_id") != tenant:
            raise MediaStoryboardError("TENANT_SCOPE_VIOLATION", "MediaScriptVersion is outside this organization")
        if script.get("status") in {"superseded", "withdrawn"}:
            raise MediaStoryboardError("SCRIPT_VERSION_NOT_USABLE", "withdrawn or superseded script cannot be storyboarded")
        segments = script.get("segments")
        if not isinstance(segments, list) or len(segments) != 3:
            raise MediaStoryboardError("SCRIPT_VERSION_INVALID", "script must contain three segments")
        previous = 0
        for expected_sequence, segment in enumerate(segments, 1):
            if segment["sequence"] != expected_sequence or segment["start_ms"] != previous or segment["end_ms"] <= segment["start_ms"]:
                raise MediaStoryboardError("SCRIPT_TIMELINE_INVALID", "script segment timeline is not contiguous")
            previous = segment["end_ms"]
        if previous != int(script["duration_seconds"]) * 1000:
            raise MediaStoryboardError("SCRIPT_TIMELINE_INVALID", "script timeline does not cover its duration")
        return script

    def _lookup(self, *, port: Any, tenant: str, identity: str, kind: str) -> dict[str, Any]:
        try:
            if hasattr(port, "get_version_by_id"):
                candidate = port.get_version_by_id(org_id=tenant, version_id=identity)
            elif hasattr(port, "get_by_version_id"):
                candidate = port.get_by_version_id(org_id=tenant, version_id=identity)
            elif hasattr(port, "get_version"):
                try:
                    candidate = port.get_version(org_id=tenant, version_id=identity)
                except TypeError:
                    # The provenance RightsService also requires the parent
                    # rights_record_id. Adapters can expose a version-only
                    # lookup or accept the version id as the parent key.
                    candidate = port.get_version(
                        org_id=tenant, rights_record_id=identity, version_id=identity
                    )
            elif hasattr(port, "get"):
                candidate = port.get(org_id=tenant, version_id=identity)
            elif callable(port):
                candidate = port(org_id=tenant, version_id=identity)
            else:
                raise TypeError(f"{kind} port has no get operation")
        except MediaStoryboardError:
            raise
        except (KeyError, LookupError) as exc:
            raise MediaStoryboardError(f"{kind.upper()}_NOT_FOUND", f"{kind} version does not exist") from exc
        except Exception as exc:
            provider_code = getattr(exc, "code", None)
            if isinstance(provider_code, str) and provider_code.endswith("_NOT_FOUND"):
                raise MediaStoryboardError(provider_code, f"{kind} version does not exist") from exc
            raise MediaStoryboardError("DEPENDENCY_UNAVAILABLE", f"{kind} lookup failed") from exc
        if isinstance(candidate, Mapping) and "version" in candidate:
            candidate = candidate["version"]
        try:
            return _safe_json(_mapping(candidate, kind))
        except MediaStoryboardError:
            raise
        except Exception as exc:
            raise MediaStoryboardError(f"{kind.upper()}_INVALID", f"{kind} version is invalid") from exc

    def _asset(self, *, tenant: str, identity: str, supplied: dict[str, dict[str, Any]]) -> dict[str, Any]:
        candidate = supplied.get(identity)
        if candidate is None:
            if self.asset_port is None:
                raise MediaStoryboardError("ASSET_VERSION_NOT_FOUND", "referenced AssetVersion was not supplied")
            candidate = self._lookup(port=self.asset_port, tenant=tenant, identity=identity, kind="asset_version")
        _error_schema(ASSET_VERSION_VALIDATOR, candidate, "ASSET_VERSION_INVALID")
        if _uuid(candidate.get("id"), "asset_version.id", code="ASSET_VERSION_NOT_FOUND") != identity:
            raise MediaStoryboardError("ASSET_VERSION_NOT_FOUND", "AssetVersion port returned a different version")
        if _uuid(candidate.get("org_id"), "asset_version.org_id") != tenant:
            raise MediaStoryboardError("TENANT_SCOPE_VIOLATION", "AssetVersion is outside this organization")
        if candidate.get("status") != "approved":
            raise MediaStoryboardError("ASSET_VERSION_NOT_APPROVED", "AssetVersion must be approved")
        if candidate.get("storage_object_ref") is not None and not str(candidate["storage_object_ref"]).startswith("private://"):
            raise MediaStoryboardError("ASSET_VERSION_INVALID", "AssetVersion storage reference must be private")
        return candidate

    def _rights(self, *, tenant: str, identity: str, supplied: dict[str, dict[str, Any]],
                at: datetime, script: Mapping[str, Any], media_type: str) -> dict[str, Any]:
        candidate = supplied.get(identity)
        if candidate is None:
            if self.rights_port is None:
                raise MediaStoryboardError("RIGHTS_VERSION_NOT_FOUND", "referenced RightsRecordVersion was not supplied")
            candidate = self._lookup(port=self.rights_port, tenant=tenant, identity=identity, kind="rights_version")
        _error_schema(RIGHTS_VERSION_VALIDATOR, candidate, "RIGHTS_VERSION_INVALID")
        if _uuid(candidate.get("id"), "rights_version.id", code="RIGHTS_VERSION_NOT_FOUND") != identity:
            raise MediaStoryboardError("RIGHTS_VERSION_NOT_FOUND", "RightsVersion port returned a different version")
        if _uuid(candidate.get("org_id"), "rights_version.org_id") != tenant:
            raise MediaStoryboardError("TENANT_SCOPE_VIOLATION", "RightsRecordVersion is outside this organization")
        if candidate.get("status") != "verified":
            raise MediaStoryboardError("RIGHTS_NOT_VERIFIED", "RightsRecordVersion must be verified")
        if candidate.get("permitted_use") not in {"derivative", "commercial"}:
            raise MediaStoryboardError("RIGHTS_USE_NOT_ALLOWED", "rights must allow derivative or commercial use")
        valid_from = candidate.get("valid_from")
        valid_to = candidate.get("valid_to")
        if valid_from is not None and at < _time(valid_from, "rights.valid_from"):
            raise MediaStoryboardError("RIGHTS_NOT_CURRENT", "rights are not yet valid")
        if valid_to is not None and at >= _time(valid_to, "rights.valid_to"):
            raise MediaStoryboardError("RIGHTS_NOT_CURRENT", "rights have expired")
        regions = {str(item).lower() for item in candidate.get("permitted_regions", [])}
        locales = {str(item).lower() for item in candidate.get("permitted_locales", [])}
        media = {str(item).lower() for item in candidate.get("permitted_media", [])}
        market = str(script["market"]).lower()
        locale = str(script["locale"]).lower()
        if regions and market not in regions and "*" not in regions and "all" not in regions:
            raise MediaStoryboardError("RIGHTS_SCOPE_MISMATCH", "rights do not cover the script market")
        if locales and locale not in locales and locale.split("-", 1)[0] not in locales and "*" not in locales and "all" not in locales:
            raise MediaStoryboardError("RIGHTS_SCOPE_MISMATCH", "rights do not cover the script locale")
        if media and media_type.lower() not in media and "*" not in media and "all" not in media:
            raise MediaStoryboardError("RIGHTS_SCOPE_MISMATCH", "rights do not cover the asset media type")
        source_snapshot_ids = candidate.get("source_snapshot_ids")
        if (
            not isinstance(source_snapshot_ids, list)
            or not source_snapshot_ids
            or any(not isinstance(item, str) for item in source_snapshot_ids)
            or not isinstance(candidate.get("policy_rule_version"), str)
            or not candidate["policy_rule_version"].strip()
        ):
            raise MediaStoryboardError("RIGHTS_VERSION_INVALID", "rights require source snapshots and policy rule version")
        if (
            not isinstance(candidate.get("snapshot_hash"), str)
            or not re.fullmatch(HASH_RE, candidate["snapshot_hash"])
        ):
            raise MediaStoryboardError("RIGHTS_VERSION_INVALID", "rights snapshot hash is invalid")
        return candidate

    def _plan(
        self, *, tenant: str, script: Mapping[str, Any], shots: Any,
        asset_versions: Any, rights_versions: Any, at: datetime,
    ) -> tuple[list[dict[str, Any]], list[str], int]:
        if not isinstance(shots, Sequence) or isinstance(shots, (str, bytes, bytearray)) or not shots:
            raise MediaStoryboardError("SHOT_PLAN_INVALID", "shots must be a nonempty array")
        asset_map = _collection(asset_versions, "asset_versions")
        rights_map = _collection(rights_versions, "rights_versions")
        intervals = {int(item["sequence"]): (int(item["start_ms"]), int(item["end_ms"])) for item in script["segments"]}
        normalized: list[dict[str, Any]] = []
        seen_sequences: set[int] = set()
        previous_end = 0
        all_rights: set[str] = set()
        asset_count = 0
        ordered_shots: list[tuple[int, int, Mapping[str, Any]]] = []
        for index, raw in enumerate(shots):
            if not isinstance(raw, Mapping):
                raise MediaStoryboardError("SHOT_PLAN_INVALID", f"shots[{index}] must be an object")
            sequence = raw.get("sequence")
            if type(sequence) is not int or sequence < 1 or sequence in seen_sequences:
                raise MediaStoryboardError("SHOT_PLAN_INVALID", "shot sequences must be unique positive integers")
            seen_sequences.add(sequence)
            ordered_shots.append((sequence, index, raw))
        for sequence, original_index, raw in sorted(ordered_shots, key=lambda item: item[0]):
            index = original_index
            segment_sequence = raw.get("script_segment_sequence")
            if type(segment_sequence) is not int or segment_sequence not in intervals:
                raise MediaStoryboardError("SHOT_PLAN_INVALID", "shot script segment sequence is invalid")
            try:
                start_ms, end_ms = int(raw["start_ms"]), int(raw["end_ms"])
            except (KeyError, TypeError, ValueError) as exc:
                raise MediaStoryboardError("SHOT_PLAN_INVALID", "shot timing is invalid") from exc
            if start_ms != previous_end or end_ms <= start_ms or end_ms - start_ms < 500:
                raise MediaStoryboardError("SHOT_TIMELINE_INVALID", "shots must be contiguous and at least 500ms")
            segment_start, segment_end = intervals[segment_sequence]
            if start_ms < segment_start or end_ms > segment_end:
                raise MediaStoryboardError("SHOT_TIMELINE_INVALID", "shot must remain inside its script segment")
            purpose = _text(raw.get("purpose"), f"shots[{index}].purpose", 512, code="SHOT_PLAN_INVALID")
            transition = raw.get("transition", "none")
            if transition not in {"cut", "fade", "dissolve", "none"}:
                raise MediaStoryboardError("SHOT_PLAN_INVALID", "shot transition is invalid")
            raw_refs = raw.get("asset_refs", [])
            if not isinstance(raw_refs, Sequence) or isinstance(raw_refs, (str, bytes, bytearray)):
                raise MediaStoryboardError("ASSET_REFERENCE_INVALID", "shot asset_refs must be an array")
            refs: list[dict[str, Any]] = []
            ref_keys: set[tuple[str, str]] = set()
            for ref_index, raw_ref in enumerate(raw_refs):
                if not isinstance(raw_ref, Mapping):
                    raise MediaStoryboardError("ASSET_REFERENCE_INVALID", "asset reference must be an object")
                role = raw_ref.get("role")
                if role not in ROLES:
                    raise MediaStoryboardError("ASSET_REFERENCE_INVALID", "asset role is invalid")
                asset_id = _uuid(raw_ref.get("asset_version_id"), "asset_version_id", code="ASSET_VERSION_NOT_FOUND")
                key = (role, asset_id)
                if key in ref_keys:
                    raise MediaStoryboardError("ASSET_REFERENCE_INVALID", "duplicate asset role/reference in shot")
                ref_keys.add(key)
                asset = self._asset(tenant=tenant, identity=asset_id, supplied=asset_map)
                if asset["variant_version_id"] != script["variant_version_id"]:
                    raise MediaStoryboardError("ASSET_LINEAGE_MISMATCH", "AssetVersion belongs to a different VariantVersion")
                if asset["region_profile_version_id"] != script["region_profile_version_id"]:
                    raise MediaStoryboardError("ASSET_LINEAGE_MISMATCH", "AssetVersion belongs to a different region profile")
                if asset.get("policy_snapshot_id") != script["policy_snapshot_id"]:
                    raise MediaStoryboardError("ASSET_LINEAGE_MISMATCH", "AssetVersion belongs to a different policy snapshot")
                media_type = str(asset["media_type"])
                if media_type not in ROLE_MEDIA[role]:
                    raise MediaStoryboardError("ASSET_ROLE_MISMATCH", "asset media type is incompatible with its role")
                asset_hash = asset.get("file_hash")
                if not isinstance(asset_hash, str) or not re.fullmatch(HASH_RE, asset_hash):
                    raise MediaStoryboardError("ASSET_VERSION_INVALID", "approved AssetVersion requires a valid file hash")
                rights_ids = _uuid_list(raw_ref.get("rights_record_version_ids"), "rights_record_version_ids", required=True)
                rights_snapshots: list[dict[str, str]] = []
                for rights_id in rights_ids:
                    rights = self._rights(tenant=tenant, identity=rights_id, supplied=rights_map, at=at, script=script, media_type=media_type)
                    rights_snapshots.append({"id": rights_id, "snapshot_hash": str(rights["snapshot_hash"]).lower()})
                    all_rights.add(rights_id)
                refs.append({
                    "role": role, "asset_version_id": asset_id, "media_type": media_type,
                    "format": str(asset["format"]), "storage_object_ref": asset.get("storage_object_ref"),
                    "asset_snapshot_hash": asset_hash.lower(),
                    "rights_record_version_ids": rights_ids,
                    "rights_snapshots": sorted(rights_snapshots, key=lambda item: item["id"]),
                })
                asset_count += 1
            refs.sort(key=lambda item: (item["role"], item["asset_version_id"], item["rights_record_version_ids"]))
            normalized.append({
                "sequence": sequence, "script_segment_sequence": segment_sequence,
                "start_ms": start_ms, "end_ms": end_ms, "purpose": purpose,
                "asset_refs": refs, "transition": transition,
            })
            previous_end = end_ms
        if [item["sequence"] for item in normalized] != list(range(1, len(normalized) + 1)):
            raise MediaStoryboardError("SHOT_PLAN_INVALID", "shot sequences must start at one and be contiguous")
        if previous_end != int(script["duration_seconds"]) * 1000:
            raise MediaStoryboardError("SHOT_TIMELINE_INVALID", "shots must cover the full script duration")
        return normalized, sorted(all_rights), asset_count

    def _build_version(
        self, *, tenant: str, actor: str, script: Mapping[str, Any], storyboard_id: str,
        version_no: int, shots: list[dict[str, Any]], rights_ids: list[str], asset_count: int,
        reason: str | None, supersedes: str | None, at: datetime, status: str,
    ) -> tuple[dict[str, Any], str]:
        material = {
            "org_id": tenant, "media_storyboard_id": storyboard_id,
            "media_script_version_id": script["id"], "version_no": version_no,
            "duration_seconds": script["duration_seconds"], "locale": script["locale"],
            "market": script["market"], "region_profile_version_id": script["region_profile_version_id"],
            "policy_snapshot_id": script["policy_snapshot_id"], "template_version": TEMPLATE_VERSION,
            "status": status, "shots": shots, "asset_reference_count": asset_count,
            "rights_snapshot_ids": rights_ids, "revision_reason": reason,
            "supersedes_version_id": supersedes,
            "source_script_snapshot_hash": str(script["snapshot_hash"]).lower(),
        }
        snapshot_hash = _hash(material)
        version_id = str(uuid5(VERSION_NAMESPACE, f"{storyboard_id}:{version_no}:{snapshot_hash}"))
        stamp = _stamp(at)
        version = {"id": version_id, **material, "snapshot_hash": snapshot_hash, "created_by": actor, "created_at": stamp}
        _error_schema(STORYBOARD_VERSION_VALIDATOR, version, "INVALID_STORYBOARD_VERSION")
        return version, stamp

    @_audit_failures
    def create_storyboard(
        self, script_version: Any | None = None, *, media_script_version_id: UUID | str | None = None,
        shots: Any, asset_versions: Any | None = None, rights_versions: Any | None = None,
        org_id: UUID | str | None = None, tenant_context: Any | None = None,
        actor_id: UUID | str | None = None, trace_id: str = "media-storyboard-create",
        idempotency_key: str, created_at: Any | None = None,
    ) -> dict[str, Any]:
        tenant, actor = _context(org_id=org_id, actor_id=actor_id, tenant_context=tenant_context)
        trace = _text(trace_id, "trace_id", 256)
        key = _text(idempotency_key, "idempotency_key", 200)
        at = self._now(created_at, "created_at")
        script = self._script(tenant=tenant, value=script_version, version_id=media_script_version_id)
        normalized_shots, rights_ids, asset_count = self._plan(
            tenant=tenant, script=script, shots=shots, asset_versions=asset_versions,
            rights_versions=rights_versions, at=at,
        )
        request_hash = _hash({
            "operation": "create", "media_script_version_id": script["id"],
            "script_snapshot_hash": script["snapshot_hash"], "shots": normalized_shots,
            "rights_snapshot_ids": rights_ids,
        })
        replay = self.store.replay(org_id=tenant, namespace="create", key=key, request_hash=request_hash)
        if replay is not None:
            return replay
        storyboard_id = str(uuid5(STORYBOARD_NAMESPACE, f"{tenant}:{script['id']}"))
        version, stamp = self._build_version(
            tenant=tenant, actor=actor, script=script, storyboard_id=storyboard_id,
            version_no=1, shots=normalized_shots, rights_ids=rights_ids, asset_count=asset_count,
            reason=None, supersedes=None, at=at, status="draft",
        )
        root = {
            "id": storyboard_id, "org_id": tenant, "media_script_version_id": script["id"],
            "duration_seconds": script["duration_seconds"], "current_version_id": version["id"],
            "status": "draft", "created_by": actor, "created_at": stamp, "updated_at": stamp,
        }
        _error_schema(STORYBOARD_VALIDATOR, root, "INVALID_STORYBOARD")
        return self.store.create(
            root=root, version=version, namespace="create", key=key, request_hash=request_hash,
            audit={
                "operation": "create_storyboard", "org_id": tenant, "media_storyboard_id": storyboard_id,
                "version_id": version["id"], "version_no": 1, "media_script_version_id": script["id"],
                "policy_snapshot_id": script["policy_snapshot_id"], "request_hash": request_hash,
                "snapshot_hash": version["snapshot_hash"], "status": "created", "actor_id": actor,
                "trace_id": trace, "duration_ms": 0, "cost_units": 0, "created_at": stamp,
            },
        )

    @_audit_failures
    def revise_storyboard(
        self, *, media_storyboard_id: UUID | str, expected_version_no: int, shots: Any,
        asset_versions: Any | None = None, rights_versions: Any | None = None,
        revision_reason: str, script_version: Any | None = None,
        org_id: UUID | str | None = None, tenant_context: Any | None = None,
        actor_id: UUID | str | None = None, trace_id: str = "media-storyboard-revise",
        idempotency_key: str, revised_at: Any | None = None,
    ) -> dict[str, Any]:
        tenant, actor = _context(org_id=org_id, actor_id=actor_id, tenant_context=tenant_context)
        storyboard_id = _uuid(media_storyboard_id, "media_storyboard_id")
        trace = _text(trace_id, "trace_id", 256)
        key = _text(idempotency_key, "idempotency_key", 200)
        reason = _text(revision_reason, "revision_reason", 1000, code="STORYBOARD_REVISION_INVALID")
        if type(expected_version_no) is not int or expected_version_no < 1:
            raise MediaStoryboardError("VERSION_CONFLICT", "expected_version_no must be positive")
        root = self.store.get_storyboard(org_id=tenant, storyboard_id=storyboard_id)
        current = self.store.get_version(org_id=tenant, version_id=root["current_version_id"])
        if int(current["version_no"]) != expected_version_no:
            raise MediaStoryboardError("VERSION_CONFLICT", "storyboard current version changed")
        script = self._script(tenant=tenant, value=script_version, version_id=current["media_script_version_id"])
        if str(script["snapshot_hash"]).lower() != str(current["source_script_snapshot_hash"]).lower():
            raise MediaStoryboardError("SCRIPT_SNAPSHOT_MISMATCH", "script snapshot changed for this storyboard")
        at = self._now(revised_at, "revised_at")
        normalized_shots, rights_ids, asset_count = self._plan(
            tenant=tenant, script=script, shots=shots, asset_versions=asset_versions,
            rights_versions=rights_versions, at=at,
        )
        request_hash = _hash({
            "operation": "revise", "media_storyboard_id": storyboard_id,
            "expected_version_no": expected_version_no, "shots": normalized_shots,
            "rights_snapshot_ids": rights_ids, "revision_reason": reason,
        })
        replay = self.store.replay(org_id=tenant, namespace="revise", key=key, request_hash=request_hash)
        if replay is not None:
            return replay
        version, stamp = self._build_version(
            tenant=tenant, actor=actor, script=script, storyboard_id=storyboard_id,
            version_no=expected_version_no + 1, shots=normalized_shots, rights_ids=rights_ids,
            asset_count=asset_count, reason=reason, supersedes=current["id"], at=at, status="edited",
        )
        updated_root = {**root, "current_version_id": version["id"], "updated_at": stamp}
        _error_schema(STORYBOARD_VALIDATOR, updated_root, "INVALID_STORYBOARD")
        return self.store.append(
            org_id=tenant, storyboard_id=storyboard_id, expected_version_no=expected_version_no,
            root=updated_root, version=version, namespace="revise", key=key, request_hash=request_hash,
            audit={
                "operation": "revise_storyboard", "org_id": tenant, "media_storyboard_id": storyboard_id,
                "version_id": version["id"], "version_no": expected_version_no + 1,
                "media_script_version_id": script["id"], "policy_snapshot_id": script["policy_snapshot_id"],
                "request_hash": request_hash, "snapshot_hash": version["snapshot_hash"],
                "status": "edited", "actor_id": actor, "trace_id": trace,
                "duration_ms": 0, "cost_units": 0, "created_at": stamp,
            },
        )

    def get_storyboard(self, *, media_storyboard_id: UUID | str, org_id: UUID | str | None = None,
                       tenant_context: Any | None = None) -> dict[str, Any]:
        tenant, _ = _context(org_id=org_id, actor_id=None, tenant_context=tenant_context)
        return self.store.get_storyboard(org_id=tenant, storyboard_id=_uuid(media_storyboard_id, "media_storyboard_id"))

    def get_version(self, *, version_id: UUID | str, org_id: UUID | str | None = None,
                    tenant_context: Any | None = None) -> dict[str, Any]:
        tenant, _ = _context(org_id=org_id, actor_id=None, tenant_context=tenant_context)
        return self.store.get_version(org_id=tenant, version_id=_uuid(version_id, "version_id"))

    def list_versions(self, *, media_storyboard_id: UUID | str, org_id: UUID | str | None = None,
                      tenant_context: Any | None = None) -> list[dict[str, Any]]:
        tenant, _ = _context(org_id=org_id, actor_id=None, tenant_context=tenant_context)
        return self.store.list_versions(org_id=tenant, storyboard_id=_uuid(media_storyboard_id, "media_storyboard_id"))


StoryboardService = MediaStoryboardService
MediaStoryboardStore = InMemoryMediaStoryboardStore


__all__ = [
    "AssetVersionPort", "InMemoryMediaStoryboardStore", "MediaStoryboardError",
    "MediaStoryboardService", "MediaStoryboardStore", "RightsVersionPort",
    "ScriptVersionPort", "StoryboardService", "TEMPLATE_VERSION",
]
