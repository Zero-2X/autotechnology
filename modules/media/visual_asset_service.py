"""Deterministic cover, thumbnail and keyframe AssetVersion references."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from functools import wraps
import json
from pathlib import Path
import re
from threading import RLock
from typing import Any, Mapping, Protocol, Sequence
from uuid import UUID, uuid5

from jsonschema import Draft202012Validator, FormatChecker

from .script_service import (
    MediaScriptError,
    _context as _script_context,
    _hash,
    _mapping,
    _schema_error as _script_schema_error,
    _stamp,
    _time as _script_time,
    _uuid as _script_uuid,
)


ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "packages" / "contracts" / "jsonschema"
VISUAL_SET_VALIDATOR = Draft202012Validator(
    json.loads((CONTRACTS / "media-visual-asset-set.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
VISUAL_VERSION_VALIDATOR = Draft202012Validator(
    json.loads((CONTRACTS / "media-visual-asset-set-version.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
SCRIPT_VERSION_VALIDATOR = Draft202012Validator(
    json.loads((CONTRACTS / "media-script-version.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
STORYBOARD_VERSION_VALIDATOR = Draft202012Validator(
    json.loads((CONTRACTS / "media-storyboard-version.schema.json").read_text(encoding="utf-8")),
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

TEMPLATE_VERSION = "media-visual-asset-set-v1"
SYSTEM_ACTOR = UUID("00000000-0000-4000-8000-000000000001")
SET_NAMESPACE = UUID("5b5e3e8d-5b89-5f95-97f2-0a6d01fc72c8")
VERSION_NAMESPACE = UUID("c6c4f1f2-7c0f-5dcb-a2a7-4e8bd7d97fb6")
HASH_RE = r"^[A-Fa-f0-9]{64}$"
ROLES = frozenset({"cover", "thumbnail", "keyframe"})
ROLE_MEDIA = {
    "cover": frozenset({"image", "video", "thumbnail"}),
    "thumbnail": frozenset({"image", "thumbnail"}),
    "keyframe": frozenset({"image", "video", "thumbnail"}),
}
SENSITIVE_KEYS = frozenset({"model", "provider", "credential", "token", "secret", "password", "authorization", "api_key", "raw_output"})


class ScriptVersionPort(Protocol):
    def get_version(self, *, org_id: str, version_id: str) -> Mapping[str, Any]: ...


class StoryboardVersionPort(Protocol):
    def get_version(self, *, org_id: str, version_id: str) -> Mapping[str, Any]: ...


class AssetVersionPort(Protocol):
    def get_version(self, *, org_id: str, version_id: str) -> Mapping[str, Any]: ...


class RightsVersionPort(Protocol):
    def get_version(self, *, org_id: str, version_id: str) -> Mapping[str, Any]: ...


class MediaVisualAssetError(ValueError):
    """Stable, non-sensitive MEDIA-003B application error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _uuid(value: Any, field: str, *, code: str = "INVALID_VISUAL_ASSET_INPUT") -> str:
    try:
        return _script_uuid(value, field, code=code)
    except MediaScriptError as exc:
        raise MediaVisualAssetError(exc.code, str(exc)) from exc


def _time(value: Any, field: str) -> datetime:
    try:
        return _script_time(value, field)
    except MediaScriptError as exc:
        raise MediaVisualAssetError(exc.code, str(exc)) from exc


def _context(*, org_id: UUID | str | None, actor_id: UUID | str | None, tenant_context: Any) -> tuple[str, str]:
    try:
        return _script_context(org_id=org_id, actor_id=actor_id, tenant_context=tenant_context)
    except MediaScriptError as exc:
        raise MediaVisualAssetError(exc.code, str(exc)) from exc


def _error_schema(validator: Draft202012Validator, value: Mapping[str, Any], code: str) -> None:
    try:
        _script_schema_error(validator, value, code)
    except MediaScriptError as exc:
        raise MediaVisualAssetError(exc.code, str(exc)) from exc


def _mapping_safe(value: Any, field: str) -> dict[str, Any]:
    try:
        return deepcopy(dict(_mapping(value, field)))
    except MediaScriptError as exc:
        raise MediaVisualAssetError("INVALID_VISUAL_ASSET_INPUT", f"{field} must be an object") from exc


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
    raise MediaVisualAssetError("INVALID_VISUAL_ASSET_INPUT", "input contains a non-JSON value")


def _text(value: Any, field: str, maximum: int, *, code: str = "INVALID_VISUAL_ASSET_INPUT") -> str:
    if not isinstance(value, str):
        raise MediaVisualAssetError(code, f"{field} must be text")
    result = value.strip()
    if not result or len(result) > maximum:
        raise MediaVisualAssetError(code, f"{field} has an invalid length")
    if any(ord(char) < 0x20 and char not in "\t\n\r" for char in result):
        raise MediaVisualAssetError(code, f"{field} contains a control character")
    return result


