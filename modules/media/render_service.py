"""Input-locked render jobs and private intermediate artifact confirmation."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from functools import wraps
import json
from hashlib import sha256
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
JOB_VALIDATOR = Draft202012Validator(json.loads((CONTRACTS / "render-job.schema.json").read_text(encoding="utf-8")), format_checker=FormatChecker())
ASSET_VALIDATOR = Draft202012Validator(json.loads((CONTRACTS / "asset-version.schema.json").read_text(encoding="utf-8")), format_checker=FormatChecker())
SCRIPT_VALIDATOR = Draft202012Validator(json.loads((CONTRACTS / "media-script-version.schema.json").read_text(encoding="utf-8")), format_checker=FormatChecker())
STORYBOARD_VALIDATOR = Draft202012Validator(json.loads((CONTRACTS / "media-storyboard-version.schema.json").read_text(encoding="utf-8")), format_checker=FormatChecker())
SUBTITLE_VALIDATOR = Draft202012Validator(json.loads((CONTRACTS / "media-subtitle-version.schema.json").read_text(encoding="utf-8")), format_checker=FormatChecker())
VISUAL_VALIDATOR = Draft202012Validator(json.loads((CONTRACTS / "media-visual-asset-set-version.schema.json").read_text(encoding="utf-8")), format_checker=FormatChecker())
OUTPUT_VALIDATOR = Draft202012Validator(json.loads((CONTRACTS / "media-output-spec-version.schema.json").read_text(encoding="utf-8")), format_checker=FormatChecker())

TEMPLATE_VERSION = "media-render-job-v1"
SYSTEM_ACTOR = UUID("00000000-0000-4000-8000-000000000001")
JOB_NAMESPACE = UUID("ea3d3c49-4e00-5658-aab7-5d00a479cb4c")
ASSET_NAMESPACE = UUID("9946f514-66bb-5b78-b128-50e4ca17a3ef")
HASH_RE = r"^[A-Fa-f0-9]{64}$"
SENSITIVE_KEYS = frozenset({"model", "provider", "credential", "token", "secret", "password", "authorization", "api_key", "raw_output"})


class MediaRenderError(ValueError):
    """Stable, non-sensitive MEDIA-004A failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class VersionPort(Protocol):
    def get_version(self, *, org_id: str, version_id: str) -> Mapping[str, Any]: ...


class RendererPort(Protocol):
    def render(self, job: Mapping[str, Any], *, profile: Mapping[str, Any]) -> Any: ...


class StoragePort(Protocol):
    def put(self, org_id: str, object_key: str, content: bytes, *, content_type: str = "application/octet-stream", metadata: Mapping[str, str] | None = None, idempotency_key: str | None = None) -> Any: ...
    def head(self, org_id: str, storage_object_ref: str) -> Any: ...
    def get(self, org_id: str, storage_object_ref: str) -> bytes: ...


class InMemoryPrivateStorage:
    """Small account-free storage fallback; real deployments inject FakeStorage or another adapter."""

    def __init__(self) -> None:
        self._objects: dict[tuple[str, str], tuple[dict[str, Any], bytes]] = {}
        self._idempotency: dict[tuple[str, str], str] = {}

    def put(self, org_id: str, object_key: str, content: bytes, *, content_type: str = "application/octet-stream",
            metadata: Mapping[str, str] | None = None, idempotency_key: str | None = None) -> Any:
        if not isinstance(content, bytes) or not object_key or object_key.startswith(("http://", "https://")):
            raise ValueError("private object input is invalid")
        digest = _bytes_hash(content)
        if idempotency_key is not None:
            prior = self._idempotency.get((str(org_id), idempotency_key))
            if prior is not None and prior != digest:
                raise ValueError("storage idempotency key conflict")
            self._idempotency[(str(org_id), idempotency_key)] = digest
        ref = f"private://media-render/{org_id}/{object_key}"
        identity = (str(org_id), ref)
        prior = self._objects.get(identity)
        if prior is not None and prior[0]["content_hash"] != digest:
            raise ValueError("private object is immutable")
        record = {"storage_object_ref": ref, "content_hash": digest, "size_bytes": len(content),
                  "content_type": content_type, "access_policy": "private", "org_id": str(org_id)}
        self._objects[identity] = (record, content)
        return type("StoredObject", (), record)()

    def head(self, org_id: str, storage_object_ref: str) -> Any:
        try:
            record, _ = self._objects[(str(org_id), storage_object_ref)]
        except KeyError as exc:
            raise KeyError("private object not found") from exc
        return type("StoredObject", (), record)()

    def get(self, org_id: str, storage_object_ref: str) -> bytes:
        try:
            return self._objects[(str(org_id), storage_object_ref)][1]
        except KeyError as exc:
            raise KeyError("private object not found") from exc


def _uuid(value: Any, field: str, *, code: str = "INVALID_RENDER_INPUT") -> str:
    try:
        return _script_uuid(value, field, code=code)
    except MediaScriptError as exc:
        raise MediaRenderError(exc.code, str(exc)) from exc


def _time(value: Any, field: str) -> datetime:
    try:
        return _script_time(value, field)
    except MediaScriptError as exc:
        raise MediaRenderError(exc.code, str(exc)) from exc


def _context(*, org_id: Any, actor_id: Any, tenant_context: Any) -> tuple[str, str]:
    try:
        return _script_context(org_id=org_id, actor_id=actor_id, tenant_context=tenant_context)
    except MediaScriptError as exc:
        raise MediaRenderError(exc.code, str(exc)) from exc


def _schema(validator: Draft202012Validator, value: Mapping[str, Any], code: str) -> None:
    try:
        _script_schema_error(validator, value, code)
    except MediaScriptError as exc:
        raise MediaRenderError(exc.code, str(exc)) from exc


