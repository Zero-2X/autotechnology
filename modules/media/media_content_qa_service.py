"""MEDIA-005B deterministic content, disclosure and material-rights QA."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import json
from hashlib import sha256
import re
from threading import RLock
from typing import Any, Mapping, Protocol, Sequence
from uuid import UUID, uuid4, uuid5

from jsonschema import Draft202012Validator, FormatChecker

from .media_qa_service import (
    EVENT_NAMESPACE,
    QA_SCHEMA,
    _context,
    _hash,
    _mapping,
    _safe,
    _stamp,
    _time,
    _text,
    _uuid,
)


_REPORT_VALIDATOR = Draft202012Validator(QA_SCHEMA, format_checker=FormatChecker())
_NUMBER = re.compile(r"(?<![\w])[-+]?\d+(?:[.,]\d+)*(?:\.\d+)?(?:%|ms|s|kg|km|GB|MB|px|Hz)?(?![\w])", re.IGNORECASE)
_CODE = re.compile(r"```[\w.+#-]*\s*([\s\S]*?)```|`([^`\n]+)`")
_VERSION = re.compile(r"(?<![\w])v?\d+\.\d+(?:\.\d+){0,2}(?:[-+][0-9A-Za-z.-]+)?(?![\w])", re.IGNORECASE)
_AI_LABEL = re.compile(r"(?:artificial\s+intelligence|ai[- ]generated|ai\s+generated|machine[- ]generated|人工智能|机器生成|生成式\s*AI)", re.IGNORECASE)
_AD_LABEL = re.compile(r"(?:advertisement|advertising|sponsored|paid\s+partnership|广告|赞助|付费合作)", re.IGNORECASE)
_MEDIA_CHECKS = ("visual", "audio", "subtitle", "file_hash", "numbers", "code", "versions", "ai_label", "rights")


class MediaContentQAError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class TextExtractionPort(Protocol):
    def extract(self, *, org_id: str, artifact: Mapping[str, Any], source: Mapping[str, Any]) -> Mapping[str, Any]: ...


class RightsPort(Protocol):
    def check(self, *, org_id: str, asset_version: Mapping[str, Any], rights_versions: Sequence[Mapping[str, Any]], market: str | None, locale: str | None, media: str, permitted_use: str, evaluated_at: str) -> Mapping[str, Any]: ...


class FakeTextExtractionPort:
    """Offline text projection adapter for acceptance tests."""

    def __init__(self, *, text: str | None = None, ocr_text: str | None = None, transcript: str | None = None,
                 result: Mapping[str, Any] | None = None, error: Exception | None = None) -> None:
        self.result = deepcopy(dict(result)) if result is not None else None
        self.text, self.ocr_text, self.transcript, self.error = text, ocr_text, transcript, error
        self.calls: list[dict[str, Any]] = []

    def extract(self, *, org_id: str, artifact: Mapping[str, Any], source: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append({"org_id": org_id, "artifact_id": artifact.get("id")})
        if self.error is not None:
            raise self.error
        if self.result is not None:
            return deepcopy(self.result)
        result: dict[str, Any] = {}
        if self.text is not None:
            result["text"] = self.text
        if self.ocr_text is not None:
            result["ocr_text"] = self.ocr_text
        if self.transcript is not None:
            result["transcript"] = self.transcript
        return result


class InMemoryMediaContentQAStore:
    def __init__(self) -> None:
        self.reports: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
        self.evaluations: dict[tuple[str, str, int], dict[str, Any]] = {}
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

    def replay(self, *, org_id: str, key: str, request_hash: str) -> dict[str, Any] | None:
        with self._lock:
            prior = self.reports.get((org_id, key))
            if prior is None:
                return None
            if prior[0] != request_hash:
                raise MediaContentQAError("IDEMPOTENCY_KEY_REUSED", "content QA payload differs from prior request")
            return deepcopy(prior[1])

    def save(self, *, org_id: str, key: str, request_hash: str, report: Mapping[str, Any], evaluations: Sequence[Mapping[str, Any]], audit: Mapping[str, Any], event: Mapping[str, Any]) -> dict[str, Any]:
        identity = (org_id, key)
        with self._lock:
            prior = self.reports.get(identity)
            if prior is not None:
                if prior[0] != request_hash:
                    raise MediaContentQAError("IDEMPOTENCY_KEY_REUSED", "content QA payload differs from prior request")
                return deepcopy(prior[1])
            result = deepcopy(dict(report))
            self.reports[identity] = (request_hash, result)
            for sequence, evaluation in enumerate(evaluations, 1):
                self.evaluations[(org_id, str(report["id"]), sequence)] = {
                    "org_id": org_id, "report_id": str(report["id"]), "sequence": sequence, **deepcopy(dict(evaluation)),
                }
            self.audit.append(deepcopy(dict(audit)))
            self.outbox.append(deepcopy(dict(event)))
            return deepcopy(result)


def _counter_tokens(pattern: re.Pattern[str], text: str) -> Counter[str]:
    values: list[str] = []
    for match in pattern.finditer(text):
        if pattern is _CODE:
            values.append((match.group(1) if match.group(1) is not None else match.group(2) or "").strip())
        else:
            values.append(match.group(0).replace(",", ""))
    return Counter(values)


def _text_from_projection(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    parts: list[str] = []
    for field in ("title", "abstract", "text", "content", "statement", "disclosure", "ai_disclosure"):
        if isinstance(value.get(field), str):
            parts.append(value[field])
    for field in ("segments", "cues", "blocks", "sections"):
        items = value.get(field)
        if isinstance(items, Sequence) and not isinstance(items, (str, bytes, bytearray)):
            for item in items:
                if isinstance(item, Mapping):
                    for subfield in ("text", "content", "localized_text", "transcript"):
                        if isinstance(item.get(subfield), str):
                            parts.append(item[subfield])
    body = value.get("body")
    if isinstance(body, Mapping):
        parts.append(_text_from_projection(body))
    return "\n".join(parts)


class MediaContentRightsQAService:
    """Check protected tokens, disclosures and rights without reading media bytes."""

    rule_version = "media-005b/v1"

    def __init__(self, *, extractor: TextExtractionPort | Any | None = None,
                 text_port: TextExtractionPort | Any | None = None,
                 rights_port: RightsPort | Any | None = None,
                 store: InMemoryMediaContentQAStore | None = None,
                 clock: Any | None = None) -> None:
        self.extractor = extractor or text_port
        self.rights_port = rights_port
        self.store = store or InMemoryMediaContentQAStore()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def audit_log(self) -> tuple[dict[str, Any], ...]:
        return self.store.audit_log

    @property
    def outbox_events(self) -> tuple[dict[str, Any], ...]:
        return self.store.outbox_events

    @staticmethod
    def _find(findings: list[dict[str, Any]], *, check: str, code: str, severity: str, path: str, message: str,
              observed: Any = None, expected: Any = None, object_id: str | None = None) -> None:
        item = {"code": code, "severity": severity, "path": path, "message": message,
                "observed": _safe(observed), "expected": _safe(expected), "check": check}
        if object_id is not None:
            item["object_id"] = object_id
        findings.append(item)

    @staticmethod
    def _status(findings: Sequence[Mapping[str, Any]], check: str) -> str:
        selected = [item for item in findings if item.get("check") == check]
        if any(item.get("severity") == "error" for item in selected):
            return "failed"
        if any(item.get("severity") == "warning" for item in selected):
            return "needs_review"
        return "passed"

    def _extract(self, *, org_id: str, artifact: Mapping[str, Any], source: Mapping[str, Any]) -> tuple[str | None, str | None]:
        if self.extractor is None:
            return None, "TEXT_EXTRACTION_UNAVAILABLE"
        try:
            if hasattr(self.extractor, "extract"):
                method = self.extractor.extract
                try:
                    result = method(org_id=org_id, artifact=artifact, source=source)
                except TypeError:
                    result = method(artifact=artifact, source=source)
            elif callable(self.extractor):
                result = self.extractor(org_id=org_id, artifact=artifact, source=source)
            else:
                return None, "TEXT_EXTRACTION_UNAVAILABLE"
            if not isinstance(result, Mapping) or result.get("status") in {"unknown", "unavailable"}:
                return None, "TEXT_EXTRACTION_UNAVAILABLE"
            value = result.get("text") or result.get("ocr_text") or result.get("transcript")
            if not isinstance(value, str):
                return None, "TEXT_EXTRACTION_UNAVAILABLE"
            return value, None
        except Exception as exc:
            return None, getattr(exc, "code", None) or "TEXT_EXTRACTION_UNAVAILABLE"

    def _check_tokens(self, *, source_text: str, observed_text: str | None, findings: list[dict[str, Any]]) -> None:
        if observed_text is None:
            for check, code in (("numbers", "MEDIA_NUMBER_EXTRACTION_UNAVAILABLE"), ("code", "MEDIA_CODE_EXTRACTION_UNAVAILABLE"), ("versions", "MEDIA_VERSION_EXTRACTION_UNAVAILABLE")):
                self._find(findings, check=check, code=code, severity="warning", path="/text_extraction", message="text extraction is unavailable; protected token check needs review", observed=None, expected="extracted text")
            return
        for check, pattern, mismatch_code, label in (
            ("numbers", _NUMBER, "MEDIA_NUMBER_MISMATCH", "number"),
            ("code", _CODE, "MEDIA_CODE_MISMATCH", "code token"),
            ("versions", _VERSION, "MEDIA_VERSION_MISMATCH", "version token"),
        ):
            expected = _counter_tokens(pattern, source_text)
            actual = _counter_tokens(pattern, observed_text)
            if expected == actual:
                continue
            missing = list((expected - actual).elements())
            added = list((actual - expected).elements())
            self._find(findings, check=check, code=mismatch_code, severity="error", path=f"/text/{check}", message=f"{label} tokens differ between locked source and extracted media text", observed={"missing": missing, "added": added}, expected={"tokens": list(expected.elements())})

    def _check_disclosure(self, *, source: Mapping[str, Any], observed_text: str | None, ai_generated: bool, advertising_required: bool,
                          required_ad_disclosure: str | None, findings: list[dict[str, Any]]) -> None:
        disclosure_parts = [source.get(field) for field in ("disclosure", "ai_disclosure", "advertising_disclosure") if isinstance(source.get(field), str)]
        if observed_text:
            disclosure_parts.append(observed_text)
        disclosure = " ".join(disclosure_parts)
        if ai_generated and not _AI_LABEL.search(disclosure):
            self._find(findings, check="ai_label", code="AI_LABEL_MISSING", severity="error", path="/disclosure", message="AI generated media requires an AI disclosure", observed=bool(disclosure), expected="AI or artificial intelligence disclosure")
        if advertising_required:
            if not _AD_LABEL.search(disclosure):
                self._find(findings, check="ai_label", code="AD_DISCLOSURE_MISSING", severity="error", path="/disclosure", message="advertising media requires an advertising disclosure", observed=bool(disclosure), expected="advertisement/sponsored disclosure")
            elif required_ad_disclosure and required_ad_disclosure.casefold() not in disclosure.casefold():
                self._find(findings, check="ai_label", code="AD_DISCLOSURE_MISMATCH", severity="error", path="/disclosure", message="required advertising disclosure text is missing", observed=disclosure[:128], expected=required_ad_disclosure)

    def _check_rights(self, *, org_id: str, actor: str, asset: Mapping[str, Any] | None, rights_versions: Sequence[Mapping[str, Any]], market: str | None,
                      locale: str | None, media: str, permitted_use: str, check_time: datetime, findings: list[dict[str, Any]]) -> None:
        rights = list(rights_versions or ())
        for index, item in enumerate(rights):
            if not isinstance(item, Mapping) or _uuid(item.get("org_id"), f"rights_versions[{index}].org_id") != org_id:
                raise MediaContentQAError("TENANT_SCOPE_VIOLATION", "rights version is outside this organization")
        required_ids = []
        if asset is not None:
            required_ids = [str(value) for value in (asset.get("rights_snapshot_ids") or asset.get("rights_record_version_ids") or ())]
        by_id = {str(item.get("id")): item for item in rights}
        if required_ids:
            missing = [value for value in required_ids if value not in by_id]
            if missing:
                self._find(findings, check="rights", code="RIGHTS_SNAPSHOT_MISSING", severity="error", path="/rights_snapshot_ids", message="AssetVersion rights snapshot is not present in supplied rights versions", observed=missing, expected="all rights snapshot ids")
        allowed = False
        details: list[dict[str, Any]] = []
        levels = {"research": 0, "derivative": 1, "commercial": 2}
        for item in rights:
            reasons: list[str] = []
            if item.get("status") not in {"verified", "current"}:
                reasons.append("status")
            try:
                valid_from = _time(item.get("valid_from"), "rights.valid_from") if item.get("valid_from") else None
                valid_to = _time(item.get("valid_to"), "rights.valid_to") if item.get("valid_to") else None
            except MediaContentQAError:
                reasons.append("validity")
                valid_from = valid_to = None
            if valid_from is not None and check_time < valid_from:
                reasons.append("not_yet_valid")
            if valid_to is not None and check_time >= valid_to:
                reasons.append("expired")
            if market is not None and market not in (item.get("permitted_regions") or []):
                reasons.append("region")
            if locale is not None and locale not in (item.get("permitted_locales") or []):
                reasons.append("locale")
            if media not in (item.get("permitted_media") or []):
                reasons.append("media")
            if levels.get(permitted_use, -1) > levels.get(str(item.get("permitted_use")), -1):
                reasons.append("use")
            details.append({"id": str(item.get("id")), "reasons": reasons})
            if not reasons and (not required_ids or str(item.get("id")) in required_ids):
                allowed = True
        if not rights:
            self._find(findings, check="rights", code="RIGHTS_MISSING", severity="error", path="/rights_versions", message="material rights are required for media QA", observed=[], expected="verified rights version")
        elif not allowed:
            self._find(findings, check="rights", code="RIGHTS_NOT_ALLOWED", severity="error", path="/rights_versions", message="no supplied RightsRecordVersion permits this media use", observed=details, expected={"market": market, "locale": locale, "media": media, "permitted_use": permitted_use})
        if self.rights_port is not None:
            try:
                result = self.rights_port.check(org_id=org_id, asset_version=asset or {}, rights_versions=rights, market=market, locale=locale, media=media, permitted_use=permitted_use, evaluated_at=_stamp(check_time))
            except Exception:
                self._find(findings, check="rights", code="RIGHTS_CHECK_UNAVAILABLE", severity="warning", path="/rights_versions", message="rights port result needs human review", observed="unavailable", expected="allowed decision")
            else:
                if not isinstance(result, Mapping) or result.get("allowed") is not True:
                    self._find(findings, check="rights", code="RIGHTS_PORT_BLOCKED", severity="error", path="/rights_versions", message="rights port did not authorize this media", observed=_safe(result), expected={"allowed": True})

    def run_content_qa(self, *, org_id: Any = None, tenant_context: Any = None, actor_id: Any = None,
                        asset_version: Any | None = None, asset: Any | None = None, render_job: Any | None = None,
                        artifacts: Sequence[Mapping[str, Any]] | None = None, source_text: str | None = None,
                        expected_text: str | None = None, observed_text: str | None = None,
                        ocr_text: str | None = None, transcript: str | None = None,
                        variant_version: Any | None = None, canonical_version: Any | None = None,
                        script_version: Any | None = None, subtitle_version: Any | None = None,
                        claims: Sequence[Mapping[str, Any]] = (), evidence: Sequence[Mapping[str, Any]] = (),
                        rights_versions: Sequence[Mapping[str, Any]] = (), market: str | None = None,
                        locale: str | None = None, media: str | None = None, permitted_use: str = "commercial",
                        ai_generated: bool = False, advertising_required: bool = False,
                        required_ad_disclosure: str | None = None, idempotency_key: str = "media-content-qa",
                        trace_id: str = "media-content-qa", expected_version: int | None = None,
                        evaluated_at: Any | None = None, **kwargs: Any) -> dict[str, Any]:
        if asset_version is None:
            asset_version = asset
        if observed_text is None:
            observed_text = ocr_text or transcript
        if observed_text is None:
            observed_text = kwargs.pop("extracted_text", None)
        if artifacts is None:
            artifacts = kwargs.pop("predecessor_artifacts", None)
        if kwargs:
            raise MediaContentQAError("INVALID_QA_INPUT", f"unsupported content QA arguments: {sorted(kwargs)}")
        tenant, actor = _context(org_id=org_id, actor_id=actor_id, tenant_context=tenant_context)
        key = _text(idempotency_key, "idempotency_key", 200)
        trace = _text(trace_id, "trace_id")
        asset_projection = _mapping(asset_version, "asset_version") if asset_version is not None else None
        if asset_projection is not None and _uuid(asset_projection.get("org_id"), "asset_version.org_id") != tenant:
            raise MediaContentQAError("TENANT_SCOPE_VIOLATION", "asset version is outside this organization")
        variant_projection = _mapping(variant_version, "variant_version") if variant_version is not None else None
        canonical_projection = _mapping(canonical_version, "canonical_version") if canonical_version is not None else None
        for name, projection in (("variant_version", variant_projection), ("canonical_version", canonical_projection), ("script_version", script_version), ("subtitle_version", subtitle_version)):
            if projection is not None and isinstance(projection, Mapping) and projection.get("org_id") is not None and _uuid(projection.get("org_id"), f"{name}.org_id") != tenant:
                raise MediaContentQAError("TENANT_SCOPE_VIOLATION", f"{name} is outside this organization")
        source = {
            "source_text": source_text, "variant": _safe(variant_projection) if variant_projection is not None else None,
            "canonical": _safe(canonical_projection) if canonical_projection is not None else None,
            "script": _safe(script_version) if isinstance(script_version, Mapping) else script_version,
            "subtitle": _safe(subtitle_version) if isinstance(subtitle_version, Mapping) else subtitle_version,
        }
        if source_text is None:
            source_text = "\n".join(filter(None, (_text_from_projection(script_version), _text_from_projection(subtitle_version), _text_from_projection(canonical_projection), _text_from_projection(variant_projection))))
        if expected_text is not None:
            source_text = expected_text
        if not isinstance(source_text, str) or not source_text:
            raise MediaContentQAError("INVALID_QA_INPUT", "source_text or a source version projection is required")
        subject_id = _uuid((asset_projection or {}).get("id") or (render_job or {}).get("id"), "subject_id")
        request_projection = {
            "subject_id": subject_id, "asset": _safe(asset_projection), "render_job": _safe(render_job),
            "artifacts": _safe(list(artifacts or ())), "source_hash": sha256(source_text.encode("utf-8")).hexdigest(),
            "observed_hash": sha256(observed_text.encode("utf-8")).hexdigest() if isinstance(observed_text, str) else None,
            "rights": _safe(list(rights_versions or ())), "variant": _safe(variant_projection), "canonical": _safe(canonical_projection),
            "config": {"market": market, "locale": locale, "media": media, "permitted_use": permitted_use, "ai_generated": ai_generated, "advertising_required": advertising_required, "required_ad_disclosure": required_ad_disclosure, "expected_version": expected_version},
            "trace_id": trace, "evaluated_at": _stamp(_time(evaluated_at, "evaluated_at")) if evaluated_at is not None else None,
        }
        request_hash = _hash(request_projection)
        prior = self.store.replay(org_id=tenant, key=key, request_hash=request_hash)
        if prior is not None:
            return prior
        check_time = _time(evaluated_at, "evaluated_at") if evaluated_at is not None else _time(self.clock(), "clock")
        if expected_version is not None and asset_projection is not None and asset_projection.get("version_no") != expected_version:
            raise MediaContentQAError("VERSION_CONFLICT", "asset version differs from expected_version")
        findings: list[dict[str, Any]] = []
        if observed_text is None and self.extractor is not None:
            artifact = _mapping((list(artifacts or ()) or [{}])[0], "artifact")
            observed_text, extraction_error = self._extract(org_id=tenant, artifact=artifact, source=source)
        else:
            extraction_error = None if observed_text is not None else "TEXT_EXTRACTION_UNAVAILABLE"
        self._check_tokens(source_text=source_text, observed_text=observed_text, findings=findings)
        self._check_disclosure(source=asset_projection or variant_projection or {}, observed_text=observed_text, ai_generated=ai_generated, advertising_required=advertising_required, required_ad_disclosure=required_ad_disclosure, findings=findings)
        self._check_rights(org_id=tenant, actor=actor, asset=asset_projection, rights_versions=rights_versions, market=market or (variant_projection or {}).get("market"), locale=locale or (variant_projection or {}).get("locale"), media=media or (asset_projection or {}).get("media_type", "video"), permitted_use=permitted_use, check_time=check_time, findings=findings)
        if extraction_error:
            self._find(findings, check="numbers", code=extraction_error, severity="warning", path="/text_extraction", message="media text extraction needs human review", observed=extraction_error, expected="extracted text")
        findings.sort(key=lambda item: (str(item.get("check", "")), str(item.get("code", "")), str(item.get("path", "")), str(item.get("object_id", "")), str(item.get("message", ""))))
        checks = {check: {"status": self._status(findings, check), "finding_count": sum(1 for item in findings if item.get("check") == check)} for check in _MEDIA_CHECKS}
        status = "failed" if any(value["status"] == "failed" for value in checks.values()) else "needs_review" if any(value["status"] == "needs_review" for value in checks.values()) else "passed"
        input_hash = (render_job or {}).get("input_hash") if isinstance(render_job, Mapping) else None
        if not isinstance(input_hash, str) or len(input_hash) != 64:
            input_hash = _hash(request_projection)
        report = {
            "id": str(uuid4()), "org_id": tenant, "subject_type": "media_asset_version" if asset_projection is not None else "media_render_job", "subject_id": subject_id,
            "rule_version": self.rule_version, "status": status, "findings": findings, "checks": checks,
            "artifact_facts": [], "input_snapshot": {"render_job_id": subject_id, "input_hash": input_hash, "output_profile_key": "content", "output_profile": {}, "subtitle_version_id": (subtitle_version or {}).get("id") if isinstance(subtitle_version, Mapping) else None, "subtitle_snapshot_hash": (subtitle_version or {}).get("snapshot_hash") if isinstance(subtitle_version, Mapping) else None},
            "actor_id": actor, "trace_id": trace, "evaluated_at": _stamp(check_time), "request_hash": request_hash,
            **({"expected_version": expected_version} if expected_version is not None else {}), "created_at": _stamp(check_time),
        }
        errors = list(_REPORT_VALIDATOR.iter_errors(report))
        if errors:
            raise MediaContentQAError("INVALID_QA_REPORT", errors[0].message)
        report_hash = _hash(report)
        payload = {"aggregate_id": subject_id, "aggregate_version": int(expected_version or 1), "report_id": report["id"], "status": status, "report_hash": report_hash}
        event = {"event_id": str(uuid5(EVENT_NAMESPACE, f"media-content-qa:{tenant}:{report['id']}")), "event_type": "asset.qa_requested", "event_schema_version": 1, "org_id": tenant, "aggregate_id": subject_id, "aggregate_type": "AssetVersion", "aggregate_version": int(expected_version or 1), "trace_id": trace, "actor_type": "service", "actor_id": actor, "idempotency_key": key, "occurred_at": _stamp(check_time), "payload": payload, "payload_hash": _hash(payload)}
        audit = {"operation": "run_content_qa", "org_id": tenant, "subject_id": subject_id, "actor_id": actor, "trace_id": trace, "idempotency_key": key, "input_hash": request_hash, "output_hash": report_hash, "status": status, "finding_count": len(findings), "created_at": _stamp(check_time)}
        evaluations = [{"check_name": item.get("check"), "code": item.get("code"), "source_hash": sha256(source_text.encode("utf-8")).hexdigest(), "observed_hash": sha256(observed_text.encode("utf-8")).hexdigest() if isinstance(observed_text, str) else None, "rights_snapshot_hash": _hash(list(rights_versions or ())), "created_at": _stamp(check_time)} for item in findings]
        return self.store.save(org_id=tenant, key=key, request_hash=request_hash, report=report, evaluations=evaluations, audit=audit, event=event)

    def run_media_content_qa(self, **kwargs: Any) -> dict[str, Any]:
        return self.run_content_qa(**kwargs)

    def run_rights_qa(self, **kwargs: Any) -> dict[str, Any]:
        return self.run_content_qa(**kwargs)

    def check_content(self, **kwargs: Any) -> dict[str, Any]:
        return self.run_content_qa(**kwargs)

    def check_asset(self, **kwargs: Any) -> dict[str, Any]:
        return self.run_content_qa(**kwargs)

    def check_asset_version(self, **kwargs: Any) -> dict[str, Any]:
        return self.run_content_qa(**kwargs)


MediaAssetContentQAService = MediaContentRightsQAService
MediaRightsQAService = MediaContentRightsQAService
MediaContentQAService = MediaContentRightsQAService
MediaComplianceQAService = MediaContentRightsQAService
MediaContentQAStore = InMemoryMediaContentQAStore


__all__ = [
    "FakeTextExtractionPort", "InMemoryMediaContentQAStore", "MediaAssetContentQAService", "MediaComplianceQAService",
    "MediaContentQAError", "MediaContentQAService", "MediaContentQAStore", "MediaContentRightsQAService",
    "MediaRightsQAService", "RightsPort", "TextExtractionPort",
]
