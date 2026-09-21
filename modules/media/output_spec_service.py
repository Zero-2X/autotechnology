"""Deterministic output specifications for the three supported aspect ratios."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from functools import wraps
from math import gcd, isfinite
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
OUTPUT_SPEC_VALIDATOR = Draft202012Validator(
    json.loads((CONTRACTS / "media-output-spec.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
OUTPUT_VERSION_VALIDATOR = Draft202012Validator(
    json.loads((CONTRACTS / "media-output-spec-version.schema.json").read_text(encoding="utf-8")),
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

TEMPLATE_VERSION = "media-output-spec-v1"
SYSTEM_ACTOR = UUID("00000000-0000-4000-8000-000000000001")
SPEC_NAMESPACE = UUID("b57a92fb-91bd-5f85-ae7e-3bd8b15f0c7c")
VERSION_NAMESPACE = UUID("c42a5e57-fd62-5d1c-bd7a-8b12fd8a4a1e")
HASH_RE = r"^[A-Fa-f0-9]{64}$"
RATIO_ORDER = ("9:16", "1:1", "16:9")
RATIO_VALUES = {"9:16": (9, 16), "1:1": (1, 1), "16:9": (16, 9)}
DEFAULT_DIMENSIONS = {"9:16": (1080, 1920), "1:1": (1080, 1080), "16:9": (1920, 1080)}
DEFAULT_PROFILE_KEYS = {"9:16": "vertical", "1:1": "square", "16:9": "landscape"}
CONTAINERS = frozenset({"mp4", "mov", "webm"})
VIDEO_CODECS = frozenset({"h264", "hevc", "av1", "vp9"})
PIXEL_FORMATS = frozenset({"yuv420p", "yuv422p", "yuv444p", "rgba"})
AUDIO_CODECS = frozenset({"aac", "opus", "pcm", "none"})
AUDIO_RATES = frozenset({0, 44100, 48000, 96000})
SENSITIVE_KEYS = frozenset({
    "model", "provider", "credential", "token", "secret", "password", "authorization", "api_key", "raw_output",
})


class VisualAssetSetVersionPort(Protocol):
    def get_version(self, *, org_id: str, version_id: str) -> Mapping[str, Any]: ...


class ScriptVersionPort(Protocol):
    def get_version(self, *, org_id: str, version_id: str) -> Mapping[str, Any]: ...


class StoryboardVersionPort(Protocol):
    def get_version(self, *, org_id: str, version_id: str) -> Mapping[str, Any]: ...


class MediaOutputSpecError(ValueError):
    """Stable, non-sensitive MEDIA-003C application error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _uuid(value: Any, field: str, *, code: str = "INVALID_OUTPUT_SPEC_INPUT") -> str:
    try:
        return _script_uuid(value, field, code=code)
    except MediaScriptError as exc:
        raise MediaOutputSpecError(exc.code, str(exc)) from exc


def _time(value: Any, field: str) -> datetime:
    try:
        return _script_time(value, field)
    except MediaScriptError as exc:
        raise MediaOutputSpecError(exc.code, str(exc)) from exc


def _context(*, org_id: UUID | str | None, actor_id: UUID | str | None, tenant_context: Any) -> tuple[str, str]:
    try:
        return _script_context(org_id=org_id, actor_id=actor_id, tenant_context=tenant_context)
    except MediaScriptError as exc:
        raise MediaOutputSpecError(exc.code, str(exc)) from exc


def _error_schema(validator: Draft202012Validator, value: Mapping[str, Any], code: str) -> None:
    try:
        _script_schema_error(validator, value, code)
    except MediaScriptError as exc:
        raise MediaOutputSpecError(exc.code, str(exc)) from exc


def _mapping_safe(value: Any, field: str) -> dict[str, Any]:
    try:
        return deepcopy(dict(_mapping(value, field)))
    except MediaScriptError as exc:
        raise MediaOutputSpecError("INVALID_OUTPUT_SPEC_INPUT", f"{field} must be an object") from exc


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
    raise MediaOutputSpecError("INVALID_OUTPUT_SPEC_INPUT", "input contains a non-JSON value")


def _text(value: Any, field: str, maximum: int, *, code: str = "INVALID_OUTPUT_SPEC_INPUT") -> str:
    if not isinstance(value, str):
        raise MediaOutputSpecError(code, f"{field} must be text")
    result = value.strip()
    if not result or len(result) > maximum:
        raise MediaOutputSpecError(code, f"{field} has an invalid length")
    if any(ord(char) < 0x20 and char not in "\t\n\r" for char in result):
        raise MediaOutputSpecError(code, f"{field} contains a control character")
    return result


