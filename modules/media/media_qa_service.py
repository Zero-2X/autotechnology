"""Deterministic visual, audio, subtitle and file integrity QA for media renders.

The service deliberately treats media inspection as a port.  It can therefore be
run in CI with fixed probe facts and a private in-memory object store while a
deployment supplies an ffprobe-like adapter later.  No media bytes are retained
in reports or audit records.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from hashlib import sha256
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Protocol, Sequence
from uuid import UUID, uuid4, uuid5

from jsonschema import Draft202012Validator, FormatChecker

from .render_service import InMemoryPrivateStorage, StoragePort


ROOT = Path(__file__).resolve().parents[2]
QA_SCHEMA = json.loads((ROOT / "packages/contracts/jsonschema/qa-report.schema.json").read_text(encoding="utf-8"))
QA_VALIDATOR = Draft202012Validator(QA_SCHEMA, format_checker=FormatChecker())
SYSTEM_ACTOR = UUID("00000000-0000-4000-8000-000000000001")
EVENT_NAMESPACE = UUID("4b9e1c7c-9a52-5a70-8bd0-6c41d8a8f7d1")
HASH_RE = "^[A-Fa-f0-9]{64}$"
SENSITIVE_KEYS = frozenset({
    "model", "provider", "credential", "token", "secret", "password", "authorization", "api_key", "raw_output",
})
CHECKS = ("visual", "audio", "subtitle", "file_hash")


class MediaQAError(ValueError):
    """Stable, non-sensitive MEDIA-005A error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class MediaProbePort(Protocol):
    def probe(self, org_id: str, storage_object_ref: str, *, artifact: Mapping[str, Any], profile: Mapping[str, Any]) -> Mapping[str, Any]: ...


class QAStoragePort(StoragePort, Protocol):
    pass


def _hash(value: Any) -> str:
    try:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise MediaQAError("INVALID_QA_INPUT", "QA input must be JSON serializable") from exc
    return sha256(payload.encode("utf-8")).hexdigest()


def _bytes_hash(value: bytes) -> str:
    return sha256(value).hexdigest()