def _safe(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return _stamp(value)
    if isinstance(value, Mapping):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise MediaRenderError("INVALID_RENDER_INPUT", "input contains a non-JSON value")


def _bytes_hash(value: bytes) -> str:
    return sha256(value).hexdigest()


def _same_hash(left: Any, right: Any) -> bool:
    return str(left).lower() == str(right).lower()


def _mapping_safe(value: Any, field: str) -> dict[str, Any]:
    try:
        return deepcopy(dict(_mapping(value, field)))
    except MediaScriptError as exc:
        raise MediaRenderError("INVALID_RENDER_INPUT", f"{field} must be an object") from exc


def _text(value: Any, field: str, maximum: int, *, code: str = "INVALID_RENDER_INPUT") -> str:
    if not isinstance(value, str):
        raise MediaRenderError(code, f"{field} must be text")
    result = value.strip()
    if not result or len(result) > maximum or any(ord(c) < 0x20 and c not in "\t\n\r" for c in result):
        raise MediaRenderError(code, f"{field} has an invalid value")
    return result


def _reject_sensitive(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_KEYS:
                raise MediaRenderError("SENSITIVE_INPUT_REJECTED", "render input contains a restricted field")
            _reject_sensitive(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _reject_sensitive(item)


def _audit_failures(method: Any) -> Any:
    @wraps(method)
    def wrapped(self: "MediaRenderService", *args: Any, **kwargs: Any) -> Any:
        try:
            return method(self, *args, **kwargs)
        except MediaRenderError as exc:
            raw_org = kwargs.get("org_id")
            context = kwargs.get("tenant_context")
            if isinstance(context, Mapping):
                raw_org = context.get("org_id") or context.get("tenant_id") or raw_org
            elif context is not None:
                raw_org = getattr(context, "org_id", None) or getattr(context, "tenant_id", None) or raw_org
            try:
                safe_org = _uuid(raw_org, "org_id") if raw_org is not None else None
            except Exception:
                safe_org = None
            with self.store._lock:
                self.store.audit.append({"operation": method.__name__, "org_id": safe_org, "job_id": kwargs.get("media_render_job_id"), "status": "rejected", "error_code": exc.code, "trace_id": kwargs.get("trace_id", "media-render"), "duration_ms": 0, "cost_units": 0})
            raise
    return wrapped


class FakeRenderer:
    """Account-free deterministic renderer used by acceptance tests."""

    def __init__(self, *, content: bytes | None = None, content_type: str = "video/mp4") -> None:
        self.content = content
        self.content_type = content_type
        self.calls: list[dict[str, Any]] = []

    def render(self, job: Mapping[str, Any], *, profile: Mapping[str, Any]) -> dict[str, Any]:
        self.calls.append({"job_id": job["id"], "profile_key": profile["profile_key"]})
        payload = self.content if self.content is not None else f"synthetic-render:{job['input_hash']}:{profile['profile_key']}".encode()
        return {"content": payload, "content_type": self.content_type, "stage": "full", "shot_sequence": None}


class InMemoryMediaRenderStore:
    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}
        self.inputs: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.commands: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.artifacts: dict[tuple[str, str, str], dict[str, Any]] = {}
        # MEDIA-004B keeps retry decisions and failure facts in append-only
        # projections.  The dictionaries are intentionally public on the
        # account-free store so adapters/tests can inspect the same facts that
        # a database projection would expose.
        self.failures: dict[tuple[str, str, int, str], dict[str, Any]] = {}
        self.retry_schedules: dict[tuple[str, str, int], dict[str, Any]] = {}
        self.retry_commands: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.rerender_targets: dict[tuple[str, str, str, int, str], dict[str, Any]] = {}
        self.human_tasks: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.job_versions: dict[tuple[str, str], int] = {}
        self.audit: list[dict[str, Any]] = []
        self.outbox: list[dict[str, Any]] = []
        self._lock = RLock()

    def replay(self, *, org_id: str, namespace: str, key: str, request_hash: str) -> dict[str, Any] | None:
        with self._lock:
            prior = self.commands.get((org_id, namespace, key))
            if prior is None:
                return None
            if prior["request_hash"] != request_hash:
                raise MediaRenderError("IDEMPOTENCY_KEY_REUSED", "command payload differs from prior request")
            return deepcopy(prior["response"])

    def create(self, *, job: Mapping[str, Any], namespace: str, key: str, request_hash: str, response: Mapping[str, Any], audit: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            command_key = (str(job["org_id"]), namespace, key)
            prior = self.commands.get(command_key)
            if prior is not None:
                if prior["request_hash"] != request_hash:
                    raise MediaRenderError("IDEMPOTENCY_KEY_REUSED", "command payload differs from prior request")
                return deepcopy(prior["response"])
            natural = next((value for value in self.jobs.values() if value["org_id"] == job["org_id"] and value["input_hash"] == job["input_hash"]), None)
            if natural is not None:
                raise MediaRenderError("RENDER_JOB_ALREADY_EXISTS", "an identical render job already exists")
            self.jobs[str(job["id"])] = deepcopy(dict(job))
            self.job_versions[(str(job["org_id"]), str(job["id"]))] = 1
            input_map = (
                ("script", job["media_script_version_id"], job["input_snapshot_hashes"]["script"], None),
                ("storyboard", job["media_storyboard_version_id"], job["input_snapshot_hashes"]["storyboard"], None),
                ("subtitle", job["media_subtitle_version_id"], job["input_snapshot_hashes"]["subtitle"], None),
                ("visual_asset_set", job["media_visual_asset_set_version_id"], job["input_snapshot_hashes"]["visual_asset_set"], None),
                ("output_spec", job["media_output_spec_version_id"], job["input_snapshot_hashes"]["output_spec"], None),
                ("asset_version", job["asset_version_id"], job["input_snapshot_hashes"]["asset_version"], job.get("asset_version_no")),
            )
            sequence = 0
            for kind, identity, digest, expected_version_no in input_map:
                if identity is None or digest is None:
                    continue
                sequence += 1
                self.inputs[(str(job["org_id"]), str(job["id"]), kind)] = {
                    "org_id": str(job["org_id"]), "render_job_id": str(job["id"]), "sequence": sequence,
                    "input_kind": kind, "input_version_id": identity, "snapshot_hash": digest,
                    "expected_version_no": expected_version_no, "created_at": job["created_at"],
                }
            self.commands[command_key] = {"request_hash": request_hash, "response": deepcopy(dict(response))}
            self.audit.append(deepcopy(dict(audit)))
            return deepcopy(dict(response))

    def get(self, *, org_id: str, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self.jobs.get(job_id)
            if job is None or job["org_id"] != org_id:
                raise MediaRenderError("TENANT_SCOPE_VIOLATION", "render job is outside this organization")
            return deepcopy(job)

    def save(self, *, org_id: str, job: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            prior = self.jobs.get(str(job["id"]))
            if prior is None or prior["org_id"] != org_id:
                raise MediaRenderError("TENANT_SCOPE_VIOLATION", "render job is outside this organization")
            self.jobs[str(job["id"])] = deepcopy(dict(job))
            return deepcopy(dict(job))

    def claim_running(self, *, org_id: str, job_id: str, stamp: str, allow_retry: bool = False) -> dict[str, Any]:
        """Atomically claim a planned job so concurrent workers cannot render twice."""
        with self._lock:
            job = self.jobs.get(job_id)
            if job is None or job["org_id"] != org_id:
                raise MediaRenderError("TENANT_SCOPE_VIOLATION", "render job is outside this organization")
            if job["status"] == "succeeded":
                return deepcopy(job)
            if job["status"] == "running":
                raise MediaRenderError("RENDER_JOB_IN_PROGRESS", "render job is already running")
            if job["status"] in {"failed", "unknown", "dead_letter"}:
                raise MediaRenderError("RENDER_JOB_NOT_EXECUTABLE", "render job requires a later retry task")
            if job["status"] == "retry_scheduled" and not allow_retry:
                raise MediaRenderError("RENDER_JOB_NOT_EXECUTABLE", "render job requires its scheduled retry")
            if job["status"] not in {"planned", "retry_scheduled"}:
                raise MediaRenderError("RENDER_JOB_NOT_EXECUTABLE", "render job is not executable")
            job["status"], job["attempt_count"], job["updated_at"] = "running", int(job["attempt_count"]) + 1, stamp
            self.jobs[job_id] = deepcopy(job)
            self.job_versions[(str(org_id), str(job_id))] = self.job_versions.get((str(org_id), str(job_id)), 1) + 1
            return deepcopy(job)

    def add_artifact(self, *, org_id: str, job_id: str, artifact: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            if job_id not in self.jobs or self.jobs[job_id]["org_id"] != org_id:
                raise MediaRenderError("TENANT_SCOPE_VIOLATION", "render job is outside this organization")
            natural = (org_id, job_id, f"{artifact['stage']}:{artifact['shot_sequence']}:{artifact['output_profile_key']}")
            prior = self.artifacts.get(natural)
            if prior is not None:
                if prior["content_hash"] != artifact["content_hash"]:
                    raise MediaRenderError("ARTIFACT_KEY_CONFLICT", "artifact key contains a different payload")
                return deepcopy(prior)
            self.artifacts[natural] = deepcopy(dict(artifact))
            return deepcopy(dict(artifact))

    def version(self, *, org_id: str, job_id: str) -> int:
        with self._lock:
            job = self.jobs.get(str(job_id))
            if job is None or job.get("org_id") != str(org_id):
                raise MediaRenderError("TENANT_SCOPE_VIOLATION", "render job is outside this organization")
            return int(self.job_versions.get((str(org_id), str(job_id)), 1))

    def bump_version(self, *, org_id: str, job_id: str) -> int:
        with self._lock:
            key = (str(org_id), str(job_id))
            self.job_versions[key] = self.job_versions.get(key, 1) + 1
            return self.job_versions[key]

    def artifact_for(self, *, org_id: str, job_id: str, stage: str, shot_sequence: int | None,
                     output_profile_key: str) -> dict[str, Any] | None:
        natural = (str(org_id), str(job_id), f"{stage}:{shot_sequence}:{output_profile_key}")
        with self._lock:
            value = self.artifacts.get(natural)
            return deepcopy(value) if value is not None else None


class MediaRenderService:
    def __init__(self, *, script_port: VersionPort | Any | None = None, storyboard_port: VersionPort | Any | None = None,
                 subtitle_port: VersionPort | Any | None = None, visual_port: VersionPort | Any | None = None,
                 output_port: VersionPort | Any | None = None, asset_port: VersionPort | Any | None = None,
                 renderer: RendererPort | Any | None = None, storage: StoragePort | Any | None = None,
                 store: InMemoryMediaRenderStore | None = None, clock: Any | None = None) -> None:
        self.script_port, self.storyboard_port, self.subtitle_port = script_port, storyboard_port, subtitle_port
        self.visual_port, self.output_port, self.asset_port = visual_port, output_port, asset_port
        self.renderer = renderer or FakeRenderer()
        self.storage = storage or InMemoryPrivateStorage()
        self.store = store or InMemoryMediaRenderStore()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def audit_log(self) -> tuple[dict[str, Any], ...]:
        with self.store._lock:
            return tuple(deepcopy(self.store.audit))

    @property
    def outbox_events(self) -> tuple[dict[str, Any], ...]:
        with self.store._lock:
            return tuple(deepcopy(self.store.outbox))

    def _now(self, value: Any | None, field: str) -> datetime:
        return _time(value if value is not None else self.clock(), field)

    def _lookup(self, port: Any, tenant: str, identity: str, kind: str) -> dict[str, Any]:
        if port is None:
            raise MediaRenderError(f"{kind.upper()}_NOT_FOUND", f"{kind} version is required")
        try:
            if hasattr(port, "get_version"):
                value = port.get_version(org_id=tenant, version_id=identity)
            elif hasattr(port, "get"):
                value = port.get(org_id=tenant, version_id=identity)
            elif callable(port):
                value = port(org_id=tenant, version_id=identity)
            else:
                raise TypeError("version port has no lookup operation")
        except MediaRenderError:
            raise
        except (KeyError, LookupError) as exc:
            raise MediaRenderError(f"{kind.upper()}_NOT_FOUND", f"{kind} version does not exist") from exc
        except Exception as exc:
            raise MediaRenderError("DEPENDENCY_UNAVAILABLE", f"{kind} lookup failed") from exc
        if isinstance(value, Mapping) and "version" in value:
            value = value["version"]
        return _safe(_mapping_safe(value, kind))

    def _version(self, *, tenant: str, value: Any, version_id: Any, port: Any, validator: Draft202012Validator,
                 kind: str, unusable: set[str] = frozenset({"withdrawn", "superseded"})) -> dict[str, Any]:
        expected = _uuid(version_id, f"{kind}_id", code=f"{kind.upper()}_NOT_FOUND") if version_id is not None else None
        candidate = value if value is not None else self._lookup(port, tenant, expected, kind)
        if isinstance(candidate, Mapping) and "version" in candidate:
            candidate = candidate["version"]
        result = _safe(_mapping_safe(candidate, kind))
        _reject_sensitive(result)
        _schema(validator, result, f"{kind.upper()}_INVALID")
        identity = _uuid(result.get("id"), f"{kind}.id", code=f"{kind.upper()}_NOT_FOUND")
        if expected is not None and identity != expected:
            raise MediaRenderError(f"{kind.upper()}_NOT_FOUND", f"{kind} port returned a different version")
        if _uuid(result.get("org_id"), f"{kind}.org_id") != tenant:
            raise MediaRenderError("TENANT_SCOPE_VIOLATION", f"{kind} is outside this organization")
        if result.get("status") in unusable:
            raise MediaRenderError(f"{kind.upper()}_NOT_USABLE", f"{kind} cannot be rendered")
        hash_field = "file_hash" if kind == "asset_version" else "snapshot_hash"
        if not re.fullmatch(HASH_RE, str(result.get(hash_field, ""))):
            raise MediaRenderError(f"{kind.upper()}_INVALID", f"{kind} {hash_field} is invalid")
        return result

    def _inputs(self, *, tenant: str, script_version: Any, media_script_version_id: Any, storyboard_version: Any,
                media_storyboard_version_id: Any, subtitle_version: Any, media_subtitle_version_id: Any,
                visual_version: Any, media_visual_asset_set_version_id: Any, output_version: Any,
                media_output_spec_version_id: Any, asset_version: Any, asset_version_id: Any,
                profile_key: str) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None, dict[str, Any], dict[str, Any], dict[str, Any]]:
        script = self._version(tenant=tenant, value=script_version, version_id=media_script_version_id, port=self.script_port, validator=SCRIPT_VALIDATOR, kind="script_version")
        storyboard = None
        storyboard_id = media_storyboard_version_id
        if storyboard_version is not None or storyboard_id is not None:
            storyboard = self._version(tenant=tenant, value=storyboard_version, version_id=storyboard_id, port=self.storyboard_port, validator=STORYBOARD_VALIDATOR, kind="storyboard_version")
            if storyboard["media_script_version_id"] != script["id"] or storyboard["duration_seconds"] != script["duration_seconds"] or storyboard["region_profile_version_id"] != script["region_profile_version_id"] or storyboard["policy_snapshot_id"] != script["policy_snapshot_id"] or not _same_hash(storyboard.get("source_script_snapshot_hash"), script["snapshot_hash"]):
                raise MediaRenderError("SOURCE_LINEAGE_MISMATCH", "storyboard does not match script lineage")
        subtitle = None
        if subtitle_version is not None or media_subtitle_version_id is not None:
            subtitle = self._version(tenant=tenant, value=subtitle_version, version_id=media_subtitle_version_id, port=self.subtitle_port, validator=SUBTITLE_VALIDATOR, kind="subtitle_version")
            if subtitle["media_script_version_id"] != script["id"] or subtitle["duration_seconds"] != script["duration_seconds"] or not _same_hash(subtitle.get("source_script_snapshot_hash"), script["snapshot_hash"]):
                raise MediaRenderError("SOURCE_LINEAGE_MISMATCH", "subtitle does not match script lineage")
            if storyboard is not None and (subtitle.get("media_storyboard_version_id") not in (None, storyboard["id"]) or (subtitle.get("source_storyboard_snapshot_hash") is not None and not _same_hash(subtitle.get("source_storyboard_snapshot_hash"), storyboard["snapshot_hash"]))):
                raise MediaRenderError("SOURCE_LINEAGE_MISMATCH", "subtitle does not match storyboard lineage")
        visual = self._version(tenant=tenant, value=visual_version, version_id=media_visual_asset_set_version_id, port=self.visual_port, validator=VISUAL_VALIDATOR, kind="visual_asset_set_version")
        if visual["media_script_version_id"] != script["id"] or visual["duration_seconds"] != script["duration_seconds"] or visual["region_profile_version_id"] != script["region_profile_version_id"] or visual["policy_snapshot_id"] != script["policy_snapshot_id"] or not _same_hash(visual.get("source_script_snapshot_hash"), script["snapshot_hash"]):
            raise MediaRenderError("SOURCE_LINEAGE_MISMATCH", "visual asset set does not match script lineage")
        if storyboard is not None and (visual.get("media_storyboard_version_id") != storyboard["id"] or not _same_hash(visual.get("source_storyboard_snapshot_hash"), storyboard["snapshot_hash"])):
            raise MediaRenderError("SOURCE_LINEAGE_MISMATCH", "visual asset set does not match storyboard")
        output = self._version(tenant=tenant, value=output_version, version_id=media_output_spec_version_id, port=self.output_port, validator=OUTPUT_VALIDATOR, kind="output_spec_version")
        if output["media_visual_asset_set_version_id"] != visual["id"] or output["duration_seconds"] != visual["duration_seconds"] or output["region_profile_version_id"] != visual["region_profile_version_id"] or output["policy_snapshot_id"] != visual["policy_snapshot_id"] or not _same_hash(output.get("source_visual_snapshot_hash"), visual["snapshot_hash"]) or not _same_hash(output.get("source_script_snapshot_hash"), script["snapshot_hash"]):
            raise MediaRenderError("SOURCE_LINEAGE_MISMATCH", "output spec does not match visual asset set")
        if (output.get("source_storyboard_snapshot_hash") is None) != (storyboard is None) or (storyboard is not None and not _same_hash(output.get("source_storyboard_snapshot_hash"), storyboard["snapshot_hash"])):
            raise MediaRenderError("SOURCE_LINEAGE_MISMATCH", "output spec does not match storyboard lineage")
        profile = next((item for item in output["profiles"] if item["profile_key"] == profile_key), None)
        if profile is None:
            raise MediaRenderError("OUTPUT_PROFILE_NOT_FOUND", "selected output profile is absent")
        asset = None
        if asset_version is not None or asset_version_id is not None:
            asset = self._version(tenant=tenant, value=asset_version, version_id=asset_version_id, port=self.asset_port, validator=ASSET_VALIDATOR, kind="asset_version", unusable={"withdrawn", "blocked"})
            if asset["variant_version_id"] != script["variant_version_id"] or asset["region_profile_version_id"] != script["region_profile_version_id"] or asset.get("policy_snapshot_id") != script.get("policy_snapshot_id"):
                raise MediaRenderError("ASSET_LINEAGE_MISMATCH", "target AssetVersion does not match script")
            if asset.get("media_type") != "video" or asset.get("aspect_ratio") != profile["aspect_ratio"]:
                raise MediaRenderError("ASSET_OUTPUT_MISMATCH", "target AssetVersion does not match output profile")
        if profile.get("subtitle_track_ids") and subtitle is None:
            raise MediaRenderError("SUBTITLE_VERSION_REQUIRED", "selected profile requires a subtitle version")
        return script, storyboard, subtitle, visual, output, profile if asset is None else {**profile, "target_asset": asset}

    def _job_material(self, *, script: Mapping[str, Any], storyboard: Mapping[str, Any] | None, subtitle: Mapping[str, Any] | None,
                      visual: Mapping[str, Any], output: Mapping[str, Any], profile: Mapping[str, Any], asset: Mapping[str, Any] | None) -> dict[str, Any]:
        return {"script": [script["id"], script["snapshot_hash"]], "storyboard": None if storyboard is None else [storyboard["id"], storyboard["snapshot_hash"]],
                "subtitle": None if subtitle is None else [subtitle["id"], subtitle["snapshot_hash"]], "visual": [visual["id"], visual["snapshot_hash"]],
                "output": [output["id"], output["snapshot_hash"]], "profile": profile["profile_key"], "profile_snapshot": profile,
                "asset": None if asset is None else [asset["id"], asset.get("file_hash"), asset.get("version_no")], "template": TEMPLATE_VERSION}

    @_audit_failures
    def create_render_job(self, *, script_version: Any | None = None, media_script_version_id: Any | None = None,
                          storyboard_version: Any | None = None, media_storyboard_version_id: Any | None = None,
                          subtitle_version: Any | None = None, media_subtitle_version_id: Any | None = None,
                          visual_asset_set_version: Any | None = None, media_visual_asset_set_version_id: Any | None = None,
                          output_spec_version: Any | None = None, media_output_spec_version_id: Any | None = None,
                          asset_version: Any | None = None, asset_version_id: Any | None = None, profile_key: str,
                          org_id: Any = None, tenant_context: Any = None, actor_id: Any = None,
                          trace_id: str = "media-render-create", idempotency_key: str, created_at: Any | None = None) -> dict[str, Any]:
        tenant, actor = _context(org_id=org_id, actor_id=actor_id, tenant_context=tenant_context)
        trace, key = _text(trace_id, "trace_id", 256), _text(idempotency_key, "idempotency_key", 200)
        selected_profile = _text(profile_key, "profile_key", 64, code="OUTPUT_PROFILE_INVALID")
        script, storyboard, subtitle, visual, output, profile_with_asset = self._inputs(
            tenant=tenant, script_version=script_version, media_script_version_id=media_script_version_id,
            storyboard_version=storyboard_version, media_storyboard_version_id=media_storyboard_version_id,
            subtitle_version=subtitle_version, media_subtitle_version_id=media_subtitle_version_id,
            visual_version=visual_asset_set_version, media_visual_asset_set_version_id=media_visual_asset_set_version_id,
            output_version=output_spec_version, media_output_spec_version_id=media_output_spec_version_id,
            asset_version=asset_version, asset_version_id=asset_version_id, profile_key=selected_profile)
        target_asset = profile_with_asset.pop("target_asset", None)
        material = self._job_material(script=script, storyboard=storyboard, subtitle=subtitle, visual=visual, output=output, profile=profile_with_asset, asset=target_asset)
        input_hash = _hash(material)
        replay = self.store.replay(org_id=tenant, namespace="create", key=key, request_hash=input_hash)
        if replay is not None:
            return replay
        at = self._now(created_at, "created_at")
        job_id = str(uuid5(JOB_NAMESPACE, f"{tenant}:{input_hash}"))
        target_id = target_asset["id"] if target_asset else str(uuid5(ASSET_NAMESPACE, f"{job_id}:{selected_profile}"))
        hashes = {"script": str(script["snapshot_hash"]).lower(), "storyboard": None if storyboard is None else str(storyboard["snapshot_hash"]).lower(), "subtitle": None if subtitle is None else str(subtitle["snapshot_hash"]).lower(), "visual_asset_set": str(visual["snapshot_hash"]).lower(), "output_spec": str(output["snapshot_hash"]).lower(), "asset_version": None if target_asset is None else str(target_asset["file_hash"]).lower()}
        stamp = _stamp(at)
        job = {"id": job_id, "org_id": tenant, "asset_version_id": target_id, "asset_version_no": None if target_asset is None else target_asset["version_no"], "media_script_version_id": script["id"], "media_storyboard_version_id": None if storyboard is None else storyboard["id"], "media_subtitle_version_id": None if subtitle is None else subtitle["id"], "media_visual_asset_set_version_id": visual["id"], "media_output_spec_version_id": output["id"], "output_profile_key": selected_profile, "output_profile": deepcopy(profile_with_asset), "duration_seconds": script["duration_seconds"], "region_profile_version_id": script["region_profile_version_id"], "policy_snapshot_id": script["policy_snapshot_id"], "status": "planned", "input_hash": input_hash, "attempt_count": 0, "max_attempts": 3, "next_retry_at": None, "last_failure_id": None, "failure_count": 0, "dead_letter_reason": None, "input_snapshot_hashes": hashes, "artifacts": [], "artifact_count": 0, "trace_id": trace, "failure_code": None, "created_by": actor, "created_at": stamp, "updated_at": stamp}
        job["output_profile"].pop("target_asset", None)
        _schema(JOB_VALIDATOR, job, "INVALID_RENDER_JOB")
        response = {"render_job": job}
        return self.store.create(job=job, namespace="create", key=key, request_hash=input_hash, response=response, audit={"operation": "create_render_job", "org_id": tenant, "job_id": job_id, "input_hash": input_hash, "status": "planned", "actor_id": actor, "trace_id": trace, "created_at": stamp})

    def _renderer_result(self, job: Mapping[str, Any], *, expected_stage: str | None = None,
                         expected_shot_sequence: int | None = None) -> dict[str, Any]:
        try:
            if hasattr(self.renderer, "render"):
                raw = self.renderer.render(job, profile=job["output_profile"])
            elif callable(self.renderer):
                raw = self.renderer(job)
            else:
                raise TypeError("renderer has no render operation")
        except MediaRenderError:
            raise
        except Exception as exc:
            raise MediaRenderError("RENDER_RESULT_UNKNOWN", "renderer result is unknown") from exc
        if isinstance(raw, bytes):
            raw = {"content": raw}
        if not isinstance(raw, Mapping) or not isinstance(raw.get("content"), bytes):
            raise MediaRenderError("RENDER_OUTPUT_INVALID", "renderer must return bytes content")
        content = raw["content"]
        result = _safe({key: value for key, value in raw.items() if key != "content"})
        _reject_sensitive(result)
        stage = _text(result.get("stage", "full"), "stage", 64, code="RENDER_OUTPUT_INVALID")
        shot = result.get("shot_sequence")
        if shot is not None and (type(shot) is not int or shot < 1):
            raise MediaRenderError("RENDER_OUTPUT_INVALID", "shot_sequence is invalid")
        if expected_stage is not None:
            expected_stage = _text(expected_stage, "stage", 64, code="RENDER_OUTPUT_INVALID")
            # A renderer that returns its normal full-scope defaults is allowed
            # to serve a shot request; the requested scope is the authoritative
            # natural key.  An explicitly different scope is a deterministic
            # contract violation.
            if stage not in {"full", expected_stage}:
                raise MediaRenderError("RENDER_OUTPUT_SCOPE_MISMATCH", "renderer returned a different stage")
            stage = expected_stage
        if expected_shot_sequence is not None:
            if shot not in {None, expected_shot_sequence}:
                raise MediaRenderError("RENDER_OUTPUT_SCOPE_MISMATCH", "renderer returned a different shot")
            shot = expected_shot_sequence
        content_type = _text(result.get("content_type", "application/octet-stream"), "content_type", 128, code="RENDER_OUTPUT_INVALID")
        return {"content": raw["content"], "stage": stage, "shot_sequence": shot, "content_type": content_type}

    @_audit_failures
    def execute_render_job(self, *, media_render_job_id: Any, org_id: Any = None, tenant_context: Any = None,
                           actor_id: Any = None, trace_id: str = "media-render-execute", executed_at: Any | None = None,
                           allow_retry: bool = False) -> dict[str, Any]:
        tenant, actor = _context(org_id=org_id, actor_id=actor_id, tenant_context=tenant_context)
        trace = _text(trace_id, "trace_id", 256)
        job_id = _uuid(media_render_job_id, "media_render_job_id")
        stamp = _stamp(self._now(executed_at, "executed_at"))
        job = self.store.claim_running(org_id=tenant, job_id=job_id, stamp=stamp, allow_retry=allow_retry)
        if job["status"] == "succeeded":
            return {"render_job": job, "artifacts": job["artifacts"]}
        # A worker can lose the database confirmation after the private object
        # has already been written.  Confirm that stable object before asking a
        # renderer to produce bytes again.
        try:
            recovered = self._recover_pending_artifact(tenant=tenant, job=job, stamp=stamp)
        except MediaRenderError as exc:
            job["status"] = "unknown" if exc.code == "RENDER_RESULT_UNKNOWN" else "failed"
            job["failure_code"] = exc.code
            job["updated_at"] = stamp
            self.store.save(org_id=tenant, job=job)
            self.store.audit.append({"operation": "execute_render_job", "org_id": tenant, "job_id": job_id,
                                     "input_hash": job["input_hash"], "status": job["status"], "error_code": exc.code,
                                     "actor_id": actor, "trace_id": trace, "created_at": stamp})
            raise
        if recovered is not None:
            return recovered
        started_payload = {"aggregate_id": job_id, "aggregate_version": max(1, int(job["attempt_count"])), "input_hash": job["input_hash"], "profile_key": job["output_profile_key"]}
        self.store.outbox.append({"event_id": str(uuid5(JOB_NAMESPACE, f"media-render-started:{job_id}:{job['attempt_count']}")), "event_type": "asset.render_started", "event_schema_version": 1, "org_id": tenant, "aggregate_id": job_id, "aggregate_type": "AssetVersion", "aggregate_version": job["attempt_count"], "trace_id": trace, "actor_type": "service", "actor_id": actor, "idempotency_key": f"render:{job_id}:{job['attempt_count']}", "occurred_at": stamp, "payload": started_payload, "payload_hash": _hash(started_payload)})
        try:
            result = self._renderer_result(job)
            object_key = f"render/{job_id}/{job['output_profile_key']}/{result['stage']}/{result['shot_sequence'] or 'full'}.bin"
            try:
                stored = self.storage.put(tenant, object_key, result["content"], content_type=result["content_type"], metadata={"input_hash": job["input_hash"], "stage": result["stage"]}, idempotency_key=f"render:{job_id}:{result['stage']}:{result['shot_sequence'] or 'full'}")
                # Persist only non-sensitive recovery metadata.  The bytes stay
                # in StoragePort and are never copied into the job projection.
                job["pending_storage_object_ref"] = stored.storage_object_ref
                job["pending_object_key"] = object_key
                job["pending_stage"] = result["stage"]
                job["pending_shot_sequence"] = result["shot_sequence"]
                job["pending_content_type"] = result["content_type"]
                job["updated_at"] = stamp
                self.store.save(org_id=tenant, job=job)
                head = self.storage.head(tenant, stored.storage_object_ref)
                body = self.storage.get(tenant, stored.storage_object_ref)
            except Exception as exc:
                raise MediaRenderError("RENDER_RESULT_UNKNOWN", "intermediate artifact confirmation failed") from exc
            body_hash = _bytes_hash(body)
            if getattr(head, "org_id", tenant) != tenant or head.storage_object_ref != stored.storage_object_ref or head.access_policy != "private" or head.content_hash.lower() != body_hash or head.size_bytes != len(body) or head.content_type != result["content_type"]:
                raise MediaRenderError("ARTIFACT_VERIFICATION_FAILED", "stored artifact failed hash verification")
            artifact = {"id": str(uuid5(JOB_NAMESPACE, f"{job_id}:{object_key}")), "sequence": len(job["artifacts"]) + 1, "stage": result["stage"], "shot_sequence": result["shot_sequence"], "output_profile_key": job["output_profile_key"], "storage_object_ref": stored.storage_object_ref, "content_hash": body_hash, "size_bytes": len(body), "content_type": head.content_type, "input_hash": job["input_hash"], "created_at": stamp}
            _schema(JOB_VALIDATOR, {**job, "artifacts": [*job["artifacts"], artifact], "artifact_count": len(job["artifacts"]) + 1, "status": "succeeded"}, "INVALID_RENDER_JOB")
            artifact = self.store.add_artifact(org_id=tenant, job_id=job_id, artifact=artifact)
            job["artifacts"] = [*job["artifacts"], artifact]; job["artifact_count"] = len(job["artifacts"]); job["status"] = "succeeded"; job["failure_code"] = None; job["next_retry_at"] = None; job["last_failure_id"] = None; job["dead_letter_reason"] = None; job["updated_at"] = stamp
            for field in ("pending_storage_object_ref", "pending_object_key", "pending_stage", "pending_shot_sequence", "pending_content_type"):
                job.pop(field, None)
            self.store.save(org_id=tenant, job=job)
            self.store.audit.append({"operation": "execute_render_job", "org_id": tenant, "job_id": job_id, "input_hash": job["input_hash"], "output_hash": body_hash, "status": "succeeded", "actor_id": actor, "trace_id": trace, "created_at": stamp})
            return {"render_job": deepcopy(job), "artifacts": deepcopy(job["artifacts"])}
        except MediaRenderError as exc:
            job["status"] = "unknown" if exc.code == "RENDER_RESULT_UNKNOWN" else "failed"; job["failure_code"] = exc.code; job["updated_at"] = stamp
            self.store.save(org_id=tenant, job=job)
            self.store.audit.append({"operation": "execute_render_job", "org_id": tenant, "job_id": job_id, "input_hash": job["input_hash"], "status": job["status"], "error_code": exc.code, "actor_id": actor, "trace_id": trace, "created_at": stamp})
            raise
        except Exception as exc:
            job["status"], job["failure_code"], job["updated_at"] = "unknown", "RENDER_RESULT_UNKNOWN", stamp
            self.store.save(org_id=tenant, job=job)
            self.store.audit.append({"operation": "execute_render_job", "org_id": tenant, "job_id": job_id, "input_hash": job["input_hash"], "status": "unknown", "error_code": "RENDER_RESULT_UNKNOWN", "actor_id": actor, "trace_id": trace, "created_at": stamp})
            raise MediaRenderError("RENDER_RESULT_UNKNOWN", "render result is unknown") from exc

    def _recover_pending_artifact(self, *, tenant: str, job: Mapping[str, Any], stamp: str) -> dict[str, Any] | None:
        ref = job.get("pending_storage_object_ref")
        if not ref:
            return None
        try:
            head = self.storage.head(tenant, str(ref))
            body = self.storage.get(tenant, str(ref))
            body_hash = _bytes_hash(body)
            stage = _text(job.get("pending_stage", "full"), "pending_stage", 64, code="ARTIFACT_VERIFICATION_FAILED")
            shot = job.get("pending_shot_sequence")
            if shot is not None and (type(shot) is not int or shot < 1):
                raise MediaRenderError("ARTIFACT_VERIFICATION_FAILED", "pending shot is invalid")
            content_type = _text(job.get("pending_content_type", getattr(head, "content_type", "application/octet-stream")), "content_type", 128, code="ARTIFACT_VERIFICATION_FAILED")
            if getattr(head, "org_id", tenant) != tenant or head.storage_object_ref != ref or head.access_policy != "private" or head.content_hash.lower() != body_hash or head.size_bytes != len(body) or head.content_type != content_type:
                raise MediaRenderError("ARTIFACT_VERIFICATION_FAILED", "pending artifact failed hash verification")
            artifact = {"id": str(uuid5(JOB_NAMESPACE, f"{job['id']}:{job.get('pending_object_key', ref)}")), "sequence": len(job.get("artifacts", [])) + 1, "stage": stage, "shot_sequence": shot, "output_profile_key": job["output_profile_key"], "storage_object_ref": ref, "content_hash": body_hash, "size_bytes": len(body), "content_type": head.content_type, "input_hash": job["input_hash"], "created_at": stamp}
            _schema(JOB_VALIDATOR, {**dict(job), "artifacts": [*job.get("artifacts", []), artifact], "artifact_count": len(job.get("artifacts", [])) + 1, "status": "succeeded"}, "INVALID_RENDER_JOB")
            confirmed = self.store.add_artifact(org_id=tenant, job_id=str(job["id"]), artifact=artifact)
            updated = deepcopy(dict(job))
            updated["artifacts"] = [*updated.get("artifacts", []), confirmed]
            updated["artifact_count"] = len(updated["artifacts"])
            updated["status"] = "succeeded"
            updated["failure_code"] = None
            updated["next_retry_at"] = None
            updated["updated_at"] = stamp
            for field in ("pending_storage_object_ref", "pending_object_key", "pending_stage", "pending_shot_sequence", "pending_content_type"):
                updated.pop(field, None)
            self.store.save(org_id=tenant, job=updated)
            return {"render_job": deepcopy(updated), "artifacts": deepcopy(updated["artifacts"]), "recovered": True}
        except MediaRenderError:
            raise
        except Exception:
            # The object may have expired or confirmation may still be
            # unavailable.  The normal execution path records an unknown
            # outcome and the retry service decides what happens next.
            return None

    def worker_handler(self, task_job: Any, context: Any) -> None:
        job_id = getattr(task_job, "aggregate_id", None) or getattr(task_job, "id", None)
        org_id = getattr(task_job, "org_id", None)
        if hasattr(context, "checkpoint"):
            context.checkpoint()
        self.execute_render_job(media_render_job_id=job_id, org_id=org_id, actor_id=None, trace_id=getattr(task_job, "trace_id", "media-render-worker"))
        if hasattr(context, "checkpoint"):
            context.checkpoint()

    # MEDIA-004B commands live in a separate module to keep the 004A renderer
    # boundary small, while these lazy delegates keep the public service
    # ergonomic for existing Worker integrations.
    def retry_service(self) -> Any:
        from .render_retry_service import MediaRenderRetryService
        return MediaRenderRetryService(self)

    def record_failure(self, **kwargs: Any) -> dict[str, Any]:
        return self.retry_service().record_failure(**kwargs)

    record_render_failure = record_failure

    def retry_due(self, **kwargs: Any) -> dict[str, Any] | list[dict[str, Any]]:
        return self.retry_service().retry_due(**kwargs)

    retry_render_job = retry_due
    retry = retry_due

    def rerender_shot(self, **kwargs: Any) -> dict[str, Any]:
        return self.retry_service().rerender_shot(**kwargs)

    rerender_single_shot = rerender_shot
    rerender = rerender_shot

    def dead_letter(self, **kwargs: Any) -> dict[str, Any]:
        return self.retry_service().dead_letter(**kwargs)

    mark_dead_letter = dead_letter
    dead_letter_render_job = dead_letter

    def resolve_unknown(self, **kwargs: Any) -> dict[str, Any]:
        return self.retry_service().resolve_unknown(**kwargs)

    resolve = resolve_unknown

    def get_job(self, *, media_render_job_id: Any, org_id: Any = None, tenant_context: Any = None) -> dict[str, Any]:
        tenant, _ = _context(org_id=org_id, actor_id=None, tenant_context=tenant_context)
        return self.store.get(org_id=tenant, job_id=_uuid(media_render_job_id, "media_render_job_id"))


RenderJobService = MediaRenderService
MediaRenderJobService = MediaRenderService
MediaRenderJobStore = InMemoryMediaRenderStore


__all__ = ["FakeRenderer", "InMemoryMediaRenderStore", "InMemoryPrivateStorage", "MediaRenderError", "MediaRenderJobService", "MediaRenderService", "MediaRenderJobStore", "RenderJobService", "RendererPort", "StoragePort", "VersionPort"]