def _reject_sensitive(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_KEYS:
                raise MediaOutputSpecError("SENSITIVE_INPUT_REJECTED", "output specification contains a restricted field")
            _reject_sensitive(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _reject_sensitive(item)


def _profile_values(value: Any) -> list[Any]:
    if isinstance(value, Mapping):
        if "aspect_ratio" in value or "ratio" in value:
            return [value]
        return list(value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    raise MediaOutputSpecError("OUTPUT_PROFILES_REQUIRED", "profiles must be an object or array")


def _audit_failures(method: Any) -> Any:
    @wraps(method)
    def wrapped(self: "MediaOutputSpecService", *args: Any, **kwargs: Any) -> Any:
        try:
            return method(self, *args, **kwargs)
        except MediaOutputSpecError as exc:
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
                safe_spec = _uuid(kwargs.get("media_output_spec_id"), "media_output_spec_id") if kwargs.get("media_output_spec_id") else None
            except Exception:
                safe_spec = None
            with self.store._lock:
                self.store.audit.append({
                    "operation": method.__name__, "org_id": safe_org, "media_output_spec_id": safe_spec,
                    "version_no": kwargs.get("expected_version_no"), "status": "rejected", "error_code": exc.code,
                    "actor_id": safe_actor, "trace_id": kwargs.get("trace_id") if isinstance(kwargs.get("trace_id"), str) else "media-output-spec",
                    "duration_ms": 0, "cost_units": 0,
                })
            raise
    return wrapped


class InMemoryMediaOutputSpecStore:
    def __init__(self) -> None:
        self.specs: dict[str, dict[str, Any]] = {}
        self.versions: dict[str, dict[str, Any]] = {}
        self.versions_by_spec: dict[str, list[str]] = {}
        self.by_source: dict[tuple[str, str], str] = {}
        self.commands: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self._lock = RLock()

    def replay(self, *, org_id: str, namespace: str, key: str, request_hash: str) -> dict[str, Any] | None:
        with self._lock:
            prior = self.commands.get((org_id, namespace, key))
            if prior is None:
                return None
            if prior["request_hash"] != request_hash:
                raise MediaOutputSpecError("IDEMPOTENCY_KEY_REUSED", "command payload differs from prior request")
            return deepcopy(prior["response"])

    def create(self, *, root: Mapping[str, Any], version: Mapping[str, Any], namespace: str, key: str,
               request_hash: str, audit: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            command_key = (str(root["org_id"]), namespace, key)
            prior = self.commands.get(command_key)
            if prior is not None:
                if prior["request_hash"] != request_hash:
                    raise MediaOutputSpecError("IDEMPOTENCY_KEY_REUSED", "command payload differs from prior request")
                return deepcopy(prior["response"])
            source_key = (str(root["org_id"]), str(root["media_visual_asset_set_version_id"]))
            if source_key in self.by_source:
                raise MediaOutputSpecError("OUTPUT_SPEC_ALREADY_EXISTS", "an output specification already exists for this visual version")
            spec_id = str(root["id"])
            self.specs[spec_id] = deepcopy(dict(root))
            self.versions[version["id"]] = deepcopy(dict(version))
            self.versions_by_spec[spec_id] = [version["id"]]
            self.by_source[source_key] = spec_id
            response = {"media_output_spec": deepcopy(dict(root)), "version": deepcopy(dict(version))}
            self.commands[command_key] = {"request_hash": request_hash, "response": deepcopy(response)}
            self.audit.append(deepcopy(dict(audit)))
            return response

    def append(self, *, org_id: str, spec_id: str, expected_version_no: int, root: Mapping[str, Any],
               version: Mapping[str, Any], namespace: str, key: str, request_hash: str,
               audit: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            command_key = (org_id, namespace, key)
            prior = self.commands.get(command_key)
            if prior is not None:
                if prior["request_hash"] != request_hash:
                    raise MediaOutputSpecError("IDEMPOTENCY_KEY_REUSED", "command payload differs from prior request")
                return deepcopy(prior["response"])
            current = self.specs.get(spec_id)
            if current is None or current["org_id"] != org_id:
                raise MediaOutputSpecError("TENANT_SCOPE_VIOLATION", "output specification is outside this organization")
            current_version_id = current.get("current_version_id")
            current_version = self.versions.get(current_version_id)
            if current_version is None or int(current_version["version_no"]) != expected_version_no:
                raise MediaOutputSpecError("VERSION_CONFLICT", "output specification current version changed")
            self.versions[version["id"]] = deepcopy(dict(version))
            self.versions_by_spec.setdefault(spec_id, []).append(version["id"])
            self.specs[spec_id] = deepcopy(dict(root))
            response = {"media_output_spec": deepcopy(dict(root)), "version": deepcopy(dict(version))}
            self.commands[command_key] = {"request_hash": request_hash, "response": deepcopy(response)}
            self.audit.append(deepcopy(dict(audit)))
            return response

    def get_spec(self, *, org_id: str, spec_id: str) -> dict[str, Any]:
        with self._lock:
            value = self.specs.get(spec_id)
            if value is None or value["org_id"] != org_id:
                raise MediaOutputSpecError("TENANT_SCOPE_VIOLATION", "output specification is outside this organization")
            return deepcopy(value)

    def get_version(self, *, org_id: str, version_id: str) -> dict[str, Any]:
        with self._lock:
            value = self.versions.get(version_id)
            if value is None or value["org_id"] != org_id:
                raise MediaOutputSpecError("TENANT_SCOPE_VIOLATION", "output specification version is outside this organization")
            return deepcopy(value)

    def list_versions(self, *, org_id: str, spec_id: str) -> list[dict[str, Any]]:
        self.get_spec(org_id=org_id, spec_id=spec_id)
        with self._lock:
            return [deepcopy(self.versions[item]) for item in self.versions_by_spec.get(spec_id, [])]


class MediaOutputSpecService:
    def __init__(self, *, visual_port: VisualAssetSetVersionPort | Any | None = None,
                 visual_asset_set_port: VisualAssetSetVersionPort | Any | None = None,
                 visual_version_port: VisualAssetSetVersionPort | Any | None = None,
                 script_port: ScriptVersionPort | Any | None = None,
                 storyboard_port: StoryboardVersionPort | Any | None = None,
                 store: InMemoryMediaOutputSpecStore | None = None, clock: Any | None = None) -> None:
        self.visual_port = visual_port or visual_asset_set_port or visual_version_port
        self.script_port = script_port
        self.storyboard_port = storyboard_port
        self.store = store or InMemoryMediaOutputSpecStore()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def audit_log(self) -> tuple[dict[str, Any], ...]:
        with self.store._lock:
            return tuple(deepcopy(self.store.audit))

    def _now(self, value: Any | None, field: str) -> datetime:
        return _time(value if value is not None else self.clock(), field)

    def _lookup(self, *, port: Any, tenant: str, identity: str, kind: str) -> dict[str, Any]:
        if port is None:
            raise MediaOutputSpecError(f"{kind.upper()}_NOT_FOUND", f"{kind} version is required")
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
        except MediaOutputSpecError:
            raise
        except (KeyError, LookupError) as exc:
            raise MediaOutputSpecError(f"{kind.upper()}_NOT_FOUND", f"{kind} version does not exist") from exc
        except Exception as exc:
            provider_code = getattr(exc, "code", None)
            if isinstance(provider_code, str) and provider_code.endswith("_NOT_FOUND"):
                raise MediaOutputSpecError(provider_code, f"{kind} version does not exist") from exc
            raise MediaOutputSpecError("DEPENDENCY_UNAVAILABLE", f"{kind} lookup failed") from exc
        if isinstance(candidate, Mapping) and "version" in candidate:
            candidate = candidate["version"]
        return _safe_json(_mapping_safe(candidate, kind))

    def _visual(self, *, tenant: str, value: Any, version_id: Any) -> dict[str, Any]:
        expected = _uuid(version_id, "media_visual_asset_set_version_id", code="VISUAL_ASSET_VERSION_NOT_FOUND") if version_id is not None else None
        candidate = value
        if candidate is None:
            if expected is None:
                raise MediaOutputSpecError("VISUAL_ASSET_VERSION_NOT_FOUND", "an exact visual AssetSetVersion is required")
            candidate = self._lookup(port=self.visual_port, tenant=tenant, identity=expected, kind="visual_asset_set_version")
        if isinstance(candidate, Mapping) and "version" in candidate:
            candidate = candidate["version"]
        visual = _safe_json(_mapping_safe(candidate, "media_visual_asset_set_version"))
        _error_schema(VISUAL_VERSION_VALIDATOR, visual, "VISUAL_ASSET_VERSION_INVALID")
        identity = _uuid(visual.get("id"), "media_visual_asset_set_version.id", code="VISUAL_ASSET_VERSION_NOT_FOUND")
        if expected is not None and identity != expected:
            raise MediaOutputSpecError("VISUAL_ASSET_VERSION_NOT_FOUND", "visual port returned a different version")
        if _uuid(visual.get("org_id"), "media_visual_asset_set_version.org_id") != tenant:
            raise MediaOutputSpecError("TENANT_SCOPE_VIOLATION", "visual AssetSetVersion is outside this organization")
        if visual.get("status") in {"withdrawn", "superseded"}:
            raise MediaOutputSpecError("VISUAL_ASSET_VERSION_NOT_USABLE", "visual AssetSetVersion cannot be used")
        if not re.fullmatch(HASH_RE, str(visual.get("snapshot_hash", ""))):
            raise MediaOutputSpecError("VISUAL_ASSET_VERSION_INVALID", "visual AssetSetVersion snapshot hash is invalid")
        return visual

    def _script(self, *, tenant: str, value: Any, version_id: Any, visual: Mapping[str, Any]) -> dict[str, Any] | None:
        if value is None and version_id is None:
            return None
        expected = _uuid(version_id, "media_script_version_id", code="SCRIPT_VERSION_NOT_FOUND") if version_id is not None else None
        candidate = value
        if candidate is None:
            candidate = self._lookup(port=self.script_port, tenant=tenant, identity=expected, kind="script_version")
        if isinstance(candidate, Mapping) and "version" in candidate:
            candidate = candidate["version"]
        script = _safe_json(_mapping_safe(candidate, "media_script_version"))
        _error_schema(SCRIPT_VERSION_VALIDATOR, script, "SCRIPT_VERSION_INVALID")
        identity = _uuid(script.get("id"), "media_script_version.id", code="SCRIPT_VERSION_NOT_FOUND")
        if expected is not None and identity != expected:
            raise MediaOutputSpecError("SCRIPT_VERSION_NOT_FOUND", "script port returned a different version")
        if _uuid(script.get("org_id"), "media_script_version.org_id") != tenant:
            raise MediaOutputSpecError("TENANT_SCOPE_VIOLATION", "script version is outside this organization")
        if script.get("status") in {"withdrawn", "superseded"}:
            raise MediaOutputSpecError("SCRIPT_VERSION_NOT_USABLE", "script version cannot be used")
        for field in ("id", "duration_seconds", "region_profile_version_id", "policy_snapshot_id"):
            if script[field] != visual[{"id": "media_script_version_id", "duration_seconds": "duration_seconds", "region_profile_version_id": "region_profile_version_id", "policy_snapshot_id": "policy_snapshot_id"}[field]]:
                raise MediaOutputSpecError("SOURCE_LINEAGE_MISMATCH", "script lineage differs from visual AssetSetVersion")
        if str(script["snapshot_hash"]).lower() != str(visual["source_script_snapshot_hash"]).lower():
            raise MediaOutputSpecError("SOURCE_SNAPSHOT_MISMATCH", "script snapshot differs from visual AssetSetVersion")
        return script

    def _storyboard(self, *, tenant: str, value: Any, version_id: Any, visual: Mapping[str, Any], script: Mapping[str, Any] | None) -> dict[str, Any] | None:
        expected = _uuid(version_id, "media_storyboard_version_id", code="STORYBOARD_VERSION_NOT_FOUND") if version_id is not None else None
        if value is None and expected is None:
            if visual.get("media_storyboard_version_id") is None:
                return None
            expected = _uuid(visual["media_storyboard_version_id"], "media_storyboard_version_id", code="STORYBOARD_VERSION_NOT_FOUND")
        candidate = value
        if candidate is None:
            candidate = self._lookup(port=self.storyboard_port, tenant=tenant, identity=expected, kind="storyboard_version")
        if isinstance(candidate, Mapping) and "version" in candidate:
            candidate = candidate["version"]
        storyboard = _safe_json(_mapping_safe(candidate, "media_storyboard_version"))
        _error_schema(STORYBOARD_VERSION_VALIDATOR, storyboard, "STORYBOARD_VERSION_INVALID")
        identity = _uuid(storyboard.get("id"), "media_storyboard_version.id", code="STORYBOARD_VERSION_NOT_FOUND")
        if expected is not None and identity != expected:
            raise MediaOutputSpecError("STORYBOARD_VERSION_NOT_FOUND", "storyboard version does not match")
        if _uuid(storyboard.get("org_id"), "media_storyboard_version.org_id") != tenant:
            raise MediaOutputSpecError("TENANT_SCOPE_VIOLATION", "storyboard version is outside this organization")
        if storyboard.get("status") in {"withdrawn", "superseded"}:
            raise MediaOutputSpecError("STORYBOARD_VERSION_NOT_USABLE", "storyboard version cannot be used")
        if storyboard["media_script_version_id"] != visual["media_script_version_id"] or storyboard["duration_seconds"] != visual["duration_seconds"]:
            raise MediaOutputSpecError("SOURCE_LINEAGE_MISMATCH", "storyboard does not belong to visual AssetSetVersion")
        if storyboard["region_profile_version_id"] != visual["region_profile_version_id"] or storyboard["policy_snapshot_id"] != visual["policy_snapshot_id"]:
            raise MediaOutputSpecError("SOURCE_LINEAGE_MISMATCH", "storyboard region or policy differs from visual AssetSetVersion")
        if visual.get("media_storyboard_version_id") != storyboard["id"]:
            raise MediaOutputSpecError("SOURCE_LINEAGE_MISMATCH", "storyboard id differs from visual AssetSetVersion")
        if script is not None and storyboard["media_script_version_id"] != script["id"]:
            raise MediaOutputSpecError("SOURCE_LINEAGE_MISMATCH", "storyboard script differs from selected script")
        if str(storyboard["snapshot_hash"]).lower() != str(visual.get("source_storyboard_snapshot_hash")).lower():
            raise MediaOutputSpecError("SOURCE_SNAPSHOT_MISMATCH", "storyboard snapshot differs from visual AssetSetVersion")
        return storyboard

    def _profile(self, raw_value: Any, index: int) -> dict[str, Any]:
        raw = _safe_json(_mapping_safe(raw_value, f"profiles[{index}]"))
        _reject_sensitive(raw)
        allowed = {"sequence", "profile_key", "key", "aspect_ratio", "ratio", "width", "height", "frame_rate", "fps",
                   "container_format", "container", "video_codec", "codec", "pixel_format", "audio_codec",
                   "audio_sample_rate_hz", "audio_sample_rate", "audio_channels", "subtitle_track_ids", "subtitle_ids", "bitrate_kbps"}
        if set(raw) - allowed:
            raise MediaOutputSpecError("OUTPUT_PROFILE_INVALID", "profile contains an unknown field")
        ratio = raw.get("aspect_ratio", raw.get("ratio"))
        if not isinstance(ratio, str) or ratio not in RATIO_VALUES:
            raise MediaOutputSpecError("OUTPUT_RATIO_INVALID", "aspect_ratio must be 9:16, 1:1 or 16:9")
        profile_key = raw.get("profile_key", raw.get("key")) or DEFAULT_PROFILE_KEYS[ratio]
        if not isinstance(profile_key, str) or not re.fullmatch(r"[a-z][a-z0-9._-]{0,63}", profile_key.strip()):
            raise MediaOutputSpecError("OUTPUT_PROFILE_INVALID", "profile_key is invalid")
        profile_key = profile_key.strip()
        default_width, default_height = DEFAULT_DIMENSIONS[ratio]
        width, height = raw.get("width", default_width), raw.get("height", default_height)
        if type(width) is not int or type(height) is not int or width < 2 or height < 2 or width > 7680 or height > 7680 or width % 2 or height % 2:
            raise MediaOutputSpecError("OUTPUT_DIMENSIONS_INVALID", "width and height must be positive even values no greater than 7680")
        ratio_width, ratio_height = RATIO_VALUES[ratio]
        divisor = gcd(width, height)
        if width // divisor != ratio_width or height // divisor != ratio_height:
            raise MediaOutputSpecError("OUTPUT_DIMENSIONS_INVALID", "width and height do not match aspect_ratio")
        frame_rate = raw.get("frame_rate", raw.get("fps", 30))
        if isinstance(frame_rate, bool) or not isinstance(frame_rate, (int, float)) or not isfinite(float(frame_rate)) or frame_rate < 1 or frame_rate > 120:
            raise MediaOutputSpecError("OUTPUT_FRAME_RATE_INVALID", "frame_rate must be finite and between 1 and 120")
        if round(float(frame_rate), 3) != float(frame_rate):
            raise MediaOutputSpecError("OUTPUT_FRAME_RATE_INVALID", "frame_rate has at most three decimal places")
        container = str(raw.get("container_format", raw.get("container", "mp4"))).lower()
        video_codec = str(raw.get("video_codec", raw.get("codec", "h264"))).lower()
        pixel_format = str(raw.get("pixel_format", "yuv420p")).lower()
        audio_codec = str(raw.get("audio_codec", "aac")).lower()
        if container not in CONTAINERS or video_codec not in VIDEO_CODECS or pixel_format not in PIXEL_FORMATS or audio_codec not in AUDIO_CODECS:
            raise MediaOutputSpecError("OUTPUT_FORMAT_INVALID", "output format is outside the allowed profile set")
        sample_rate = raw.get("audio_sample_rate_hz", raw.get("audio_sample_rate", 48000 if audio_codec != "none" else 0))
        channels = raw.get("audio_channels", 2 if audio_codec != "none" else 0)
        if type(sample_rate) is not int or sample_rate not in AUDIO_RATES or type(channels) is not int or channels < 0 or channels > 8:
            raise MediaOutputSpecError("OUTPUT_AUDIO_INVALID", "audio sample rate or channels is invalid")
        if audio_codec == "none" and (sample_rate != 0 or channels != 0):
            raise MediaOutputSpecError("OUTPUT_AUDIO_INVALID", "audio none requires zero sample rate and channels")
        if audio_codec != "none" and (sample_rate == 0 or channels == 0):
            raise MediaOutputSpecError("OUTPUT_AUDIO_INVALID", "audio codec requires sample rate and channels")
        track_values = raw.get("subtitle_track_ids", raw.get("subtitle_ids", []))
        if track_values is None:
            track_values = []
        if isinstance(track_values, (str, bytes, bytearray, Mapping)):
            raise MediaOutputSpecError("SUBTITLE_REFERENCE_INVALID", "subtitle_track_ids must be an array")
        try:
            track_ids = sorted({_uuid(item, "subtitle_track_id", code="SUBTITLE_REFERENCE_INVALID") for item in track_values})
        except TypeError as exc:
            raise MediaOutputSpecError("SUBTITLE_REFERENCE_INVALID", "subtitle_track_ids must be an array") from exc
        bitrate = raw.get("bitrate_kbps")
        if bitrate is not None and (type(bitrate) is not int or bitrate < 1 or bitrate > 1000000):
            raise MediaOutputSpecError("OUTPUT_BITRATE_INVALID", "bitrate_kbps is invalid")
        result: dict[str, Any] = {
            "sequence": 0, "profile_key": profile_key, "aspect_ratio": ratio, "width": width, "height": height,
            "frame_rate": float(frame_rate) if not float(frame_rate).is_integer() else int(frame_rate),
            "container_format": container, "video_codec": video_codec, "pixel_format": pixel_format,
            "audio_codec": audio_codec, "audio_sample_rate_hz": sample_rate, "audio_channels": channels,
            "subtitle_track_ids": track_ids,
        }
        if bitrate is not None:
            result["bitrate_kbps"] = bitrate
        return result

    def _profiles(self, value: Any, *, require_all_ratios: bool | None = None) -> tuple[list[dict[str, Any]], bool]:
        if require_all_ratios is not None and type(require_all_ratios) is not bool:
            raise MediaOutputSpecError("OUTPUT_SPEC_INPUT_INVALID", "require_all_ratios must be boolean")
        raw_values = _profile_values(value)
        if not raw_values or len(raw_values) > 3:
            raise MediaOutputSpecError("OUTPUT_PROFILES_REQUIRED", "profiles must contain between one and three items")
        normalized = [self._profile(item, index) for index, item in enumerate(raw_values)]
        if len({item["profile_key"] for item in normalized}) != len(normalized):
            raise MediaOutputSpecError("OUTPUT_PROFILE_DUPLICATE", "profile_key must be unique")
        if len({item["aspect_ratio"] for item in normalized}) != len(normalized):
            raise MediaOutputSpecError("OUTPUT_RATIO_DUPLICATE", "aspect_ratio must be unique")
        all_required = bool(require_all_ratios) if require_all_ratios is not None else False
        if all_required and set(item["aspect_ratio"] for item in normalized) != set(RATIO_ORDER):
            raise MediaOutputSpecError("OUTPUT_RATIO_SET_INCOMPLETE", "all three aspect ratios are required")
        normalized.sort(key=lambda item: (RATIO_ORDER.index(item["aspect_ratio"]), item["profile_key"]))
        for sequence, item in enumerate(normalized, 1):
            item["sequence"] = sequence
        return normalized, all_required

    def _build_version(self, *, tenant: str, actor: str, visual: Mapping[str, Any], script: Mapping[str, Any] | None,
                       storyboard: Mapping[str, Any] | None, spec_id: str, version_no: int,
                       profiles: list[dict[str, Any]], require_all_ratios: bool, reason: str | None,
                       supersedes: str | None, at: datetime, status: str) -> tuple[dict[str, Any], str]:
        material = {
            "org_id": tenant, "media_output_spec_id": spec_id, "media_visual_asset_set_version_id": visual["id"],
            "media_script_version_id": visual["media_script_version_id"],
            "media_storyboard_version_id": visual.get("media_storyboard_version_id"),
            "version_no": version_no, "duration_seconds": visual["duration_seconds"],
            "region_profile_version_id": visual["region_profile_version_id"], "policy_snapshot_id": visual["policy_snapshot_id"],
            "template_version": TEMPLATE_VERSION, "status": status, "profiles": profiles, "profile_count": len(profiles),
            "require_all_ratios": require_all_ratios, "revision_reason": reason, "supersedes_version_id": supersedes,
            "source_visual_snapshot_hash": str(visual["snapshot_hash"]).lower(),
            "source_script_snapshot_hash": str(visual["source_script_snapshot_hash"]).lower(),
            "source_storyboard_snapshot_hash": str(visual.get("source_storyboard_snapshot_hash")).lower() if visual.get("source_storyboard_snapshot_hash") else None,
        }
        snapshot_hash = _hash(material)
        version_id = str(uuid5(VERSION_NAMESPACE, f"{spec_id}:{version_no}:{snapshot_hash}"))
        stamp = _stamp(at)
        version = {"id": version_id, **material, "snapshot_hash": snapshot_hash, "created_by": actor, "created_at": stamp}
        _error_schema(OUTPUT_VERSION_VALIDATOR, version, "INVALID_OUTPUT_SPEC_VERSION")
        return version, stamp

    @_audit_failures
    def create_output_spec(
        self, visual_asset_set_version: Any | None = None, *,
        media_visual_asset_set_version_id: UUID | str | None = None,
        profiles: Any | None = None, output_profiles: Any | None = None,
        script_version: Any | None = None, media_script_version_id: UUID | str | None = None,
        storyboard_version: Any | None = None, media_storyboard_version_id: UUID | str | None = None,
        require_all_ratios: bool = False, org_id: UUID | str | None = None,
        tenant_context: Any | None = None, actor_id: UUID | str | None = None,
        trace_id: str = "media-output-spec-create", idempotency_key: str,
        created_at: Any | None = None,
    ) -> dict[str, Any]:
        tenant, actor = _context(org_id=org_id, actor_id=actor_id, tenant_context=tenant_context)
        trace, key = _text(trace_id, "trace_id", 256), _text(idempotency_key, "idempotency_key", 200)
        if type(require_all_ratios) is not bool:
            raise MediaOutputSpecError("OUTPUT_SPEC_INPUT_INVALID", "require_all_ratios must be boolean")
        visual = self._visual(tenant=tenant, value=visual_asset_set_version, version_id=media_visual_asset_set_version_id)
        script = self._script(tenant=tenant, value=script_version, version_id=media_script_version_id, visual=visual)
        storyboard = self._storyboard(tenant=tenant, value=storyboard_version, version_id=media_storyboard_version_id, visual=visual, script=script)
        profile_input = profiles if profiles is not None else output_profiles
        normalized, all_required = self._profiles(profile_input, require_all_ratios=require_all_ratios)
        at = self._now(created_at, "created_at")
        request_hash = _hash({"operation": "create", "visual": visual["id"], "visual_snapshot_hash": visual["snapshot_hash"],
                              "profiles": normalized, "require_all_ratios": all_required})
        replay = self.store.replay(org_id=tenant, namespace="create", key=key, request_hash=request_hash)
        if replay is not None:
            return replay
        spec_id = str(uuid5(SPEC_NAMESPACE, f"{tenant}:{visual['id']}"))
        version, stamp = self._build_version(tenant=tenant, actor=actor, visual=visual, script=script, storyboard=storyboard,
                                             spec_id=spec_id, version_no=1, profiles=normalized, require_all_ratios=all_required,
                                             reason=None, supersedes=None, at=at, status="draft")
        root = {"id": spec_id, "org_id": tenant, "media_visual_asset_set_version_id": visual["id"],
                "media_script_version_id": visual["media_script_version_id"],
                "media_storyboard_version_id": visual.get("media_storyboard_version_id"),
                "duration_seconds": visual["duration_seconds"], "region_profile_version_id": visual["region_profile_version_id"],
                "policy_snapshot_id": visual["policy_snapshot_id"], "current_version_id": version["id"], "status": "draft",
                "created_by": actor, "created_at": stamp, "updated_at": stamp}
        _error_schema(OUTPUT_SPEC_VALIDATOR, root, "INVALID_OUTPUT_SPEC")
        return self.store.create(root=root, version=version, namespace="create", key=key, request_hash=request_hash,
                                 audit={"operation": "create_output_spec", "org_id": tenant, "media_output_spec_id": spec_id,
                                        "version_id": version["id"], "version_no": 1, "media_visual_asset_set_version_id": visual["id"],
                                        "policy_snapshot_id": visual["policy_snapshot_id"], "request_hash": request_hash,
                                        "snapshot_hash": version["snapshot_hash"], "status": "created", "actor_id": actor,
                                        "trace_id": trace, "duration_ms": 0, "cost_units": 0, "created_at": stamp})

    @_audit_failures
    def revise_output_spec(
        self, *, media_output_spec_id: UUID | str, expected_version_no: int, profiles: Any | None = None,
        output_profiles: Any | None = None, visual_asset_set_version: Any | None = None,
        media_visual_asset_set_version_id: UUID | str | None = None, script_version: Any | None = None,
        media_script_version_id: UUID | str | None = None, storyboard_version: Any | None = None,
        media_storyboard_version_id: UUID | str | None = None, require_all_ratios: bool | None = None,
        revision_reason: str, org_id: UUID | str | None = None, tenant_context: Any | None = None,
        actor_id: UUID | str | None = None, trace_id: str = "media-output-spec-revise",
        idempotency_key: str, revised_at: Any | None = None,
    ) -> dict[str, Any]:
        tenant, actor = _context(org_id=org_id, actor_id=actor_id, tenant_context=tenant_context)
        spec_id = _uuid(media_output_spec_id, "media_output_spec_id")
        trace, key = _text(trace_id, "trace_id", 256), _text(idempotency_key, "idempotency_key", 200)
        reason = _text(revision_reason, "revision_reason", 1000, code="OUTPUT_SPEC_REVISION_INVALID")
        if type(expected_version_no) is not int or expected_version_no < 1:
            raise MediaOutputSpecError("VERSION_CONFLICT", "expected_version_no must be positive")
        root = self.store.get_spec(org_id=tenant, spec_id=spec_id)
        current = self.store.get_version(org_id=tenant, version_id=root["current_version_id"])
        base = next((version for version in self.store.list_versions(org_id=tenant, spec_id=spec_id)
                     if version["version_no"] == expected_version_no), None)
        if base is None:
            raise MediaOutputSpecError("VERSION_CONFLICT", "expected output specification version does not exist")
        source_id = media_visual_asset_set_version_id or current["media_visual_asset_set_version_id"]
        visual = self._visual(tenant=tenant, value=visual_asset_set_version, version_id=source_id)
        if visual["id"] != current["media_visual_asset_set_version_id"] or str(visual["snapshot_hash"]).lower() != str(current["source_visual_snapshot_hash"]).lower():
            raise MediaOutputSpecError("SOURCE_SNAPSHOT_MISMATCH", "visual AssetSetVersion snapshot changed")
        script = self._script(tenant=tenant, value=script_version, version_id=media_script_version_id, visual=visual)
        storyboard_id = media_storyboard_version_id if media_storyboard_version_id is not None else visual.get("media_storyboard_version_id")
        storyboard = self._storyboard(tenant=tenant, value=storyboard_version, version_id=storyboard_id, visual=visual, script=script)
        expected_all = base.get("require_all_ratios") if require_all_ratios is None else require_all_ratios
        if type(expected_all) is not bool:
            raise MediaOutputSpecError("OUTPUT_SPEC_INPUT_INVALID", "require_all_ratios must be boolean")
        profile_input = profiles if profiles is not None else output_profiles
        normalized, all_required = self._profiles(profile_input, require_all_ratios=expected_all)
        at = self._now(revised_at, "revised_at")
        request_hash = _hash({"operation": "revise", "set": spec_id, "expected_version_no": expected_version_no,
                              "profiles": normalized, "require_all_ratios": all_required, "revision_reason": reason})
        replay = self.store.replay(org_id=tenant, namespace="revise", key=key, request_hash=request_hash)
        if replay is not None:
            return replay
        if int(current["version_no"]) != expected_version_no:
            raise MediaOutputSpecError("VERSION_CONFLICT", "output specification current version changed")
        version, stamp = self._build_version(tenant=tenant, actor=actor, visual=visual, script=script, storyboard=storyboard,
                                             spec_id=spec_id, version_no=expected_version_no + 1, profiles=normalized,
                                             require_all_ratios=all_required, reason=reason, supersedes=current["id"], at=at, status="edited")
        updated_root = {**root, "current_version_id": version["id"], "updated_at": stamp}
        _error_schema(OUTPUT_SPEC_VALIDATOR, updated_root, "INVALID_OUTPUT_SPEC")
        return self.store.append(org_id=tenant, spec_id=spec_id, expected_version_no=expected_version_no, root=updated_root,
                                 version=version, namespace="revise", key=key, request_hash=request_hash,
                                 audit={"operation": "revise_output_spec", "org_id": tenant, "media_output_spec_id": spec_id,
                                        "version_id": version["id"], "version_no": expected_version_no + 1,
                                        "media_visual_asset_set_version_id": visual["id"], "policy_snapshot_id": visual["policy_snapshot_id"],
                                        "request_hash": request_hash, "snapshot_hash": version["snapshot_hash"], "status": "edited",
                                        "actor_id": actor, "trace_id": trace, "duration_ms": 0, "cost_units": 0, "created_at": stamp})

    def validate_profiles(self, profiles: Any, *, require_all_ratios: bool = False) -> list[dict[str, Any]]:
        return self._profiles(profiles, require_all_ratios=require_all_ratios)[0]

    def get_output_spec(self, *, media_output_spec_id: UUID | str, org_id: UUID | str | None = None,
                        tenant_context: Any | None = None) -> dict[str, Any]:
        tenant, _ = _context(org_id=org_id, actor_id=None, tenant_context=tenant_context)
        return self.store.get_spec(org_id=tenant, spec_id=_uuid(media_output_spec_id, "media_output_spec_id"))

    def get_version(self, *, version_id: UUID | str, org_id: UUID | str | None = None,
                    tenant_context: Any | None = None) -> dict[str, Any]:
        tenant, _ = _context(org_id=org_id, actor_id=None, tenant_context=tenant_context)
        return self.store.get_version(org_id=tenant, version_id=_uuid(version_id, "version_id"))

    def list_versions(self, *, media_output_spec_id: UUID | str, org_id: UUID | str | None = None,
                      tenant_context: Any | None = None) -> list[dict[str, Any]]:
        tenant, _ = _context(org_id=org_id, actor_id=None, tenant_context=tenant_context)
        return self.store.list_versions(org_id=tenant, spec_id=_uuid(media_output_spec_id, "media_output_spec_id"))


OutputSpecService = MediaOutputSpecService
MediaOutputSpecificationService = MediaOutputSpecService
MediaOutputSpecStore = InMemoryMediaOutputSpecStore
MediaOutputSpecService.create_spec = MediaOutputSpecService.create_output_spec
MediaOutputSpecService.revise_spec = MediaOutputSpecService.revise_output_spec
MediaOutputSpecificationService.create_output_spec_version = MediaOutputSpecService.create_output_spec


__all__ = [
    "InMemoryMediaOutputSpecStore", "MediaOutputSpecError", "MediaOutputSpecService", "MediaOutputSpecStore",
    "MediaOutputSpecificationService", "OutputSpecService", "ScriptVersionPort", "StoryboardVersionPort",
    "VisualAssetSetVersionPort", "TEMPLATE_VERSION",
]