def _uuid(value: Any, field: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise MediaQAError("INVALID_QA_INPUT", f"{field} must be a UUID") from exc


def _stamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise MediaQAError("INVALID_QA_INPUT", "evaluated_at must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _time(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise MediaQAError("INVALID_QA_INPUT", f"{field} must be ISO-8601") from exc
    else:
        raise MediaQAError("INVALID_QA_INPUT", f"{field} must be ISO-8601")
    if parsed.tzinfo is None:
        raise MediaQAError("INVALID_QA_INPUT", f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _text(value: Any, field: str, maximum: int = 256) -> str:
    if not isinstance(value, str):
        raise MediaQAError("INVALID_QA_INPUT", f"{field} must be text")
    result = value.strip()
    if not result or len(result) > maximum or any(ord(c) < 0x20 and c not in "\t\n\r" for c in result):
        raise MediaQAError("INVALID_QA_INPUT", f"{field} has an invalid value")
    return result


def _value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _context(*, org_id: Any, actor_id: Any, tenant_context: Any) -> tuple[str, str]:
    context_org = context_actor = None
    if tenant_context is not None:
        if isinstance(tenant_context, Mapping):
            context_org = tenant_context.get("org_id") or tenant_context.get("tenant_id")
            context_actor = tenant_context.get("actor_id") or tenant_context.get("user_id")
        else:
            context_org = getattr(tenant_context, "org_id", None) or getattr(tenant_context, "tenant_id", None)
            context_actor = getattr(tenant_context, "actor_id", None) or getattr(tenant_context, "user_id", None)
    supplied_org = _uuid(org_id, "org_id") if org_id is not None else None
    supplied_actor = _uuid(actor_id, "actor_id") if actor_id is not None else None
    resolved_org = _uuid(context_org, "tenant_context.org_id") if context_org is not None else supplied_org
    resolved_actor = _uuid(context_actor, "tenant_context.actor_id") if context_actor is not None else supplied_actor
    if resolved_org is None:
        raise MediaQAError("INVALID_QA_CONTEXT", "org_id is required")
    if supplied_org is not None and resolved_org != supplied_org:
        raise MediaQAError("TENANT_SCOPE_VIOLATION", "tenant context and org_id differ")
    if supplied_actor is not None and context_actor is not None and resolved_actor != supplied_actor:
        raise MediaQAError("TENANT_SCOPE_VIOLATION", "tenant context and actor_id differ")
    return resolved_org, resolved_actor or str(SYSTEM_ACTOR)


def _safe(value: Any, *, allow_bytes: bool = False) -> Any:
    """Return a JSON-safe, secret-free projection."""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return _stamp(value)
    if isinstance(value, bytes):
        if allow_bytes:
            return value
        return {"byte_count": len(value), "sha256": _bytes_hash(value)}
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_KEYS:
                raise MediaQAError("SENSITIVE_INPUT_REJECTED", "QA input contains a restricted field")
            result[str(key)] = _safe(item, allow_bytes=allow_bytes)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_safe(item, allow_bytes=allow_bytes) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise MediaQAError("INVALID_QA_INPUT", "QA input contains a non-JSON value")


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MediaQAError("INVALID_QA_INPUT", f"{field} must be an object")
    return deepcopy(dict(value))


def _object_projection(value: Any, field: str, fields: Sequence[str]) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return deepcopy(dict(value))
    result = {name: getattr(value, name) for name in fields if hasattr(value, name)}
    if not result:
        raise MediaQAError("INVALID_QA_INPUT", f"{field} must be an object projection")
    return result


def _storage_call(storage: Any, operation: str, org_id: str, ref: str) -> Any:
    method = getattr(storage, operation, None)
    if method is None:
        raise MediaQAError("FILE_STORAGE_UNAVAILABLE", f"storage does not implement {operation}")
    try:
        return method(org_id, ref)
    except TypeError:
        try:
            return method(ref, org_id=org_id)
        except TypeError:
            return method(storage_object_ref=ref, org_id=org_id)


def _private_ref(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("private://") and len(value) <= 512


def _number(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _same_number(actual: Any, expected: Any, tolerance: float = 0.0) -> bool:
    a, e = _number(actual), _number(expected)
    return a is not None and e is not None and abs(float(a) - float(e)) <= tolerance


class FakeMediaProbe:
    """Deterministic probe used by unit and acceptance tests."""

    def __init__(self, facts: Mapping[str, Mapping[str, Any]] | None = None, *, default: Mapping[str, Any] | None = None) -> None:
        self.facts = {str(key): deepcopy(dict(value)) for key, value in (facts or {}).items()}
        self.default = deepcopy(dict(default)) if default is not None else None
        self.calls: list[dict[str, Any]] = []

    def probe(self, org_id: str, storage_object_ref: str, *, artifact: Mapping[str, Any], profile: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append({"org_id": org_id, "storage_object_ref": storage_object_ref, "artifact_id": artifact.get("id")})
        for key in (storage_object_ref, str(artifact.get("id"))):
            if key in self.facts:
                return deepcopy(self.facts[key])
        if isinstance(artifact.get("probe"), Mapping):
            return deepcopy(dict(artifact["probe"]))
        if isinstance(artifact.get("probe_facts"), Mapping):
            return deepcopy(dict(artifact["probe_facts"]))
        if self.default is not None:
            return deepcopy(self.default)
        raise MediaQAError("MEDIA_PROBE_UNAVAILABLE", "media probe facts are unavailable")


class InMemoryMediaQAStore:
    """Account-free append-only projection used by the service and tests."""

    def __init__(self) -> None:
        self.reports: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
        self.commands = self.reports
        self.findings: dict[tuple[str, str, int], dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self.outbox: list[dict[str, Any]] = []
        self._lock = RLock()

    @property
    def audit_log(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(deepcopy(self.audit))

    @property
    def outbox_events(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(deepcopy(self.outbox))

    def replay(self, *, org_id: str, namespace: str, key: str, request_hash: str) -> dict[str, Any] | None:
        with self._lock:
            prior = self.reports.get((str(org_id), f"{namespace}:{key}"))
            if prior is None:
                return None
            if prior[0] != request_hash:
                raise MediaQAError("IDEMPOTENCY_KEY_REUSED", "QA command payload differs from prior request")
            return deepcopy(prior[1])

    def save(self, *, org_id: str, namespace: str, key: str, request_hash: str,
             report: Mapping[str, Any], findings: Sequence[Mapping[str, Any]], audit: Mapping[str, Any],
             event: Mapping[str, Any]) -> dict[str, Any]:
        identity = (str(org_id), f"{namespace}:{key}")
        with self._lock:
            prior = self.reports.get(identity)
            if prior is not None:
                if prior[0] != request_hash:
                    raise MediaQAError("IDEMPOTENCY_KEY_REUSED", "QA command payload differs from prior request")
                return deepcopy(prior[1])
            result = deepcopy(dict(report))
            self.reports[identity] = (request_hash, result)
            for sequence, finding in enumerate(findings, 1):
                self.findings[(str(org_id), str(report["id"]), sequence)] = {
                    "org_id": str(org_id), "report_id": str(report["id"]), "sequence": sequence,
                    **deepcopy(dict(finding)),
                }
            self.audit.append(deepcopy(dict(audit)))
            self.outbox.append(deepcopy(dict(event)))
            return deepcopy(result)


class MediaAssetQAService:
    """Run MEDIA-005A checks over immutable RenderJob and artifact projections."""

    rule_version = "media-005a/v1"

    def __init__(self, *, render_service: Any | None = None, storage: QAStoragePort | None = None,
                 storage_port: QAStoragePort | None = None,
                 probe: MediaProbePort | Any | None = None, media_probe: MediaProbePort | Any | None = None,
                 probe_port: MediaProbePort | Any | None = None,
                 store: InMemoryMediaQAStore | None = None, subtitle_port: Any | None = None,
                 clock: Any | None = None) -> None:
        self.render_service = render_service
        self.storage = storage or storage_port or (getattr(render_service, "storage", None) if render_service is not None else None) or InMemoryPrivateStorage()
        self.probe = probe or media_probe or probe_port or FakeMediaProbe()
        self.store = store or InMemoryMediaQAStore()
        self.subtitle_port = subtitle_port
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def audit_log(self) -> tuple[dict[str, Any], ...]:
        return self.store.audit_log

    @property
    def outbox_events(self) -> tuple[dict[str, Any], ...]:
        return self.store.outbox_events

    def _load_job(self, *, org_id: str, media_render_job_id: Any, render_job: Any | None) -> dict[str, Any]:
        if render_job is not None:
            job = _mapping(render_job, "render_job")
        elif self.render_service is not None:
            try:
                if hasattr(self.render_service, "get_job"):
                    job = _mapping(self.render_service.get_job(media_render_job_id=media_render_job_id, org_id=org_id), "render_job")
                else:
                    job = _mapping(self.render_service.store.get(org_id=org_id, job_id=str(media_render_job_id)), "render_job")
            except Exception as exc:
                code = getattr(exc, "code", None) or ("TENANT_SCOPE_VIOLATION" if "tenant" in str(exc).lower() else "RENDER_JOB_NOT_FOUND")
                raise MediaQAError(code, "render job is unavailable") from exc
        else:
            raise MediaQAError("INVALID_QA_INPUT", "render_job or render_service is required")
        job_org = _uuid(job.get("org_id"), "render_job.org_id")
        job_id = _uuid(job.get("id") or media_render_job_id, "render_job.id")
        if job_org != org_id:
            raise MediaQAError("TENANT_SCOPE_VIOLATION", "render job is outside this organization")
        if media_render_job_id is not None and _uuid(media_render_job_id, "media_render_job_id") != job_id:
            raise MediaQAError("QA_SOURCE_MISMATCH", "render job id does not match projection")
        job["id"], job["org_id"] = job_id, job_org
        return job

    def _load_subtitle(self, *, org_id: str, job: Mapping[str, Any], subtitle_version: Any | None) -> dict[str, Any] | None:
        subtitle_id = job.get("media_subtitle_version_id")
        if subtitle_version is not None:
            result = _mapping(subtitle_version, "subtitle_version")
        elif subtitle_id is not None and self.subtitle_port is not None:
            try:
                getter = getattr(self.subtitle_port, "get_version", None) or getattr(self.subtitle_port, "get", None)
                result = _mapping(getter(org_id=org_id, version_id=str(subtitle_id)), "subtitle_version") if getter else None
            except Exception:
                result = None
        else:
            result = None
        if result is None:
            return None
        if _uuid(result.get("org_id"), "subtitle_version.org_id") != org_id:
            raise MediaQAError("TENANT_SCOPE_VIOLATION", "subtitle version is outside this organization")
        if subtitle_id is not None and _uuid(result.get("id"), "subtitle_version.id") != _uuid(subtitle_id, "media_subtitle_version_id"):
            raise MediaQAError("QA_SOURCE_MISMATCH", "subtitle version does not match render job")
        expected_hash = _value(job.get("input_snapshot_hashes"), "subtitle")
        if expected_hash is not None and result.get("snapshot_hash") != expected_hash:
            raise MediaQAError("QA_SOURCE_MISMATCH", "subtitle snapshot hash does not match render job")
        return result

    def _artifacts(self, *, org_id: str, job: Mapping[str, Any], artifacts: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
        raw = list(artifacts if artifacts is not None else (job.get("artifacts") or ()))
        if artifacts is None and not raw and self.render_service is not None:
            render_store = getattr(self.render_service, "store", None)
            if render_store is not None:
                raw = [item for item in getattr(render_store, "artifacts", {}).values()
                       if isinstance(item, Mapping) and item.get("org_id") == org_id and item.get("render_job_id") == job["id"]]
        result: list[dict[str, Any]] = []
        for index, item in enumerate(raw):
            artifact = _mapping(item, f"artifacts[{index}]")
            artifact_org = artifact.get("org_id", org_id)
            if _uuid(artifact_org, f"artifacts[{index}].org_id") != org_id:
                raise MediaQAError("TENANT_SCOPE_VIOLATION", "artifact is outside this organization")
            if artifact.get("render_job_id") is not None and _uuid(artifact["render_job_id"], f"artifacts[{index}].render_job_id") != job["id"]:
                raise MediaQAError("QA_SOURCE_MISMATCH", "artifact references a different render job")
            artifact["id"] = _uuid(artifact.get("id"), f"artifacts[{index}].id")
            artifact["org_id"] = org_id
            result.append(artifact)
        return sorted(result, key=lambda item: (int(item.get("sequence", 0) or 0), item["id"]))

    def _probe(self, *, org_id: str, artifact: Mapping[str, Any], profile: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        try:
            if hasattr(self.probe, "probe"):
                method = self.probe.probe
                try:
                    value = method(org_id, str(artifact.get("storage_object_ref")), artifact=artifact, profile=profile)
                except TypeError:
                    try:
                        value = method(storage_object_ref=str(artifact.get("storage_object_ref")), artifact=artifact, profile=profile)
                    except TypeError:
                        value = method(str(artifact.get("storage_object_ref")))
            elif hasattr(self.probe, "inspect"):
                method = self.probe.inspect
                try:
                    value = method(org_id, str(artifact.get("storage_object_ref")), artifact=artifact, profile=profile)
                except TypeError:
                    value = method(str(artifact.get("storage_object_ref")))
            elif callable(self.probe):
                value = self.probe(org_id, str(artifact.get("storage_object_ref")), artifact=artifact, profile=profile)
            else:
                raise MediaQAError("MEDIA_PROBE_UNAVAILABLE", "media probe is not callable")
            if not isinstance(value, Mapping) or value.get("status") in {"unknown", "unavailable"}:
                return None, "MEDIA_PROBE_UNAVAILABLE"
            return _mapping(value, "probe_result"), None
        except MediaQAError as exc:
            return None, exc.code
        except Exception:
            return None, "MEDIA_PROBE_UNAVAILABLE"

    @staticmethod
    def _find(findings: list[dict[str, Any]], *, check: str, code: str, severity: str, path: str, message: str,
              observed: Any = None, expected: Any = None, artifact_id: str | None = None) -> None:
        item: dict[str, Any] = {
            "code": code, "severity": severity, "path": path, "message": message,
            "observed": _safe(observed), "expected": _safe(expected), "check": check,
        }
        if artifact_id is not None:
            item["artifact_id"] = artifact_id
        findings.append(item)

    @staticmethod
    def _category_status(findings: Sequence[Mapping[str, Any]], category: str) -> str:
        selected = [item for item in findings if item.get("check") == category]
        if any(item.get("severity") == "error" for item in selected):
            return "failed"
        if any(item.get("severity") == "warning" for item in selected):
            return "needs_review"
        return "passed"

    def _check_file(self, *, org_id: str, artifact: Mapping[str, Any], job: Mapping[str, Any], findings: list[dict[str, Any]]) -> None:
        artifact_id = str(artifact["id"])
        ref = artifact.get("storage_object_ref")
        if not _private_ref(ref):
            self._find(findings, check="file_hash", code="FILE_PRIVATE_REF_REQUIRED", severity="error",
                       path=f"/artifacts/{artifact_id}/storage_object_ref", message="media artifact must use a private storage reference", observed=ref, expected="private://...")
            return
        expected_hash = artifact.get("content_hash")
        expected_input = job.get("input_hash")
        if not isinstance(expected_hash, str) or len(expected_hash) != 64 or any(c not in "0123456789abcdefABCDEF" for c in expected_hash):
            self._find(findings, check="file_hash", code="FILE_HASH_INVALID", severity="error", path=f"/artifacts/{artifact_id}/content_hash", message="artifact content hash is invalid", observed=expected_hash, expected="sha256")
        if artifact.get("input_hash") != expected_input:
            self._find(findings, check="file_hash", code="FILE_INPUT_HASH_MISMATCH", severity="error", path=f"/artifacts/{artifact_id}/input_hash", message="artifact input hash differs from render job", observed=artifact.get("input_hash"), expected=expected_input, artifact_id=artifact_id)
        try:
            head_raw = _storage_call(self.storage, "head", org_id, str(ref))
            head = _object_projection(head_raw, "storage.head", ("storage_object_ref", "content_hash", "size_bytes", "content_type", "access_policy", "org_id"))
        except KeyError:
            self._find(findings, check="file_hash", code="FILE_OBJECT_MISSING", severity="error", path=f"/artifacts/{artifact_id}/storage_object_ref", message="private object was not found", observed=ref, expected="existing private object", artifact_id=artifact_id)
            return
        except Exception as exc:
            self._find(findings, check="file_hash", code="FILE_STORAGE_UNAVAILABLE", severity="warning", path=f"/artifacts/{artifact_id}/storage_object_ref", message="private object metadata could not be confirmed", observed=getattr(exc, "code", "unavailable"), expected="head succeeds", artifact_id=artifact_id)
            return
        if head.get("org_id") not in (None, org_id):
            self._find(findings, check="file_hash", code="TENANT_SCOPE_VIOLATION", severity="error", path=f"/artifacts/{artifact_id}/storage_object_ref", message="storage object belongs to another organization", observed=head.get("org_id"), expected=org_id, artifact_id=artifact_id)
        if head.get("access_policy") not in (None, "private"):
            self._find(findings, check="file_hash", code="FILE_PUBLIC_ACCESS_FORBIDDEN", severity="error", path=f"/artifacts/{artifact_id}/storage_object_ref", message="media object must remain private", observed=head.get("access_policy"), expected="private", artifact_id=artifact_id)
        for field in ("content_hash", "size_bytes", "content_type"):
            if head.get(field) != artifact.get(field):
                self._find(findings, check="file_hash", code="FILE_HEAD_MISMATCH", severity="error", path=f"/artifacts/{artifact_id}/{field}", message=f"storage head {field} differs from artifact fact", observed=head.get(field), expected=artifact.get(field), artifact_id=artifact_id)
        try:
            payload = _storage_call(self.storage, "get", org_id, str(ref))
            if not isinstance(payload, bytes):
                raise TypeError("storage get did not return bytes")
        except KeyError:
            self._find(findings, check="file_hash", code="FILE_OBJECT_MISSING", severity="error", path=f"/artifacts/{artifact_id}/storage_object_ref", message="private object was not found", observed=ref, expected="existing private object", artifact_id=artifact_id)
            return
        except Exception as exc:
            self._find(findings, check="file_hash", code="FILE_STORAGE_UNAVAILABLE", severity="warning", path=f"/artifacts/{artifact_id}/storage_object_ref", message="private object bytes could not be confirmed", observed=getattr(exc, "code", "unavailable"), expected="get succeeds", artifact_id=artifact_id)
            return
        actual_hash = _bytes_hash(payload)
        if not _same_number(len(payload), artifact.get("size_bytes")):
            self._find(findings, check="file_hash", code="FILE_SIZE_MISMATCH", severity="error", path=f"/artifacts/{artifact_id}/size_bytes", message="stored byte count differs from artifact fact", observed=len(payload), expected=artifact.get("size_bytes"), artifact_id=artifact_id)
        if isinstance(expected_hash, str) and actual_hash.lower() != expected_hash.lower():
            self._find(findings, check="file_hash", code="FILE_HASH_MISMATCH", severity="error", path=f"/artifacts/{artifact_id}/content_hash", message="stored bytes differ from artifact SHA-256", observed=actual_hash, expected=expected_hash, artifact_id=artifact_id)
        head_hash = head.get("content_hash")
        if isinstance(head_hash, str) and actual_hash.lower() != head_hash.lower():
            self._find(findings, check="file_hash", code="FILE_HEAD_GET_MISMATCH", severity="error", path=f"/artifacts/{artifact_id}/content_hash", message="storage head hash differs from fetched bytes", observed=actual_hash, expected=head_hash, artifact_id=artifact_id)

    def _check_visual_audio(self, *, artifact: Mapping[str, Any], profile: Mapping[str, Any], job: Mapping[str, Any], probe: Mapping[str, Any] | None, probe_error: str | None, findings: list[dict[str, Any]]) -> None:
        artifact_id = str(artifact["id"])
        if probe_error:
            self._find(findings, check="visual", code=probe_error, severity="warning", path=f"/artifacts/{artifact_id}/probe", message="visual and audio facts require human review because the media probe was unavailable", observed=probe_error, expected="probe facts")
            self._find(findings, check="audio", code=probe_error, severity="warning", path=f"/artifacts/{artifact_id}/probe/audio", message="audio facts require human review because the media probe was unavailable", observed=probe_error, expected="probe facts")
            return
        assert probe is not None
        video = probe.get("video") if isinstance(probe.get("video"), Mapping) else probe
        audio = probe.get("audio") if isinstance(probe.get("audio"), Mapping) else probe
        visual_fields = (
            ("container_format", ("container_format", "container", "format")),
            ("width", ("width",)), ("height", ("height",)), ("frame_rate", ("frame_rate", "fps")),
            ("video_codec", ("video_codec", "codec")), ("pixel_format", ("pixel_format",)),
            ("duration_seconds", ("duration_seconds", "duration")),
        )
        for expected_field, names in visual_fields:
            expected = profile.get(expected_field) if expected_field != "duration_seconds" else job.get("duration_seconds")
            actual = next((video.get(name) for name in names if video.get(name) is not None), None)
            if actual is None:
                self._find(findings, check="visual", code="MEDIA_PROBE_UNAVAILABLE", severity="warning", path=f"/artifacts/{artifact_id}/probe/{expected_field}", message="media probe did not return a required visual fact", observed=None, expected=expected, artifact_id=artifact_id)
            elif expected_field == "duration_seconds" and not _same_number(actual, expected, 0.25):
                self._find(findings, check="visual", code="VIDEO_DURATION_MISMATCH", severity="error", path=f"/artifacts/{artifact_id}/duration_seconds", message="video duration differs from render job", observed=actual, expected=expected, artifact_id=artifact_id)
            elif expected_field in {"width", "height", "frame_rate"} and not _same_number(actual, expected, 0.001):
                self._find(findings, check="visual", code="VIDEO_PROFILE_MISMATCH", severity="error", path=f"/artifacts/{artifact_id}/probe/{expected_field}", message="visual fact differs from output profile", observed=actual, expected=expected, artifact_id=artifact_id)
            elif expected_field not in {"duration_seconds", "width", "height", "frame_rate"} and str(actual).lower() != str(expected).lower():
                self._find(findings, check="visual", code="VIDEO_PROFILE_MISMATCH", severity="error", path=f"/artifacts/{artifact_id}/probe/{expected_field}", message="visual fact differs from output profile", observed=actual, expected=expected, artifact_id=artifact_id)
        width, height = video.get("width"), video.get("height")
        ratio = profile.get("aspect_ratio")
        if isinstance(width, (int, float)) and isinstance(height, (int, float)) and height:
            ratio_ok = ((ratio == "9:16" and float(width) * 16 == float(height) * 9) or
                        (ratio == "1:1" and float(width) == float(height)) or
                        (ratio == "16:9" and float(width) * 9 == float(height) * 16))
            if not ratio_ok:
                self._find(findings, check="visual", code="VIDEO_ASPECT_RATIO_MISMATCH", severity="error", path=f"/artifacts/{artifact_id}/probe/aspect_ratio", message="video dimensions do not match output profile ratio", observed=f"{width}:{height}", expected=ratio, artifact_id=artifact_id)
        audio_codec = profile.get("audio_codec")
        expected_rate, expected_channels = profile.get("audio_sample_rate_hz"), profile.get("audio_channels")
        actual_codec = audio.get("audio_codec", audio.get("codec"))
        actual_rate = audio.get("audio_sample_rate_hz", audio.get("sample_rate_hz", audio.get("sample_rate")))
        actual_channels = audio.get("audio_channels", audio.get("channels"))
        audio_present = audio.get("present", actual_codec not in (None, "none"))
        if audio_codec == "none":
            if audio_present or actual_codec not in (None, "none") or actual_rate not in (None, 0) or actual_channels not in (None, 0):
                self._find(findings, check="audio", code="AUDIO_PROFILE_MISMATCH", severity="error", path=f"/artifacts/{artifact_id}/probe/audio", message="profile forbids an audio track but probe found audio", observed={"codec": actual_codec, "sample_rate_hz": actual_rate, "channels": actual_channels}, expected={"codec": "none", "sample_rate_hz": 0, "channels": 0}, artifact_id=artifact_id)
        else:
            for field, actual, expected in (("audio_codec", actual_codec, audio_codec), ("audio_sample_rate_hz", actual_rate, expected_rate), ("audio_channels", actual_channels, expected_channels)):
                if actual is None:
                    self._find(findings, check="audio", code="MEDIA_PROBE_UNAVAILABLE", severity="warning", path=f"/artifacts/{artifact_id}/probe/audio/{field}", message="media probe did not return a required audio fact", observed=None, expected=expected, artifact_id=artifact_id)
                elif (field == "audio_codec" and str(actual).lower() != str(expected).lower()) or (field != "audio_codec" and not _same_number(actual, expected)):
                    self._find(findings, check="audio", code="AUDIO_PROFILE_MISMATCH", severity="error", path=f"/artifacts/{artifact_id}/probe/audio/{field}", message="audio fact differs from output profile", observed=actual, expected=expected, artifact_id=artifact_id)

    def _check_subtitles(self, *, job: Mapping[str, Any], profile: Mapping[str, Any], subtitle: Mapping[str, Any] | None, findings: list[dict[str, Any]]) -> None:
        expected_tracks = list(profile.get("subtitle_track_ids") or [])
        job_subtitle_id = job.get("media_subtitle_version_id")
        if expected_tracks and subtitle is None:
            self._find(findings, check="subtitle", code="SUBTITLE_VERSION_MISSING", severity="error", path="/media_subtitle_version_id", message="output profile references subtitles but no locked subtitle version is available", observed=job_subtitle_id, expected="subtitle version")
            return
        if subtitle is None:
            return
        duration_ms = int(float(job.get("duration_seconds", 0)) * 1000)
        tracks = list(subtitle.get("tracks") or [])
        by_id = {str(track.get("id")): track for track in tracks if isinstance(track, Mapping) and track.get("id")}
        by_locale = {str(track.get("locale")): track for track in tracks if isinstance(track, Mapping) and track.get("locale")}
        if expected_tracks:
            for track_id in expected_tracks:
                track = by_id.get(str(track_id))
                if track is None and len(tracks) == len(expected_tracks) and len(expected_tracks) == 1:
                    track = tracks[0]
                if track is None:
                    self._find(findings, check="subtitle", code="SUBTITLE_TRACK_MISSING", severity="error", path="/tracks", message="output profile subtitle track is missing", observed=track_id, expected="locked track",)
                    continue
                self._validate_track(track=track, track_path=f"/tracks/{track_id}", duration_ms=duration_ms, findings=findings)
        else:
            for index, track in enumerate(tracks):
                self._validate_track(track=track, track_path=f"/tracks/{index}", duration_ms=duration_ms, findings=findings)
        if subtitle.get("duration_seconds") is not None and subtitle.get("duration_seconds") != job.get("duration_seconds"):
            self._find(findings, check="subtitle", code="SUBTITLE_DURATION_MISMATCH", severity="error", path="/duration_seconds", message="subtitle duration differs from render job", observed=subtitle.get("duration_seconds"), expected=job.get("duration_seconds"))

    def _validate_track(self, *, track: Mapping[str, Any], track_path: str, duration_ms: int, findings: list[dict[str, Any]]) -> None:
        cues = list(track.get("cues") or [])
        if track.get("cue_count") is not None and track.get("cue_count") != len(cues):
            self._find(findings, check="subtitle", code="SUBTITLE_CUE_COUNT_MISMATCH", severity="error", path=f"{track_path}/cue_count", message="subtitle cue count differs from cue list", observed=len(cues), expected=track.get("cue_count"))
        previous_end = -1
        previous_start = -1
        for index, cue in enumerate(cues):
            if not isinstance(cue, Mapping):
                self._find(findings, check="subtitle", code="SUBTITLE_CUE_INVALID", severity="error", path=f"{track_path}/cues/{index}", message="subtitle cue must be an object", observed=cue, expected="object")
                continue
            start, end = cue.get("start_ms"), cue.get("end_ms")
            text = cue.get("text")
            if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start or end > duration_ms:
                self._find(findings, check="subtitle", code="SUBTITLE_CUE_BOUNDS", severity="error", path=f"{track_path}/cues/{index}", message="subtitle cue is outside the media duration or has invalid bounds", observed={"start_ms": start, "end_ms": end}, expected={"start_ms": f">={0}", "end_ms": f"<={duration_ms}"})
            if isinstance(start, int) and isinstance(end, int):
                if start < previous_start:
                    self._find(findings, check="subtitle", code="SUBTITLE_CUE_ORDER", severity="error", path=f"{track_path}/cues/{index}/start_ms", message="subtitle cues are not ordered", observed=start, expected=f">={previous_start}")
                if start < previous_end:
                    self._find(findings, check="subtitle", code="SUBTITLE_CUE_OVERLAP", severity="error", path=f"{track_path}/cues/{index}/start_ms", message="subtitle cues overlap", observed=start, expected=f">={previous_end}")
                previous_start, previous_end = start, max(previous_end, end)
            if not isinstance(text, str) or not text.strip():
                self._find(findings, check="subtitle", code="SUBTITLE_CUE_TEXT_MISSING", severity="error", path=f"{track_path}/cues/{index}/text", message="subtitle cue text is required", observed=text, expected="nonempty text")

    def run_media_qa(self, *, media_render_job_id: Any | None = None, render_job: Any | None = None,
                     job: Any | None = None, artifacts: Sequence[Mapping[str, Any]] | None = None,
                     render_artifacts: Sequence[Mapping[str, Any]] | None = None,
                     predecessor_artifacts: Sequence[Mapping[str, Any]] | None = None,
                     asset_version: Any | None = None, asset: Any | None = None,
                     subtitle_version: Any | None = None, subtitle: Any | None = None,
                     profile: Mapping[str, Any] | None = None, org_id: Any = None,
                     tenant_context: Any = None, actor_id: Any = None, trace_id: str = "media-qa",
                     idempotency_key: str = "media-qa", expected_version: int | None = None,
                     evaluated_at: Any | None = None, **kwargs: Any) -> dict[str, Any]:
        if render_job is None:
            render_job = job
        if artifacts is None:
            artifacts = render_artifacts if render_artifacts is not None else predecessor_artifacts
        if asset_version is None:
            asset_version = asset
        if subtitle_version is None:
            subtitle_version = subtitle
        if media_render_job_id is None:
            media_render_job_id = kwargs.pop("render_job_id", None) or kwargs.pop("subject_id", None)
        if profile is None:
            profile = kwargs.pop("output_profile", None)
        if kwargs:
            raise MediaQAError("INVALID_QA_INPUT", f"unsupported QA arguments: {sorted(kwargs)}")
        tenant, actor = _context(org_id=org_id, actor_id=actor_id, tenant_context=tenant_context)
        trace = _text(trace_id, "trace_id")
        key = _text(idempotency_key, "idempotency_key", 200)
        if render_job is None and job is None and asset_version is not None:
            asset_projection = _mapping(asset_version, "asset_version")
            if _uuid(asset_projection.get("org_id"), "asset_version.org_id") != tenant:
                raise MediaQAError("TENANT_SCOPE_VIOLATION", "asset version is outside this organization")
            derived_id = media_render_job_id or asset_projection.get("render_job_id") or asset_projection.get("id")
            derived_id = _uuid(derived_id, "media_render_job_id")
            if profile is None:
                ratio = str(asset_projection.get("aspect_ratio") or "1:1")
                dimensions = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080)}.get(ratio, (1080, 1080))
                profile = {
                    "sequence": 1, "profile_key": str(asset_projection.get("output_profile_key") or "asset"),
                    "aspect_ratio": ratio, "width": dimensions[0], "height": dimensions[1], "frame_rate": 30,
                    "container_format": str(asset_projection.get("format") or "mp4").lower(),
                    "video_codec": "h264", "pixel_format": "yuv420p", "audio_codec": "none",
                    "audio_sample_rate_hz": 0, "audio_channels": 0, "subtitle_track_ids": [],
                }
            if artifacts is None:
                artifacts = [{
                    "id": asset_projection.get("id"), "sequence": 1, "stage": "full", "shot_sequence": None,
                    "output_profile_key": profile.get("profile_key"), "storage_object_ref": asset_projection.get("storage_object_ref") or f"private://missing/{derived_id}",
                    "content_hash": asset_projection.get("file_hash") or "0" * 64, "size_bytes": asset_projection.get("size_bytes", 0),
                    "content_type": asset_projection.get("content_type", "application/octet-stream"),
                    "input_hash": asset_projection.get("input_hash") or _hash(asset_projection), "org_id": tenant,
                }]
            render_job = {
                "id": derived_id, "org_id": tenant, "input_hash": asset_projection.get("input_hash") or _hash(asset_projection),
                "output_profile_key": profile.get("profile_key"), "output_profile": profile,
                "duration_seconds": asset_projection.get("duration_seconds", 30), "media_subtitle_version_id": None,
                "input_snapshot_hashes": {"subtitle": None}, "artifacts": artifacts,
            }
            media_render_job_id = derived_id
        job_projection = self._load_job(org_id=tenant, media_render_job_id=media_render_job_id, render_job=render_job)
        if expected_version is not None:
            if type(expected_version) is not int or expected_version < 1:
                raise MediaQAError("INVALID_QA_INPUT", "expected_version must be a positive integer")
            current_version = None
            if self.render_service is not None and hasattr(getattr(self.render_service, "store", None), "version"):
                current_version = self.render_service.store.version(org_id=tenant, job_id=job_projection["id"])
            elif isinstance(job_projection.get("version"), int):
                current_version = job_projection["version"]
            if current_version is not None and current_version != expected_version:
                raise MediaQAError("VERSION_CONFLICT", "render job version differs from expected_version")
        artifact_list = self._artifacts(org_id=tenant, job=job_projection, artifacts=artifacts)
        subtitle_projection = self._load_subtitle(org_id=tenant, job=job_projection, subtitle_version=subtitle_version)
        selected_profile = _mapping(profile if profile is not None else job_projection.get("output_profile"), "output_profile")
        if selected_profile.get("profile_key") != job_projection.get("output_profile_key"):
            raise MediaQAError("QA_SOURCE_MISMATCH", "output profile does not match render job")
        # The request hash is computed before an implicit clock read, so a repeated
        # command without evaluated_at still replays instead of conflicting.
        request_projection = {
            "job": _safe(job_projection), "artifacts": _safe(artifact_list), "subtitle": _safe(subtitle_projection),
            "profile": _safe(selected_profile), "expected_version": expected_version, "trace_id": trace,
            "evaluated_at": _stamp(_time(evaluated_at, "evaluated_at")) if evaluated_at is not None else None,
        }
        request_hash = _hash(request_projection)
        prior = self.store.replay(org_id=tenant, namespace="media-qa", key=key, request_hash=request_hash)
        if prior is not None:
            return prior
        check_time = _time(evaluated_at, "evaluated_at") if evaluated_at is not None else _time(self.clock(), "clock")
        findings: list[dict[str, Any]] = []
        if not artifact_list:
            self._find(findings, check="file_hash", code="ARTIFACTS_MISSING", severity="error", path="/artifacts", message="render job has no media artifacts", observed=[], expected="at least one artifact")
        for artifact in artifact_list:
            artifact_id = str(artifact["id"])
            if artifact.get("output_profile_key") != selected_profile.get("profile_key"):
                self._find(findings, check="file_hash", code="ARTIFACT_PROFILE_MISMATCH", severity="error", path=f"/artifacts/{artifact_id}/output_profile_key", message="artifact belongs to another output profile", observed=artifact.get("output_profile_key"), expected=selected_profile.get("profile_key"), artifact_id=artifact_id)
            if not isinstance(artifact.get("size_bytes"), int) or artifact.get("size_bytes", 0) <= 0:
                self._find(findings, check="file_hash", code="FILE_EMPTY", severity="error", path=f"/artifacts/{artifact_id}/size_bytes", message="media artifact must contain bytes", observed=artifact.get("size_bytes"), expected=">0", artifact_id=artifact_id)
            self._check_file(org_id=tenant, artifact=artifact, job=job_projection, findings=findings)
            probe, probe_error = self._probe(org_id=tenant, artifact=artifact, profile=selected_profile)
            self._check_visual_audio(artifact=artifact, profile=selected_profile, job=job_projection, probe=probe, probe_error=probe_error, findings=findings)
        self._check_subtitles(job=job_projection, profile=selected_profile, subtitle=subtitle_projection, findings=findings)
        findings.sort(key=lambda item: (str(item.get("check", "")), str(item.get("code", "")), str(item.get("path", "")), str(item.get("artifact_id", "")), str(item.get("message", ""))))
        checks = {
            check: {"status": self._category_status(findings, check), "finding_count": sum(1 for item in findings if item.get("check") == check)}
            for check in CHECKS
        }
        status = "failed" if any(value["status"] == "failed" for value in checks.values()) else "needs_review" if any(value["status"] == "needs_review" for value in checks.values()) else "passed"
        artifact_facts = [{key: _safe(artifact.get(key)) for key in ("id", "sequence", "stage", "shot_sequence", "output_profile_key", "storage_object_ref", "content_hash", "size_bytes", "content_type", "input_hash")} for artifact in artifact_list]
        subtitle_id = subtitle_projection.get("id") if subtitle_projection else job_projection.get("media_subtitle_version_id")
        input_hashes = job_projection.get("input_snapshot_hashes") or {}
        report = {
            "id": str(uuid4()), "org_id": tenant, "subject_type": "media_render_job", "subject_id": job_projection["id"],
            "rule_version": self.rule_version, "status": status, "findings": findings, "checks": checks,
            "artifact_facts": artifact_facts,
            "input_snapshot": {
                "render_job_id": job_projection["id"], "input_hash": job_projection.get("input_hash"),
                "output_profile_key": selected_profile.get("profile_key"), "output_profile": _safe(selected_profile),
                "subtitle_version_id": subtitle_id, "subtitle_snapshot_hash": input_hashes.get("subtitle"),
            },
            "actor_id": actor, "trace_id": trace, "evaluated_at": _stamp(check_time), "request_hash": request_hash,
            **({"expected_version": expected_version} if expected_version is not None else {}),
            "created_at": _stamp(check_time),
        }
        schema_errors = list(QA_VALIDATOR.iter_errors(report))
        if schema_errors:
            raise MediaQAError("INVALID_QA_REPORT", schema_errors[0].message)
        output_hash = _hash(report)
        payload = {"aggregate_id": job_projection["id"], "aggregate_version": int(expected_version or 1), "report_id": report["id"], "status": status, "report_hash": output_hash}
        event = {
            "event_id": str(uuid5(EVENT_NAMESPACE, f"media-qa:{tenant}:{report['id']}")), "event_type": "asset.qa_requested",
            "event_schema_version": 1, "org_id": tenant, "aggregate_id": job_projection["id"], "aggregate_type": "AssetVersion",
            "aggregate_version": int(expected_version or 1), "trace_id": trace, "actor_type": "service", "actor_id": actor,
            "idempotency_key": key, "occurred_at": _stamp(check_time), "payload": payload, "payload_hash": _hash(payload),
        }
        audit = {"operation": "run_media_qa", "org_id": tenant, "job_id": job_projection["id"], "actor_id": actor,
                 "trace_id": trace, "idempotency_key": key, "input_hash": request_hash, "output_hash": output_hash,
                 "status": status, "finding_count": len(findings), "created_at": _stamp(check_time)}
        return self.store.save(org_id=tenant, namespace="media-qa", key=key, request_hash=request_hash,
                               report=report, findings=findings, audit=audit, event=event)

    # Public aliases keep the application boundary discoverable to worker/API callers.
    def run_qa(self, **kwargs: Any) -> dict[str, Any]:
        return self.run_media_qa(**kwargs)

    def check_media(self, **kwargs: Any) -> dict[str, Any]:
        return self.run_media_qa(**kwargs)

    def check_render_job(self, **kwargs: Any) -> dict[str, Any]:
        return self.run_media_qa(**kwargs)

    def check_asset(self, **kwargs: Any) -> dict[str, Any]:
        return self.run_media_qa(**kwargs)

    def evaluate(self, **kwargs: Any) -> dict[str, Any]:
        return self.run_media_qa(**kwargs)

    def check_asset_version(self, **kwargs: Any) -> dict[str, Any]:
        return self.run_media_qa(**kwargs)


MediaQAService = MediaAssetQAService
MediaRenderQAService = MediaAssetQAService
MediaQualityService = MediaAssetQAService
MediaQualityQAService = MediaAssetQAService
AssetQAService = MediaAssetQAService
MediaAssetQualityService = MediaAssetQAService
MediaAssetQAError = MediaQAError
QAReportStore = InMemoryMediaQAStore
MediaQAStore = InMemoryMediaQAStore


__all__ = [
    "AssetQAService", "FakeMediaProbe", "InMemoryMediaQAStore", "MediaAssetQAError", "MediaAssetQAService",
    "MediaAssetQualityService", "MediaProbePort", "MediaQAError", "MediaQAService", "MediaQAStore",
    "MediaQualityQAService", "MediaQualityService", "MediaRenderQAService", "QAReportStore", "QAStoragePort",
]