def _reject_sensitive(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_KEYS:
                raise MediaVisualAssetError("SENSITIVE_INPUT_REJECTED", "visual asset input contains a restricted field")
            _reject_sensitive(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _reject_sensitive(item)


def _collection(value: Any, field: str) -> dict[str, dict[str, Any]]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        items = [value] if "id" in value else list(value.values())
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items = list(value)
    else:
        raise MediaVisualAssetError("REFERENCE_INVALID", f"{field} must be an object or array")
    result: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(items):
        candidate = _safe_json(_mapping_safe(item, f"{field}[{index}]"))
        _reject_sensitive(candidate)
        identity = _uuid(candidate.get("id"), f"{field}[{index}].id", code="REFERENCE_INVALID")
        if identity in result:
            raise MediaVisualAssetError("REFERENCE_INVALID", f"{field} contains a duplicate id")
        result[identity] = candidate
    return result


def _uuid_list(value: Any, field: str) -> list[str]:
    if value is None or isinstance(value, (str, bytes, Mapping)):
        raise MediaVisualAssetError("RIGHTS_REFERENCE_REQUIRED", f"{field} must be a nonempty array")
    try:
        values = list(value)
    except TypeError as exc:
        raise MediaVisualAssetError("RIGHTS_REFERENCE_REQUIRED", f"{field} must be a nonempty array") from exc
    result = sorted({_uuid(item, field, code="RIGHTS_REFERENCE_INVALID") for item in values})
    if not result:
        raise MediaVisualAssetError("RIGHTS_REFERENCE_REQUIRED", f"{field} must be nonempty")
    return result


def _audit_failures(method: Any) -> Any:
    @wraps(method)
    def wrapped(self: "MediaVisualAssetSetService", *args: Any, **kwargs: Any) -> Any:
        try:
            return method(self, *args, **kwargs)
        except MediaVisualAssetError as exc:
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
                safe_set = _uuid(kwargs.get("media_visual_asset_set_id"), "media_visual_asset_set_id") if kwargs.get("media_visual_asset_set_id") else None
            except Exception:
                safe_set = None
            with self.store._lock:
                self.store.audit.append({
                    "operation": method.__name__, "org_id": safe_org, "media_visual_asset_set_id": safe_set,
                    "version_no": kwargs.get("expected_version_no"), "status": "rejected", "error_code": exc.code,
                    "actor_id": safe_actor, "trace_id": kwargs.get("trace_id") if isinstance(kwargs.get("trace_id"), str) else "media-visual-asset",
                    "duration_ms": 0, "cost_units": 0,
                })
            raise
    return wrapped


class InMemoryMediaVisualAssetSetStore:
    def __init__(self) -> None:
        self.sets: dict[str, dict[str, Any]] = {}
        self.versions: dict[str, dict[str, Any]] = {}
        self.versions_by_set: dict[str, list[str]] = {}
        self.by_source: dict[tuple[str, str, str], str] = {}
        self.commands: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self._lock = RLock()

    def replay(self, *, org_id: str, namespace: str, key: str, request_hash: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.commands.get((org_id, namespace, key))
            if row is None:
                return None
            if row["request_hash"] != request_hash:
                raise MediaVisualAssetError("IDEMPOTENCY_KEY_REUSED", "command payload differs from prior request")
            return deepcopy(row["response"])

    def create(self, *, root: Mapping[str, Any], version: Mapping[str, Any], namespace: str, key: str,
               request_hash: str, audit: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            command_key = (str(root["org_id"]), namespace, key)
            prior = self.commands.get(command_key)
            if prior is not None:
                if prior["request_hash"] != request_hash:
                    raise MediaVisualAssetError("IDEMPOTENCY_KEY_REUSED", "command payload differs from prior request")
                return deepcopy(prior["response"])
            natural = (str(root["org_id"]), str(root["media_script_version_id"]), str(root.get("media_storyboard_version_id") or "-"))
            if natural in self.by_source:
                raise MediaVisualAssetError("VISUAL_ASSET_SET_ALREADY_EXISTS", "visual asset set already exists for this source")
            root_copy, version_copy = deepcopy(dict(root)), deepcopy(dict(version))
            self.sets[root_copy["id"]] = root_copy
            self.versions[version_copy["id"]] = version_copy
            self.versions_by_set[root_copy["id"]] = [version_copy["id"]]
            self.by_source[natural] = root_copy["id"]
            response = {"media_visual_asset_set": root_copy, "version": version_copy}
            self.commands[command_key] = {"request_hash": request_hash, "response": deepcopy(response)}
            self.audit.append(deepcopy(dict(audit)))
            return deepcopy(response)

    def append(self, *, org_id: str, set_id: str, expected_version_no: int, root: Mapping[str, Any],
               version: Mapping[str, Any], namespace: str, key: str, request_hash: str,
               audit: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            command_key = (org_id, namespace, key)
            prior = self.commands.get(command_key)
            if prior is not None:
                if prior["request_hash"] != request_hash:
                    raise MediaVisualAssetError("IDEMPOTENCY_KEY_REUSED", "command payload differs from prior request")
                return deepcopy(prior["response"])
            current_root = self.sets.get(set_id)
            if current_root is None or current_root["org_id"] != org_id:
                raise MediaVisualAssetError("TENANT_SCOPE_VIOLATION", "visual asset set is outside this organization")
            current = self.versions[current_root["current_version_id"]]
            if int(current["version_no"]) != expected_version_no:
                raise MediaVisualAssetError("VERSION_CONFLICT", "visual asset set current version changed")
            version_copy = deepcopy(dict(version))
            if version_copy["id"] in self.versions:
                raise MediaVisualAssetError("VISUAL_ASSET_VERSION_IMMUTABLE", "visual asset version already exists")
            root_copy = deepcopy(dict(root))
            self.versions[version_copy["id"]] = version_copy
            self.versions_by_set[set_id].append(version_copy["id"])
            self.sets[set_id] = root_copy
            response = {"media_visual_asset_set": root_copy, "version": version_copy}
            self.commands[command_key] = {"request_hash": request_hash, "response": deepcopy(response)}
            self.audit.append(deepcopy(dict(audit)))
            return deepcopy(response)

    def get_set(self, *, org_id: str, set_id: str) -> dict[str, Any]:
        with self._lock:
            value = self.sets.get(set_id)
            if value is None or value["org_id"] != org_id:
                raise MediaVisualAssetError("TENANT_SCOPE_VIOLATION", "visual asset set is outside this organization")
            return deepcopy(value)

    def get_version(self, *, org_id: str, version_id: str) -> dict[str, Any]:
        with self._lock:
            value = self.versions.get(version_id)
            if value is None or value["org_id"] != org_id:
                raise MediaVisualAssetError("TENANT_SCOPE_VIOLATION", "visual asset version is outside this organization")
            return deepcopy(value)

    def list_versions(self, *, org_id: str, set_id: str) -> list[dict[str, Any]]:
        root = self.get_set(org_id=org_id, set_id=set_id)
        with self._lock:
            return [deepcopy(self.versions[item]) for item in self.versions_by_set[root["id"]]]


class MediaVisualAssetSetService:
    def __init__(self, *, script_port: ScriptVersionPort | Any | None = None,
                 storyboard_port: StoryboardVersionPort | Any | None = None,
                 asset_port: AssetVersionPort | Any | None = None,
                 rights_port: RightsVersionPort | Any | None = None,
                 store: InMemoryMediaVisualAssetSetStore | None = None, clock: Any | None = None) -> None:
        self.script_port, self.storyboard_port = script_port, storyboard_port
        self.asset_port, self.rights_port = asset_port, rights_port
        self.store = store or InMemoryMediaVisualAssetSetStore()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def audit_log(self) -> tuple[dict[str, Any], ...]:
        with self.store._lock:
            return tuple(deepcopy(self.store.audit))

    def _now(self, value: Any | None, field: str) -> datetime:
        return _time(value if value is not None else self.clock(), field)

    def _lookup(self, *, port: Any, tenant: str, identity: str, kind: str) -> dict[str, Any]:
        try:
            if hasattr(port, "get_version_by_id"):
                candidate = port.get_version_by_id(org_id=tenant, version_id=identity)
            elif hasattr(port, "get_version"):
                candidate = port.get_version(org_id=tenant, version_id=identity)
            elif hasattr(port, "get"):
                candidate = port.get(org_id=tenant, version_id=identity)
            elif callable(port):
                candidate = port(org_id=tenant, version_id=identity)
            else:
                raise TypeError(f"{kind} port has no get operation")
        except MediaVisualAssetError:
            raise
        except (KeyError, LookupError) as exc:
            raise MediaVisualAssetError(f"{kind.upper()}_NOT_FOUND", f"{kind} version does not exist") from exc
        except Exception as exc:
            provider_code = getattr(exc, "code", None)
            if isinstance(provider_code, str) and provider_code.endswith("_NOT_FOUND"):
                raise MediaVisualAssetError(provider_code, f"{kind} version does not exist") from exc
            raise MediaVisualAssetError("DEPENDENCY_UNAVAILABLE", f"{kind} lookup failed") from exc
        if isinstance(candidate, Mapping) and "version" in candidate:
            candidate = candidate["version"]
        return _safe_json(_mapping_safe(candidate, kind))

    def _script(self, *, tenant: str, value: Any, version_id: Any) -> dict[str, Any]:
        expected = _uuid(version_id, "media_script_version_id", code="SCRIPT_VERSION_NOT_FOUND") if version_id is not None else None
        candidate = value
        if candidate is None:
            if expected is None or self.script_port is None:
                raise MediaVisualAssetError("SCRIPT_VERSION_NOT_FOUND", "an exact MediaScriptVersion is required")
            candidate = self._lookup(port=self.script_port, tenant=tenant, identity=expected, kind="script_version")
        if isinstance(candidate, Mapping) and "version" in candidate:
            candidate = candidate["version"]
        script = _safe_json(_mapping_safe(candidate, "media_script_version"))
        _error_schema(SCRIPT_VERSION_VALIDATOR, script, "SCRIPT_VERSION_INVALID")
        identity = _uuid(script.get("id"), "media_script_version.id", code="SCRIPT_VERSION_NOT_FOUND")
        if expected is not None and identity != expected:
            raise MediaVisualAssetError("SCRIPT_VERSION_NOT_FOUND", "script port returned a different version")
        if _uuid(script.get("org_id"), "media_script_version.org_id") != tenant:
            raise MediaVisualAssetError("TENANT_SCOPE_VIOLATION", "MediaScriptVersion is outside this organization")
        if script.get("status") in {"withdrawn", "superseded"}:
            raise MediaVisualAssetError("SCRIPT_VERSION_NOT_USABLE", "script version cannot be used")
        previous = 0
        for expected_sequence, segment in enumerate(script["segments"], 1):
            if segment["sequence"] != expected_sequence or segment["start_ms"] != previous or segment["end_ms"] <= segment["start_ms"]:
                raise MediaVisualAssetError("SCRIPT_TIMELINE_INVALID", "script timeline is not contiguous")
            previous = segment["end_ms"]
        if previous != int(script["duration_seconds"]) * 1000:
            raise MediaVisualAssetError("SCRIPT_TIMELINE_INVALID", "script timeline does not cover duration")
        return script

    def _storyboard(self, *, tenant: str, value: Any, version_id: Any, script: Mapping[str, Any]) -> dict[str, Any] | None:
        expected = _uuid(version_id, "media_storyboard_version_id", code="STORYBOARD_VERSION_NOT_FOUND") if version_id is not None else None
        candidate = value
        if candidate is None and expected is None:
            return None
        if candidate is None:
            if self.storyboard_port is None:
                raise MediaVisualAssetError("STORYBOARD_VERSION_NOT_FOUND", "exact storyboard version is required")
            candidate = self._lookup(port=self.storyboard_port, tenant=tenant, identity=expected, kind="storyboard_version")
        if isinstance(candidate, Mapping) and "version" in candidate:
            candidate = candidate["version"]
        storyboard = _safe_json(_mapping_safe(candidate, "media_storyboard_version"))
        _error_schema(STORYBOARD_VERSION_VALIDATOR, storyboard, "STORYBOARD_VERSION_INVALID")
        identity = _uuid(storyboard.get("id"), "media_storyboard_version.id", code="STORYBOARD_VERSION_NOT_FOUND")
        if expected is not None and identity != expected:
            raise MediaVisualAssetError("STORYBOARD_VERSION_NOT_FOUND", "storyboard version does not match")
        if _uuid(storyboard.get("org_id"), "media_storyboard_version.org_id") != tenant:
            raise MediaVisualAssetError("TENANT_SCOPE_VIOLATION", "storyboard version is outside this organization")
        if storyboard.get("status") in {"withdrawn", "superseded"}:
            raise MediaVisualAssetError("STORYBOARD_VERSION_NOT_USABLE", "storyboard version cannot be used")
        if storyboard["media_script_version_id"] != script["id"] or storyboard["duration_seconds"] != script["duration_seconds"]:
            raise MediaVisualAssetError("STORYBOARD_LINEAGE_MISMATCH", "storyboard does not belong to selected script")
        return storyboard

    def _asset(self, *, tenant: str, identity: str, supplied: dict[str, dict[str, Any]], script: Mapping[str, Any]) -> dict[str, Any]:
        candidate = supplied.get(identity)
        if candidate is None:
            if self.asset_port is None:
                raise MediaVisualAssetError("ASSET_VERSION_NOT_FOUND", "AssetVersion was not supplied")
            candidate = self._lookup(port=self.asset_port, tenant=tenant, identity=identity, kind="asset_version")
        _error_schema(ASSET_VERSION_VALIDATOR, candidate, "ASSET_VERSION_INVALID")
        if _uuid(candidate.get("id"), "asset_version.id", code="ASSET_VERSION_NOT_FOUND") != identity:
            raise MediaVisualAssetError("ASSET_VERSION_NOT_FOUND", "AssetVersion identity mismatch")
        if _uuid(candidate.get("org_id"), "asset_version.org_id") != tenant:
            raise MediaVisualAssetError("TENANT_SCOPE_VIOLATION", "AssetVersion is outside this organization")
        if candidate.get("status") != "approved":
            raise MediaVisualAssetError("ASSET_VERSION_NOT_APPROVED", "AssetVersion must be approved")
        if candidate["variant_version_id"] != script["variant_version_id"] or candidate["region_profile_version_id"] != script["region_profile_version_id"]:
            raise MediaVisualAssetError("ASSET_LINEAGE_MISMATCH", "AssetVersion does not match Variant or Region")
        if candidate.get("policy_snapshot_id") != script["policy_snapshot_id"]:
            raise MediaVisualAssetError("ASSET_LINEAGE_MISMATCH", "AssetVersion does not match Policy snapshot")
        if candidate.get("storage_object_ref") is not None and not str(candidate["storage_object_ref"]).startswith("private://"):
            raise MediaVisualAssetError("ASSET_VERSION_INVALID", "AssetVersion storage reference must be private")
        if not isinstance(candidate.get("file_hash"), str) or not re.fullmatch(HASH_RE, candidate["file_hash"]):
            raise MediaVisualAssetError("ASSET_VERSION_INVALID", "approved AssetVersion requires a file hash")
        if candidate["media_type"] not in {"image", "video", "thumbnail"}:
            raise MediaVisualAssetError("ASSET_MEDIA_INVALID", "visual asset media type is invalid")
        return candidate

    def _rights(self, *, tenant: str, identity: str, supplied: dict[str, dict[str, Any]], at: datetime,
                script: Mapping[str, Any], media_type: str) -> dict[str, Any]:
        candidate = supplied.get(identity)
        if candidate is None:
            if self.rights_port is None:
                raise MediaVisualAssetError("RIGHTS_VERSION_NOT_FOUND", "RightsRecordVersion was not supplied")
            candidate = self._lookup(port=self.rights_port, tenant=tenant, identity=identity, kind="rights_version")
        _error_schema(RIGHTS_VERSION_VALIDATOR, candidate, "RIGHTS_VERSION_INVALID")
        if _uuid(candidate.get("id"), "rights_version.id", code="RIGHTS_VERSION_NOT_FOUND") != identity:
            raise MediaVisualAssetError("RIGHTS_VERSION_NOT_FOUND", "RightsVersion identity mismatch")
        if _uuid(candidate.get("org_id"), "rights_version.org_id") != tenant:
            raise MediaVisualAssetError("TENANT_SCOPE_VIOLATION", "RightsRecordVersion is outside this organization")
        if candidate.get("status") != "verified":
            raise MediaVisualAssetError("RIGHTS_NOT_VERIFIED", "RightsRecordVersion must be verified")
        if candidate.get("permitted_use") not in {"derivative", "commercial"}:
            raise MediaVisualAssetError("RIGHTS_USE_NOT_ALLOWED", "rights must permit derivative or commercial use")
        if candidate.get("valid_from") is not None and at < _time(candidate["valid_from"], "rights.valid_from"):
            raise MediaVisualAssetError("RIGHTS_NOT_CURRENT", "rights are not yet valid")
        if candidate.get("valid_to") is not None and at >= _time(candidate["valid_to"], "rights.valid_to"):
            raise MediaVisualAssetError("RIGHTS_NOT_CURRENT", "rights have expired")
        market, locale = str(script["market"]).lower(), str(script["locale"]).lower()
        regions = {str(item).lower() for item in candidate.get("permitted_regions", [])}
        locales = {str(item).lower() for item in candidate.get("permitted_locales", [])}
        media = {str(item).lower() for item in candidate.get("permitted_media", [])}
        if regions and market not in regions and "*" not in regions and "all" not in regions:
            raise MediaVisualAssetError("RIGHTS_SCOPE_MISMATCH", "rights do not cover the script market")
        if locales and locale not in locales and locale.split("-", 1)[0] not in locales and "*" not in locales and "all" not in locales:
            raise MediaVisualAssetError("RIGHTS_SCOPE_MISMATCH", "rights do not cover the script locale")
        if media and media_type not in media and "*" not in media and "all" not in media:
            raise MediaVisualAssetError("RIGHTS_SCOPE_MISMATCH", "rights do not cover the visual media type")
        if not candidate.get("source_snapshot_ids") or not isinstance(candidate.get("policy_rule_version"), str) or not candidate["policy_rule_version"].strip():
            raise MediaVisualAssetError("RIGHTS_VERSION_INVALID", "rights source snapshots and policy rule version are required")
        if not isinstance(candidate.get("snapshot_hash"), str) or not re.fullmatch(HASH_RE, candidate["snapshot_hash"]):
            raise MediaVisualAssetError("RIGHTS_VERSION_INVALID", "rights snapshot hash is invalid")
        return candidate

    def _items(self, *, tenant: str, script: Mapping[str, Any], storyboard: Mapping[str, Any] | None,
               items: Any, asset_versions: Any, rights_versions: Any, at: datetime) -> tuple[list[dict[str, Any]], list[str]]:
        if not isinstance(items, Sequence) or isinstance(items, (str, bytes, bytearray)) or not items:
            raise MediaVisualAssetError("VISUAL_ITEM_REQUIRED", "items must be a nonempty array")
        asset_map, rights_map = _collection(asset_versions, "asset_versions"), _collection(rights_versions, "rights_versions")
        duration_ms = int(script["duration_seconds"]) * 1000
        indexed: list[tuple[int, int, Mapping[str, Any]]] = []
        seen_sequences: set[int] = set()
        for index, raw_value in enumerate(items):
            raw = _mapping_safe(raw_value, f"items[{index}]")
            _reject_sensitive(raw)
            sequence = raw.get("sequence")
            if type(sequence) is not int or sequence < 1 or sequence in seen_sequences:
                raise MediaVisualAssetError("VISUAL_ITEM_INVALID", "item sequences must be unique positive integers")
            seen_sequences.add(sequence)
            indexed.append((sequence, index, raw))
        normalized: list[dict[str, Any]] = []
        all_rights: set[str] = set()
        seen_role_assets: set[tuple[str, str]] = set()
        seen_keyframe_times: set[int] = set()
        for sequence, index, raw in sorted(indexed, key=lambda item: item[0]):
            if sequence != len(normalized) + 1:
                raise MediaVisualAssetError("VISUAL_ITEM_INVALID", "item sequences must start at one and be contiguous")
            role = raw.get("role")
            if role not in ROLES:
                raise MediaVisualAssetError("VISUAL_ITEM_INVALID", "item role is invalid")
            asset_id = _uuid(raw.get("asset_version_id"), "asset_version_id", code="ASSET_VERSION_NOT_FOUND")
            role_asset = (role, asset_id)
            if role_asset in seen_role_assets:
                raise MediaVisualAssetError("VISUAL_ITEM_INVALID", "role and AssetVersion cannot repeat")
            seen_role_assets.add(role_asset)
            asset = self._asset(tenant=tenant, identity=asset_id, supplied=asset_map, script=script)
            if asset["media_type"] not in ROLE_MEDIA[role]:
                raise MediaVisualAssetError("ASSET_ROLE_MISMATCH", "AssetVersion media type is incompatible with role")
            timestamp = raw.get("timestamp_ms")
            if role == "keyframe":
                if type(timestamp) is not int or timestamp < 0 or timestamp >= duration_ms:
                    raise MediaVisualAssetError("KEYFRAME_TIME_INVALID", "keyframe timestamp is outside duration")
                if timestamp in seen_keyframe_times:
                    raise MediaVisualAssetError("KEYFRAME_TIME_INVALID", "keyframe timestamps must be unique")
                seen_keyframe_times.add(timestamp)
            elif timestamp is not None:
                raise MediaVisualAssetError("VISUAL_ITEM_INVALID", "cover and thumbnail cannot have timestamps")
            rights_ids = _uuid_list(raw.get("rights_record_version_ids"), "rights_record_version_ids")
            rights_snapshots: list[dict[str, str]] = []
            for rights_id in rights_ids:
                rights = self._rights(tenant=tenant, identity=rights_id, supplied=rights_map, at=at, script=script, media_type=asset["media_type"])
                rights_snapshots.append({"id": rights_id, "snapshot_hash": str(rights["snapshot_hash"]).lower()})
                all_rights.add(rights_id)
            normalized.append({
                "sequence": sequence, "role": role, "asset_version_id": asset_id,
                "media_type": asset["media_type"], "format": str(asset["format"]),
                "storage_object_ref": asset.get("storage_object_ref"),
                "asset_snapshot_hash": str(asset["file_hash"]).lower(),
                "timestamp_ms": timestamp, "alt_text": _text(raw.get("alt_text"), "alt_text", 500, code="ALT_TEXT_REQUIRED"),
                "rights_record_version_ids": rights_ids,
                "rights_snapshots": sorted(rights_snapshots, key=lambda item: item["id"]),
            })
        if not any(item["role"] in {"cover", "thumbnail"} for item in normalized):
            raise MediaVisualAssetError("COVER_REQUIRED", "at least one cover or thumbnail is required")
        return normalized, sorted(all_rights)

    def _build_version(self, *, tenant: str, actor: str, script: Mapping[str, Any], storyboard: Mapping[str, Any] | None,
                       set_id: str, version_no: int, items: list[dict[str, Any]], rights_ids: list[str],
                       reason: str | None, supersedes: str | None, at: datetime, status: str) -> tuple[dict[str, Any], str]:
        material = {
            "org_id": tenant, "media_visual_asset_set_id": set_id, "media_script_version_id": script["id"],
            "media_storyboard_version_id": storyboard["id"] if storyboard else None, "version_no": version_no,
            "duration_seconds": script["duration_seconds"], "region_profile_version_id": script["region_profile_version_id"],
            "policy_snapshot_id": script["policy_snapshot_id"], "template_version": TEMPLATE_VERSION,
            "status": status, "items": items, "item_count": len(items), "rights_snapshot_ids": rights_ids,
            "revision_reason": reason, "supersedes_version_id": supersedes,
            "source_script_snapshot_hash": str(script["snapshot_hash"]).lower(),
            "source_storyboard_snapshot_hash": str(storyboard["snapshot_hash"]).lower() if storyboard else None,
        }
        snapshot_hash = _hash(material)
        version_id = str(uuid5(VERSION_NAMESPACE, f"{set_id}:{version_no}:{snapshot_hash}"))
        stamp = _stamp(at)
        version = {"id": version_id, **material, "snapshot_hash": snapshot_hash, "created_by": actor, "created_at": stamp}
        _error_schema(VISUAL_VERSION_VALIDATOR, version, "INVALID_VISUAL_ASSET_VERSION")
        return version, stamp

    @_audit_failures
    def create_asset_set(
        self, script_version: Any | None = None, *, media_script_version_id: UUID | str | None = None,
        storyboard_version: Any | None = None, media_storyboard_version_id: UUID | str | None = None,
        items: Any, asset_versions: Any | None = None, rights_versions: Any | None = None,
        org_id: UUID | str | None = None, tenant_context: Any | None = None,
        actor_id: UUID | str | None = None, trace_id: str = "media-visual-asset-create",
        idempotency_key: str, created_at: Any | None = None,
    ) -> dict[str, Any]:
        tenant, actor = _context(org_id=org_id, actor_id=actor_id, tenant_context=tenant_context)
        trace, key = _text(trace_id, "trace_id", 256), _text(idempotency_key, "idempotency_key", 200)
        at = self._now(created_at, "created_at")
        script = self._script(tenant=tenant, value=script_version, version_id=media_script_version_id)
        storyboard = self._storyboard(tenant=tenant, value=storyboard_version, version_id=media_storyboard_version_id, script=script)
        normalized_items, rights_ids = self._items(tenant=tenant, script=script, storyboard=storyboard, items=items,
                                                   asset_versions=asset_versions, rights_versions=rights_versions, at=at)
        request_hash = _hash({"operation": "create", "script": script["id"], "storyboard": storyboard["id"] if storyboard else None,
                              "items": normalized_items, "rights_snapshot_ids": rights_ids})
        replay = self.store.replay(org_id=tenant, namespace="create", key=key, request_hash=request_hash)
        if replay is not None:
            return replay
        source_key = storyboard["id"] if storyboard else "-"
        set_id = str(uuid5(SET_NAMESPACE, f"{tenant}:{script['id']}:{source_key}"))
        version, stamp = self._build_version(tenant=tenant, actor=actor, script=script, storyboard=storyboard, set_id=set_id,
                                             version_no=1, items=normalized_items, rights_ids=rights_ids, reason=None,
                                             supersedes=None, at=at, status="draft")
        root = {"id": set_id, "org_id": tenant, "media_script_version_id": script["id"],
                "media_storyboard_version_id": storyboard["id"] if storyboard else None,
                "duration_seconds": script["duration_seconds"], "current_version_id": version["id"], "status": "draft",
                "created_by": actor, "created_at": stamp, "updated_at": stamp}
        _error_schema(VISUAL_SET_VALIDATOR, root, "INVALID_VISUAL_ASSET_SET")
        return self.store.create(root=root, version=version, namespace="create", key=key, request_hash=request_hash,
                                 audit={"operation": "create_asset_set", "org_id": tenant, "media_visual_asset_set_id": set_id,
                                        "version_id": version["id"], "version_no": 1, "media_script_version_id": script["id"],
                                        "policy_snapshot_id": script["policy_snapshot_id"], "request_hash": request_hash,
                                        "snapshot_hash": version["snapshot_hash"], "status": "created", "actor_id": actor,
                                        "trace_id": trace, "duration_ms": 0, "cost_units": 0, "created_at": stamp})

    @_audit_failures
    def revise_asset_set(
        self, *, media_visual_asset_set_id: UUID | str, expected_version_no: int, items: Any,
        asset_versions: Any | None = None, rights_versions: Any | None = None, script_version: Any | None = None,
        storyboard_version: Any | None = None, media_storyboard_version_id: UUID | str | None = None,
        revision_reason: str, org_id: UUID | str | None = None, tenant_context: Any | None = None,
        actor_id: UUID | str | None = None, trace_id: str = "media-visual-asset-revise",
        idempotency_key: str, revised_at: Any | None = None,
    ) -> dict[str, Any]:
        tenant, actor = _context(org_id=org_id, actor_id=actor_id, tenant_context=tenant_context)
        set_id = _uuid(media_visual_asset_set_id, "media_visual_asset_set_id")
        trace, key = _text(trace_id, "trace_id", 256), _text(idempotency_key, "idempotency_key", 200)
        reason = _text(revision_reason, "revision_reason", 1000, code="VISUAL_ASSET_REVISION_INVALID")
        if type(expected_version_no) is not int or expected_version_no < 1:
            raise MediaVisualAssetError("VERSION_CONFLICT", "expected_version_no must be positive")
        root = self.store.get_set(org_id=tenant, set_id=set_id)
        current = self.store.get_version(org_id=tenant, version_id=root["current_version_id"])
        if int(current["version_no"]) != expected_version_no:
            raise MediaVisualAssetError("VERSION_CONFLICT", "visual asset set current version changed")
        script = self._script(tenant=tenant, value=script_version, version_id=current["media_script_version_id"])
        if str(script["snapshot_hash"]).lower() != str(current["source_script_snapshot_hash"]).lower():
            raise MediaVisualAssetError("SCRIPT_SNAPSHOT_MISMATCH", "script snapshot changed")
        storyboard_id = media_storyboard_version_id if media_storyboard_version_id is not None else root.get("media_storyboard_version_id")
        storyboard = self._storyboard(tenant=tenant, value=storyboard_version, version_id=storyboard_id, script=script) if storyboard_id or storyboard_version else None
        if (current.get("source_storyboard_snapshot_hash") or None) != (storyboard.get("snapshot_hash") if storyboard else None):
            raise MediaVisualAssetError("STORYBOARD_SNAPSHOT_MISMATCH", "storyboard snapshot changed")
        at = self._now(revised_at, "revised_at")
        normalized_items, rights_ids = self._items(tenant=tenant, script=script, storyboard=storyboard, items=items,
                                                   asset_versions=asset_versions, rights_versions=rights_versions, at=at)
        request_hash = _hash({"operation": "revise", "set": set_id, "expected_version_no": expected_version_no,
                              "items": normalized_items, "rights_snapshot_ids": rights_ids, "revision_reason": reason})
        replay = self.store.replay(org_id=tenant, namespace="revise", key=key, request_hash=request_hash)
        if replay is not None:
            return replay
        version, stamp = self._build_version(tenant=tenant, actor=actor, script=script, storyboard=storyboard, set_id=set_id,
                                             version_no=expected_version_no + 1, items=normalized_items, rights_ids=rights_ids,
                                             reason=reason, supersedes=current["id"], at=at, status="edited")
        updated_root = {**root, "current_version_id": version["id"], "updated_at": stamp}
        _error_schema(VISUAL_SET_VALIDATOR, updated_root, "INVALID_VISUAL_ASSET_SET")
        return self.store.append(org_id=tenant, set_id=set_id, expected_version_no=expected_version_no, root=updated_root,
                                 version=version, namespace="revise", key=key, request_hash=request_hash,
                                 audit={"operation": "revise_asset_set", "org_id": tenant, "media_visual_asset_set_id": set_id,
                                        "version_id": version["id"], "version_no": expected_version_no + 1,
                                        "media_script_version_id": script["id"], "policy_snapshot_id": script["policy_snapshot_id"],
                                        "request_hash": request_hash, "snapshot_hash": version["snapshot_hash"],
                                        "status": "edited", "actor_id": actor, "trace_id": trace,
                                        "duration_ms": 0, "cost_units": 0, "created_at": stamp})

    def get_asset_set(self, *, media_visual_asset_set_id: UUID | str, org_id: UUID | str | None = None,
                      tenant_context: Any | None = None) -> dict[str, Any]:
        tenant, _ = _context(org_id=org_id, actor_id=None, tenant_context=tenant_context)
        return self.store.get_set(org_id=tenant, set_id=_uuid(media_visual_asset_set_id, "media_visual_asset_set_id"))

    def get_version(self, *, version_id: UUID | str, org_id: UUID | str | None = None,
                    tenant_context: Any | None = None) -> dict[str, Any]:
        tenant, _ = _context(org_id=org_id, actor_id=None, tenant_context=tenant_context)
        return self.store.get_version(org_id=tenant, version_id=_uuid(version_id, "version_id"))

    def list_versions(self, *, media_visual_asset_set_id: UUID | str, org_id: UUID | str | None = None,
                      tenant_context: Any | None = None) -> list[dict[str, Any]]:
        tenant, _ = _context(org_id=org_id, actor_id=None, tenant_context=tenant_context)
        return self.store.list_versions(org_id=tenant, set_id=_uuid(media_visual_asset_set_id, "media_visual_asset_set_id"))


VisualAssetSetService = MediaVisualAssetSetService
MediaVisualAssetSetStore = InMemoryMediaVisualAssetSetStore
MediaVisualAssetService = MediaVisualAssetSetService
MediaVisualAssetService.create_visual_asset_set = MediaVisualAssetSetService.create_asset_set
MediaVisualAssetService.revise_visual_asset_set = MediaVisualAssetSetService.revise_asset_set


__all__ = [
    "AssetVersionPort", "InMemoryMediaVisualAssetSetStore", "MediaVisualAssetError", "MediaVisualAssetService", "MediaVisualAssetSetService",
    "MediaVisualAssetSetStore", "RightsVersionPort", "ScriptVersionPort", "StoryboardVersionPort",
    "TEMPLATE_VERSION", "VisualAssetSetService",
]
