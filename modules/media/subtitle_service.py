"""Deterministic subtitle tracks and immutable accessibility-aware versions."""

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
SUBTITLE_VALIDATOR = Draft202012Validator(
    json.loads((CONTRACTS / "media-subtitle.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
SUBTITLE_VERSION_VALIDATOR = Draft202012Validator(
    json.loads((CONTRACTS / "media-subtitle-version.schema.json").read_text(encoding="utf-8")),
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

TEMPLATE_VERSION = "media-subtitle-v1"
SYSTEM_ACTOR = UUID("00000000-0000-4000-8000-000000000001")
SUBTITLE_NAMESPACE = UUID("f2bd9e8d-fc6e-54b9-a3bc-9c8e3cfd8fd9")
VERSION_NAMESPACE = UUID("fddc16de-2af8-5c80-9e80-7d0d8c60c9d0")
HASH_RE = r"^[A-Fa-f0-9]{64}$"
RTL_LANGUAGES = frozenset({"ar", "fa", "he", "ur", "ps", "sd", "yi"})
SENSITIVE_KEYS = frozenset({"model", "provider", "credential", "token", "secret", "password", "authorization", "api_key", "raw_output"})


def _uuid(value: Any, field: str, *, code: str = "INVALID_SUBTITLE_INPUT") -> str:
    try:
        return _script_uuid(value, field, code=code)
    except MediaScriptError as exc:
        raise MediaSubtitleError(exc.code, str(exc)) from exc


def _time(value: Any, field: str) -> datetime:
    try:
        return _script_time(value, field)
    except MediaScriptError as exc:
        raise MediaSubtitleError(exc.code, str(exc)) from exc


def _context(*, org_id: UUID | str | None, actor_id: UUID | str | None, tenant_context: Any) -> tuple[str, str]:
    try:
        return _script_context(org_id=org_id, actor_id=actor_id, tenant_context=tenant_context)
    except MediaScriptError as exc:
        raise MediaSubtitleError(exc.code, str(exc)) from exc


class ScriptVersionPort(Protocol):
    def get_version(self, *, org_id: str, version_id: str) -> Mapping[str, Any]: ...


class StoryboardVersionPort(Protocol):
    def get_version(self, *, org_id: str, version_id: str) -> Mapping[str, Any]: ...


class MediaSubtitleError(ValueError):
    """Stable, non-sensitive MEDIA-003A application error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _error_schema(validator: Draft202012Validator, value: Mapping[str, Any], code: str) -> None:
    try:
        _script_schema_error(validator, value, code)
    except MediaScriptError as exc:
        raise MediaSubtitleError(exc.code, str(exc)) from exc


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
    raise MediaSubtitleError("INVALID_SUBTITLE_INPUT", "input contains a non-JSON value")


def _text(value: Any, field: str, maximum: int, *, code: str = "INVALID_SUBTITLE_INPUT") -> str:
    if not isinstance(value, str):
        raise MediaSubtitleError(code, f"{field} must be text")
    result = value.strip()
    if not result or len(result) > maximum:
        raise MediaSubtitleError(code, f"{field} has an invalid length")
    if any(ord(char) < 0x20 and char not in "\t\n\r" for char in result):
        raise MediaSubtitleError(code, f"{field} contains a control character")
    return result


def _canonical_locale(value: Any, field: str = "locale") -> str:
    raw = _text(value, field, 32, code="LOCALE_INVALID")
    if not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{2,8})*", raw):
        raise MediaSubtitleError("LOCALE_INVALID", f"{field} is not a BCP-47-like locale")
    parts = raw.split("-")
    normalized = [parts[0].lower()]
    for part in parts[1:]:
        normalized.append(part.upper() if len(part) in (2, 3) and part.isalpha() else part.lower())
    return "-".join(normalized)


def _mapping_safe(value: Any, field: str) -> dict[str, Any]:
    try:
        return deepcopy(dict(_mapping(value, field)))
    except MediaScriptError as exc:
        raise MediaSubtitleError("INVALID_SUBTITLE_INPUT", f"{field} must be an object") from exc


def _reject_sensitive_keys(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_KEYS:
                raise MediaSubtitleError("SENSITIVE_INPUT_REJECTED", "subtitle input contains a restricted field")
            _reject_sensitive_keys(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _reject_sensitive_keys(item)


def _collection(value: Any, field: str) -> dict[str, dict[str, Any]]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        items = [value] if "id" in value else list(value.values())
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items = list(value)
    else:
        raise MediaSubtitleError("REFERENCE_INVALID", f"{field} must be an object or array")
    result: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(items):
        candidate = _safe_json(_mapping_safe(item, f"{field}[{index}]"))
        identity = _uuid(candidate.get("id"), f"{field}[{index}].id", code="REFERENCE_INVALID")
        if identity in result:
            raise MediaSubtitleError("REFERENCE_INVALID", f"{field} contains a duplicate id")
        result[identity] = candidate
    return result


def _audit_failures(method: Any) -> Any:
    @wraps(method)
    def wrapped(self: "MediaSubtitleService", *args: Any, **kwargs: Any) -> Any:
        try:
            return method(self, *args, **kwargs)
        except MediaSubtitleError as exc:
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
                safe_subtitle = _uuid(kwargs.get("media_subtitle_id"), "media_subtitle_id") if kwargs.get("media_subtitle_id") else None
            except Exception:
                safe_subtitle = None
            with self.store._lock:
                self.store.audit.append({
                    "operation": method.__name__, "org_id": safe_org, "media_subtitle_id": safe_subtitle,
                    "version_no": kwargs.get("expected_version_no"), "status": "rejected",
                    "error_code": exc.code, "actor_id": safe_actor,
                    "trace_id": kwargs.get("trace_id") if isinstance(kwargs.get("trace_id"), str) else "media-subtitle",
                    "duration_ms": 0, "cost_units": 0,
                })
            raise
    return wrapped


class InMemoryMediaSubtitleStore:
    def __init__(self) -> None:
        self.subtitles: dict[str, dict[str, Any]] = {}
        self.versions: dict[str, dict[str, Any]] = {}
        self.versions_by_subtitle: dict[str, list[str]] = {}
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
                raise MediaSubtitleError("IDEMPOTENCY_KEY_REUSED", "command payload differs from prior request")
            return deepcopy(row["response"])

    def create(self, *, root: Mapping[str, Any], version: Mapping[str, Any], namespace: str,
               key: str, request_hash: str, audit: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            command_key = (str(root["org_id"]), namespace, key)
            prior = self.commands.get(command_key)
            if prior is not None:
                if prior["request_hash"] != request_hash:
                    raise MediaSubtitleError("IDEMPOTENCY_KEY_REUSED", "command payload differs from prior request")
                return deepcopy(prior["response"])
            natural = (
                str(root["org_id"]), str(root["media_script_version_id"]),
                str(root.get("media_storyboard_version_id") or "-"),
            )
            if natural in self.by_source:
                raise MediaSubtitleError("SUBTITLE_ALREADY_EXISTS", "subtitle root already exists for this source")
            root_copy, version_copy = deepcopy(dict(root)), deepcopy(dict(version))
            self.subtitles[root_copy["id"]] = root_copy
            self.versions[version_copy["id"]] = version_copy
            self.versions_by_subtitle[root_copy["id"]] = [version_copy["id"]]
            self.by_source[natural] = root_copy["id"]
            response = {"media_subtitle": root_copy, "version": version_copy}
            self.commands[command_key] = {"request_hash": request_hash, "response": deepcopy(response)}
            self.audit.append(deepcopy(dict(audit)))
            return deepcopy(response)

    def append(self, *, org_id: str, subtitle_id: str, expected_version_no: int,
               root: Mapping[str, Any], version: Mapping[str, Any], namespace: str,
               key: str, request_hash: str, audit: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            command_key = (org_id, namespace, key)
            prior = self.commands.get(command_key)
            if prior is not None:
                if prior["request_hash"] != request_hash:
                    raise MediaSubtitleError("IDEMPOTENCY_KEY_REUSED", "command payload differs from prior request")
                return deepcopy(prior["response"])
            current_root = self.subtitles.get(subtitle_id)
            if current_root is None or current_root["org_id"] != org_id:
                raise MediaSubtitleError("TENANT_SCOPE_VIOLATION", "subtitle is outside this organization")
            current = self.versions[current_root["current_version_id"]]
            if int(current["version_no"]) != expected_version_no:
                raise MediaSubtitleError("VERSION_CONFLICT", "subtitle current version changed")
            version_copy = deepcopy(dict(version))
            if version_copy["id"] in self.versions:
                raise MediaSubtitleError("SUBTITLE_VERSION_IMMUTABLE", "subtitle version already exists")
            root_copy = deepcopy(dict(root))
            self.versions[version_copy["id"]] = version_copy
            self.versions_by_subtitle[subtitle_id].append(version_copy["id"])
            self.subtitles[subtitle_id] = root_copy
            response = {"media_subtitle": root_copy, "version": version_copy}
            self.commands[command_key] = {"request_hash": request_hash, "response": deepcopy(response)}
            self.audit.append(deepcopy(dict(audit)))
            return deepcopy(response)

    def get_subtitle(self, *, org_id: str, subtitle_id: str) -> dict[str, Any]:
        with self._lock:
            value = self.subtitles.get(subtitle_id)
            if value is None or value["org_id"] != org_id:
                raise MediaSubtitleError("TENANT_SCOPE_VIOLATION", "subtitle is outside this organization")
            return deepcopy(value)

    def get_version(self, *, org_id: str, version_id: str) -> dict[str, Any]:
        with self._lock:
            value = self.versions.get(version_id)
            if value is None or value["org_id"] != org_id:
                raise MediaSubtitleError("TENANT_SCOPE_VIOLATION", "subtitle version is outside this organization")
            return deepcopy(value)

    def list_versions(self, *, org_id: str, subtitle_id: str) -> list[dict[str, Any]]:
        root = self.get_subtitle(org_id=org_id, subtitle_id=subtitle_id)
        with self._lock:
            return [deepcopy(self.versions[item]) for item in self.versions_by_subtitle[root["id"]]]


class MediaSubtitleService:
    def __init__(self, *, script_port: ScriptVersionPort | Any | None = None,
                 storyboard_port: StoryboardVersionPort | Any | None = None,
                 store: InMemoryMediaSubtitleStore | None = None, clock: Any | None = None) -> None:
        self.script_port = script_port
        self.storyboard_port = storyboard_port
        self.store = store or InMemoryMediaSubtitleStore()
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
        except MediaSubtitleError:
            raise
        except (KeyError, LookupError) as exc:
            raise MediaSubtitleError(f"{kind.upper()}_NOT_FOUND", f"{kind} version does not exist") from exc
        except Exception as exc:
            provider_code = getattr(exc, "code", None)
            if isinstance(provider_code, str) and provider_code.endswith("_NOT_FOUND"):
                raise MediaSubtitleError(provider_code, f"{kind} version does not exist") from exc
            raise MediaSubtitleError("DEPENDENCY_UNAVAILABLE", f"{kind} lookup failed") from exc
        if isinstance(candidate, Mapping) and "version" in candidate:
            candidate = candidate["version"]
        return _safe_json(_mapping_safe(candidate, kind))

    def _script(self, *, tenant: str, value: Any, version_id: Any) -> dict[str, Any]:
        expected = _uuid(version_id, "media_script_version_id", code="SCRIPT_VERSION_NOT_FOUND") if version_id is not None else None
        candidate = value
        if candidate is None:
            if expected is None or self.script_port is None:
                raise MediaSubtitleError("SCRIPT_VERSION_NOT_FOUND", "an exact MediaScriptVersion is required")
            candidate = self._lookup(port=self.script_port, tenant=tenant, identity=expected, kind="script_version")
        if isinstance(candidate, Mapping) and "version" in candidate:
            candidate = candidate["version"]
        script = _safe_json(_mapping_safe(candidate, "media_script_version"))
        _error_schema(SCRIPT_VERSION_VALIDATOR, script, "SCRIPT_VERSION_INVALID")
        identity = _uuid(script.get("id"), "media_script_version.id", code="SCRIPT_VERSION_NOT_FOUND")
        if expected is not None and identity != expected:
            raise MediaSubtitleError("SCRIPT_VERSION_NOT_FOUND", "script port returned a different version")
        if _uuid(script.get("org_id"), "media_script_version.org_id") != tenant:
            raise MediaSubtitleError("TENANT_SCOPE_VIOLATION", "MediaScriptVersion is outside this organization")
        if script.get("status") in {"superseded", "withdrawn"}:
            raise MediaSubtitleError("SCRIPT_VERSION_NOT_USABLE", "withdrawn or superseded script cannot be subtitled")
        segments = script.get("segments")
        if not isinstance(segments, list) or len(segments) != 3:
            raise MediaSubtitleError("SCRIPT_TIMELINE_INVALID", "script must contain three segments")
        previous = 0
        for expected_sequence, segment in enumerate(segments, 1):
            if segment["sequence"] != expected_sequence or segment["start_ms"] != previous or segment["end_ms"] <= segment["start_ms"]:
                raise MediaSubtitleError("SCRIPT_TIMELINE_INVALID", "script segment timeline is not contiguous")
            previous = segment["end_ms"]
        if previous != int(script["duration_seconds"]) * 1000:
            raise MediaSubtitleError("SCRIPT_TIMELINE_INVALID", "script timeline does not cover its duration")
        return script

    def _storyboard(self, *, tenant: str, value: Any, version_id: Any, script: Mapping[str, Any]) -> dict[str, Any] | None:
        expected = _uuid(version_id, "media_storyboard_version_id", code="STORYBOARD_VERSION_NOT_FOUND") if version_id is not None else None
        candidate = value
        if candidate is None and expected is None:
            return None
        if candidate is None:
            if self.storyboard_port is None:
                raise MediaSubtitleError("STORYBOARD_VERSION_NOT_FOUND", "exact MediaStoryboardVersion is required")
            candidate = self._lookup(port=self.storyboard_port, tenant=tenant, identity=expected, kind="storyboard_version")
        if isinstance(candidate, Mapping) and "version" in candidate:
            candidate = candidate["version"]
        storyboard = _safe_json(_mapping_safe(candidate, "media_storyboard_version"))
        _error_schema(STORYBOARD_VERSION_VALIDATOR, storyboard, "STORYBOARD_VERSION_INVALID")
        identity = _uuid(storyboard.get("id"), "media_storyboard_version.id", code="STORYBOARD_VERSION_NOT_FOUND")
        if expected is not None and identity != expected:
            raise MediaSubtitleError("STORYBOARD_VERSION_NOT_FOUND", "storyboard port returned a different version")
        if _uuid(storyboard.get("org_id"), "media_storyboard_version.org_id") != tenant:
            raise MediaSubtitleError("TENANT_SCOPE_VIOLATION", "MediaStoryboardVersion is outside this organization")
        if storyboard.get("status") in {"superseded", "withdrawn"}:
            raise MediaSubtitleError("STORYBOARD_VERSION_NOT_USABLE", "withdrawn or superseded storyboard cannot be subtitled")
        if storyboard["media_script_version_id"] != script["id"] or storyboard["duration_seconds"] != script["duration_seconds"]:
            raise MediaSubtitleError("STORYBOARD_LINEAGE_MISMATCH", "storyboard does not belong to the selected script")
        return storyboard

    def _normalize_accessibility(self, value: Any, *, kind: str, cues: list[dict[str, Any]]) -> dict[str, Any]:
        raw = _mapping_safe(value or {}, "accessibility")
        _reject_sensitive_keys(raw)
        for field in ("captions_complete", "speaker_labels_complete", "sound_descriptions_complete"):
            if field in raw and type(raw[field]) is not bool:
                raise MediaSubtitleError("ACCESSIBILITY_INVALID", f"{field} must be boolean")
        result = {
            "captions_complete": raw.get("captions_complete", kind == "caption"),
            "speaker_labels_complete": raw.get("speaker_labels_complete", False),
            "sound_descriptions_complete": raw.get("sound_descriptions_complete", False),
            "reading_order": raw.get("reading_order", "chronological"),
            "max_lines": raw.get("max_lines", 2),
            "max_chars_per_line": raw.get("max_chars_per_line", 42),
        }
        if result["reading_order"] not in {"chronological", "script_order"}:
            raise MediaSubtitleError("ACCESSIBILITY_INVALID", "reading_order is invalid")
        if type(result["max_lines"]) is not int or not 1 <= result["max_lines"] <= 4:
            raise MediaSubtitleError("ACCESSIBILITY_INVALID", "max_lines is invalid")
        if type(result["max_chars_per_line"]) is not int or not 1 <= result["max_chars_per_line"] <= 80:
            raise MediaSubtitleError("ACCESSIBILITY_INVALID", "max_chars_per_line is invalid")
        if kind == "caption" and not result["captions_complete"]:
            raise MediaSubtitleError("ACCESSIBILITY_INVALID", "caption tracks must be complete")
        if result["speaker_labels_complete"] and any(item["speaker_label"] is None for item in cues):
            raise MediaSubtitleError("ACCESSIBILITY_INVALID", "speaker labels are incomplete")
        if result["sound_descriptions_complete"] and any(item["sound_description"] is None for item in cues):
            raise MediaSubtitleError("ACCESSIBILITY_INVALID", "sound descriptions are incomplete")
        return result

    def _normalize_tracks(self, *, tracks: Any, locale: Any, cues: Any, language_name: Any,
                          kind: str, direction: str | None, is_default: bool | None,
                          accessibility: Any, script: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if tracks is None:
            if locale is None or cues is None:
                raise MediaSubtitleError("TRACKS_REQUIRED", "at least one locale track is required")
            tracks = [{
                "locale": locale, "cues": cues, "language_name": language_name,
                "kind": kind, "direction": direction, "is_default": True if is_default is None else is_default,
                "accessibility": accessibility,
            }]
        if isinstance(tracks, Mapping):
            # Accept a locale -> track/cue mapping at the boundary, then
            # normalize it to the closed array contract.
            mapped_tracks: list[dict[str, Any]] = []
            for mapped_locale, mapped_value in tracks.items():
                if isinstance(mapped_value, Mapping):
                    mapped = dict(mapped_value)
                    mapped.setdefault("locale", mapped_locale)
                else:
                    mapped = {"locale": mapped_locale, "cues": mapped_value}
                mapped_tracks.append(mapped)
            tracks = mapped_tracks
        if isinstance(tracks, (str, bytes, bytearray)):
            raise MediaSubtitleError("TRACKS_INVALID", "tracks must be an array")
        try:
            raw_tracks = list(tracks)
        except TypeError as exc:
            raise MediaSubtitleError("TRACKS_INVALID", "tracks must be an array") from exc
        if not raw_tracks:
            raise MediaSubtitleError("TRACKS_REQUIRED", "at least one locale track is required")
        intervals = {int(item["sequence"]): (int(item["start_ms"]), int(item["end_ms"])) for item in script["segments"]}
        normalized: list[dict[str, Any]] = []
        seen_locales: set[str] = set()
        for track_index, raw_value in enumerate(raw_tracks):
            raw = _mapping_safe(raw_value, f"tracks[{track_index}]")
            _reject_sensitive_keys(raw)
            track_locale = _canonical_locale(raw.get("locale"), f"tracks[{track_index}].locale")
            if track_locale in seen_locales:
                raise MediaSubtitleError("TRACK_LOCALE_DUPLICATE", "track locales must be unique")
            seen_locales.add(track_locale)
            track_kind = raw.get("kind", "caption")
            if track_kind not in {"caption", "subtitle"}:
                raise MediaSubtitleError("TRACKS_INVALID", "track kind is invalid")
            inferred_direction = "rtl" if track_locale.split("-", 1)[0] in RTL_LANGUAGES else "ltr"
            track_direction = raw.get("direction") or inferred_direction
            if track_direction not in {"ltr", "rtl"}:
                raise MediaSubtitleError("TRACKS_INVALID", "track direction is invalid")
            raw_cues = raw.get("cues")
            if not isinstance(raw_cues, Sequence) or isinstance(raw_cues, (str, bytes, bytearray)) or not raw_cues:
                raise MediaSubtitleError("CUES_REQUIRED", "each track requires cues")
            indexed: list[tuple[int, int, Mapping[str, Any]]] = []
            seen_sequences: set[int] = set()
            for cue_index, cue_value in enumerate(raw_cues):
                cue = _mapping_safe(cue_value, f"tracks[{track_index}].cues[{cue_index}]")
                _reject_sensitive_keys(cue)
                sequence = cue.get("sequence")
                if type(sequence) is not int or sequence < 1 or sequence in seen_sequences:
                    raise MediaSubtitleError("CUE_SEQUENCE_INVALID", "cue sequences must be unique positive integers")
                seen_sequences.add(sequence)
                indexed.append((sequence, cue_index, cue))
            cues_norm: list[dict[str, Any]] = []
            previous_end = -1
            for sequence, cue_index, cue in sorted(indexed, key=lambda item: item[0]):
                try:
                    start_ms, end_ms = int(cue["start_ms"]), int(cue["end_ms"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise MediaSubtitleError("CUE_TIMELINE_INVALID", "cue timing is invalid") from exc
                if sequence != len(cues_norm) + 1 or start_ms < 0 or end_ms <= start_ms or end_ms - start_ms < 250:
                    raise MediaSubtitleError("CUE_TIMELINE_INVALID", "cue sequence or duration is invalid")
                if end_ms > int(script["duration_seconds"]) * 1000 or start_ms < previous_end:
                    raise MediaSubtitleError("CUE_TIMELINE_INVALID", "cues overlap or exceed the script duration")
                segment_sequence = cue.get("source_segment_sequence")
                if type(segment_sequence) is not int or segment_sequence not in intervals:
                    raise MediaSubtitleError("CUE_SOURCE_INVALID", "cue source segment is invalid")
                segment_start, segment_end = intervals[segment_sequence]
                if start_ms < segment_start or end_ms > segment_end:
                    raise MediaSubtitleError("CUE_SOURCE_INVALID", "cue must remain inside its script segment")
                text = _text(cue.get("text"), f"tracks[{track_index}].cues[{cue_index}].text", 500, code="CUE_TEXT_INVALID")
                speaker = cue.get("speaker_label")
                if speaker is not None:
                    speaker = _text(speaker, "speaker_label", 120, code="CUE_TEXT_INVALID")
                sound = cue.get("sound_description")
                if sound is not None:
                    sound = _text(sound, "sound_description", 240, code="CUE_TEXT_INVALID")
                forced = cue.get("is_forced", False)
                if not isinstance(forced, bool):
                    raise MediaSubtitleError("CUE_ACCESSIBILITY_INVALID", "is_forced must be boolean")
                line, position = cue.get("line", 90), cue.get("position", 50)
                if type(line) is not int or not 0 <= line <= 100 or type(position) is not int or not 0 <= position <= 100:
                    raise MediaSubtitleError("CUE_POSITION_INVALID", "cue position is invalid")
                align = cue.get("align", "center")
                if align not in {"start", "center", "end"}:
                    raise MediaSubtitleError("CUE_POSITION_INVALID", "cue alignment is invalid")
                cues_norm.append({
                    "sequence": sequence, "source_segment_sequence": segment_sequence,
                    "start_ms": start_ms, "end_ms": end_ms, "text": text,
                    "speaker_label": speaker, "sound_description": sound, "is_forced": forced,
                    "line": line, "position": position, "align": align,
                })
                previous_end = end_ms
            track_accessibility = self._normalize_accessibility(raw.get("accessibility"), kind=track_kind, cues=cues_norm)
            source_text_hash = _hash({"locale": track_locale, "kind": track_kind, "cues": cues_norm})
            supplied_hash = raw.get("source_text_hash")
            if supplied_hash is not None and supplied_hash != source_text_hash:
                raise MediaSubtitleError("SUBTITLE_HASH_MISMATCH", "source_text_hash does not match cue text")
            raw_default = raw.get("is_default", False)
            if type(raw_default) is not bool:
                raise MediaSubtitleError("TRACKS_INVALID", "is_default must be boolean")
            normalized.append({
                "locale": track_locale,
                "language_name": _text(raw.get("language_name") or track_locale, "language_name", 80),
                "kind": track_kind, "direction": track_direction,
                "is_default": raw_default,
                "text_version": raw.get("text_version", 1), "source_text_hash": source_text_hash,
                "cues": cues_norm, "cue_count": len(cues_norm), "accessibility": track_accessibility,
            })
            if type(normalized[-1]["text_version"]) is not int or normalized[-1]["text_version"] < 1:
                raise MediaSubtitleError("TEXT_VERSION_INVALID", "text_version must be positive")
        normalized.sort(key=lambda item: item["locale"])
        defaults = [item for item in normalized if item["is_default"]]
        if len(defaults) == 0:
            normalized[0]["is_default"] = True
        elif len(defaults) != 1:
            raise MediaSubtitleError("DEFAULT_TRACK_INVALID", "exactly one track must be default")
        top_accessibility = _mapping_safe(accessibility or {}, "accessibility") if accessibility is not None else {
            "captions_complete": all(item["accessibility"]["captions_complete"] for item in normalized if item["kind"] == "caption") if any(item["kind"] == "caption" for item in normalized) else False,
            "speaker_labels_complete": all(item["accessibility"]["speaker_labels_complete"] for item in normalized),
            "sound_descriptions_complete": all(item["accessibility"]["sound_descriptions_complete"] for item in normalized),
            "reading_order": "chronological", "max_lines": 2, "max_chars_per_line": 42,
        }
        # Validate the aggregate profile through the same field rules.
        top_accessibility = self._normalize_accessibility(top_accessibility, kind="caption" if any(item["kind"] == "caption" for item in normalized) else "subtitle", cues=[])
        return normalized, top_accessibility

    def _build_version(self, *, tenant: str, actor: str, script: Mapping[str, Any], storyboard: Mapping[str, Any] | None,
                       subtitle_id: str, version_no: int, tracks: list[dict[str, Any]], accessibility: dict[str, Any],
                       reason: str | None, supersedes: str | None, at: datetime, status: str) -> tuple[dict[str, Any], str]:
        material = {
            "org_id": tenant, "media_subtitle_id": subtitle_id, "media_script_version_id": script["id"],
            "media_storyboard_version_id": storyboard["id"] if storyboard else None,
            "version_no": version_no, "duration_seconds": script["duration_seconds"],
            "policy_snapshot_id": script["policy_snapshot_id"], "template_version": TEMPLATE_VERSION,
            "status": status, "tracks": tracks, "track_count": len(tracks), "accessibility": accessibility,
            "revision_reason": reason, "supersedes_version_id": supersedes,
            "source_script_snapshot_hash": str(script["snapshot_hash"]).lower(),
            "source_storyboard_snapshot_hash": str(storyboard["snapshot_hash"]).lower() if storyboard else None,
        }
        snapshot_hash = _hash(material)
        version_id = str(uuid5(VERSION_NAMESPACE, f"{subtitle_id}:{version_no}:{snapshot_hash}"))
        stamp = _stamp(at)
        version = {"id": version_id, **material, "snapshot_hash": snapshot_hash, "created_by": actor, "created_at": stamp}
        _error_schema(SUBTITLE_VERSION_VALIDATOR, version, "INVALID_SUBTITLE_VERSION")
        return version, stamp

    @_audit_failures
    def create_subtitle(
        self, script_version: Any | None = None, *, media_script_version_id: UUID | str | None = None,
        tracks: Any | None = None, locale: str | None = None, cues: Any | None = None,
        language_name: str | None = None, kind: str = "caption", direction: str | None = None,
        is_default: bool | None = None, accessibility: Any | None = None,
        storyboard_version: Any | None = None, media_storyboard_version_id: UUID | str | None = None,
        org_id: UUID | str | None = None, tenant_context: Any | None = None,
        actor_id: UUID | str | None = None, trace_id: str = "media-subtitle-create",
        idempotency_key: str, created_at: Any | None = None,
    ) -> dict[str, Any]:
        tenant, actor = _context(org_id=org_id, actor_id=actor_id, tenant_context=tenant_context)
        trace = _text(trace_id, "trace_id", 256)
        key = _text(idempotency_key, "idempotency_key", 200)
        at = self._now(created_at, "created_at")
        script = self._script(tenant=tenant, value=script_version, version_id=media_script_version_id)
        storyboard = self._storyboard(tenant=tenant, value=storyboard_version, version_id=media_storyboard_version_id, script=script)
        normalized_tracks, normalized_accessibility = self._normalize_tracks(
            tracks=tracks, locale=locale, cues=cues, language_name=language_name, kind=kind,
            direction=direction, is_default=is_default, accessibility=accessibility, script=script,
        )
        request_hash = _hash({
            "operation": "create", "media_script_version_id": script["id"],
            "media_storyboard_version_id": storyboard["id"] if storyboard else None,
            "tracks": normalized_tracks, "accessibility": normalized_accessibility,
        })
        replay = self.store.replay(org_id=tenant, namespace="create", key=key, request_hash=request_hash)
        if replay is not None:
            return replay
        storyboard_key = storyboard["id"] if storyboard else "-"
        subtitle_id = str(uuid5(SUBTITLE_NAMESPACE, f"{tenant}:{script['id']}:{storyboard_key}"))
        version, stamp = self._build_version(
            tenant=tenant, actor=actor, script=script, storyboard=storyboard, subtitle_id=subtitle_id,
            version_no=1, tracks=normalized_tracks, accessibility=normalized_accessibility,
            reason=None, supersedes=None, at=at, status="draft",
        )
        root = {
            "id": subtitle_id, "org_id": tenant, "media_script_version_id": script["id"],
            "media_storyboard_version_id": storyboard["id"] if storyboard else None,
            "duration_seconds": script["duration_seconds"], "current_version_id": version["id"],
            "status": "draft", "created_by": actor, "created_at": stamp, "updated_at": stamp,
        }
        _error_schema(SUBTITLE_VALIDATOR, root, "INVALID_SUBTITLE")
        return self.store.create(
            root=root, version=version, namespace="create", key=key, request_hash=request_hash,
            audit={
                "operation": "create_subtitle", "org_id": tenant, "media_subtitle_id": subtitle_id,
                "version_id": version["id"], "version_no": 1, "media_script_version_id": script["id"],
                "policy_snapshot_id": script["policy_snapshot_id"], "request_hash": request_hash,
                "snapshot_hash": version["snapshot_hash"], "status": "created", "actor_id": actor,
                "trace_id": trace, "duration_ms": 0, "cost_units": 0, "created_at": stamp,
            },
        )

    @_audit_failures
    def revise_subtitle(
        self, *, media_subtitle_id: UUID | str, expected_version_no: int, tracks: Any | None = None,
        locale: str | None = None, cues: Any | None = None, language_name: str | None = None,
        kind: str = "caption", direction: str | None = None, is_default: bool | None = None,
        accessibility: Any | None = None, script_version: Any | None = None,
        storyboard_version: Any | None = None, media_storyboard_version_id: UUID | str | None = None,
        revision_reason: str, org_id: UUID | str | None = None, tenant_context: Any | None = None,
        actor_id: UUID | str | None = None, trace_id: str = "media-subtitle-revise",
        idempotency_key: str, revised_at: Any | None = None,
    ) -> dict[str, Any]:
        tenant, actor = _context(org_id=org_id, actor_id=actor_id, tenant_context=tenant_context)
        subtitle_id = _uuid(media_subtitle_id, "media_subtitle_id")
        trace = _text(trace_id, "trace_id", 256)
        key = _text(idempotency_key, "idempotency_key", 200)
        reason = _text(revision_reason, "revision_reason", 1000, code="SUBTITLE_REVISION_INVALID")
        if type(expected_version_no) is not int or expected_version_no < 1:
            raise MediaSubtitleError("VERSION_CONFLICT", "expected_version_no must be positive")
        root = self.store.get_subtitle(org_id=tenant, subtitle_id=subtitle_id)
        current = self.store.get_version(org_id=tenant, version_id=root["current_version_id"])
        if int(current["version_no"]) != expected_version_no:
            raise MediaSubtitleError("VERSION_CONFLICT", "subtitle current version changed")
        script = self._script(tenant=tenant, value=script_version, version_id=current["media_script_version_id"])
        if str(script["snapshot_hash"]).lower() != str(current["source_script_snapshot_hash"]).lower():
            raise MediaSubtitleError("SCRIPT_SNAPSHOT_MISMATCH", "script snapshot changed for this subtitle")
        storyboard_id = media_storyboard_version_id
        if storyboard_id is None:
            storyboard_id = root.get("media_storyboard_version_id")
        storyboard_value = storyboard_version
        if storyboard_value is None and storyboard_id is None:
            storyboard = None
        else:
            storyboard = self._storyboard(tenant=tenant, value=storyboard_value, version_id=storyboard_id, script=script)
        expected_story_hash = current.get("source_storyboard_snapshot_hash")
        actual_story_hash = storyboard.get("snapshot_hash") if storyboard else None
        if (expected_story_hash or None) != (actual_story_hash or None):
            raise MediaSubtitleError("STORYBOARD_SNAPSHOT_MISMATCH", "storyboard snapshot changed for this subtitle")
        at = self._now(revised_at, "revised_at")
        normalized_tracks, normalized_accessibility = self._normalize_tracks(
            tracks=tracks, locale=locale, cues=cues, language_name=language_name, kind=kind,
            direction=direction, is_default=is_default, accessibility=accessibility, script=script,
        )
        request_hash = _hash({
            "operation": "revise", "media_subtitle_id": subtitle_id, "expected_version_no": expected_version_no,
            "tracks": normalized_tracks, "accessibility": normalized_accessibility, "revision_reason": reason,
        })
        replay = self.store.replay(org_id=tenant, namespace="revise", key=key, request_hash=request_hash)
        if replay is not None:
            return replay
        version, stamp = self._build_version(
            tenant=tenant, actor=actor, script=script, storyboard=storyboard, subtitle_id=subtitle_id,
            version_no=expected_version_no + 1, tracks=normalized_tracks, accessibility=normalized_accessibility,
            reason=reason, supersedes=current["id"], at=at, status="edited",
        )
        updated_root = {**root, "current_version_id": version["id"], "updated_at": stamp}
        _error_schema(SUBTITLE_VALIDATOR, updated_root, "INVALID_SUBTITLE")
        return self.store.append(
            org_id=tenant, subtitle_id=subtitle_id, expected_version_no=expected_version_no,
            root=updated_root, version=version, namespace="revise", key=key, request_hash=request_hash,
            audit={
                "operation": "revise_subtitle", "org_id": tenant, "media_subtitle_id": subtitle_id,
                "version_id": version["id"], "version_no": expected_version_no + 1,
                "media_script_version_id": script["id"], "policy_snapshot_id": script["policy_snapshot_id"],
                "request_hash": request_hash, "snapshot_hash": version["snapshot_hash"],
                "status": "edited", "actor_id": actor, "trace_id": trace,
                "duration_ms": 0, "cost_units": 0, "created_at": stamp,
            },
        )

    def get_subtitle(self, *, media_subtitle_id: UUID | str, org_id: UUID | str | None = None,
                     tenant_context: Any | None = None) -> dict[str, Any]:
        tenant, _ = _context(org_id=org_id, actor_id=None, tenant_context=tenant_context)
        return self.store.get_subtitle(org_id=tenant, subtitle_id=_uuid(media_subtitle_id, "media_subtitle_id"))

    def get_version(self, *, version_id: UUID | str, org_id: UUID | str | None = None,
                    tenant_context: Any | None = None) -> dict[str, Any]:
        tenant, _ = _context(org_id=org_id, actor_id=None, tenant_context=tenant_context)
        return self.store.get_version(org_id=tenant, version_id=_uuid(version_id, "version_id"))

    def list_versions(self, *, media_subtitle_id: UUID | str, org_id: UUID | str | None = None,
                      tenant_context: Any | None = None) -> list[dict[str, Any]]:
        tenant, _ = _context(org_id=org_id, actor_id=None, tenant_context=tenant_context)
        return self.store.list_versions(org_id=tenant, subtitle_id=_uuid(media_subtitle_id, "media_subtitle_id"))


SubtitleService = MediaSubtitleService
MediaSubtitleStore = InMemoryMediaSubtitleStore
# Friendly aliases used by adapters that call the track a caption.
MediaSubtitleService.create_captions = MediaSubtitleService.create_subtitle
MediaSubtitleService.edit_subtitle = MediaSubtitleService.revise_subtitle


__all__ = [
    "InMemoryMediaSubtitleStore", "MediaSubtitleError", "MediaSubtitleService", "MediaSubtitleStore",
    "ScriptVersionPort", "StoryboardVersionPort", "SubtitleService", "TEMPLATE_VERSION",
]
