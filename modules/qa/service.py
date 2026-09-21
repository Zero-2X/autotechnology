"""Deterministic Claim/Evidence and content integrity checks for QA-001."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from threading import RLock
from typing import Any, Callable, Mapping, Protocol, Sequence
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker


_ROOT = Path(__file__).resolve().parents[2]
_REPORT_VALIDATOR = Draft202012Validator(
    json.loads((_ROOT / "packages/contracts/jsonschema/qa-report.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
_VARIANT_VALIDATOR = Draft202012Validator(
    json.loads((_ROOT / "packages/contracts/jsonschema/variant-version.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
_CLAIM_VALIDATOR = Draft202012Validator(
    json.loads((_ROOT / "packages/contracts/jsonschema/claim.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
_EVIDENCE_VALIDATOR = Draft202012Validator(
    json.loads((_ROOT / "packages/contracts/jsonschema/evidence.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
_NUMBER = re.compile(r"(?<![\w])[-+]?\d+(?:[.,]\d+)*(?:%|ms|s|kg|km|GB|MB)?(?![\w])")
_URL = re.compile(r"https?://[^\s<>]+")
_CODE = re.compile(r"```[\s\S]*?```|`[^`\n]+`")


class QAError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class TerminologyPort(Protocol):
    def check(self, *, org_id: str, source: Mapping[str, Any], variant: Mapping[str, Any], locale: str) -> Sequence[Mapping[str, Any]]: ...


def _hash(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _uuid(value: UUID | str, name: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise QAError("INVALID_QA_INPUT", f"{name} must be a UUID") from exc


def _text(value: object, name: str, limit: int = 256) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise QAError("INVALID_QA_INPUT", f"{name} must be nonempty text")
    return value.strip()


def _time(value: Any, field: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _texts(value: Mapping[str, Any], *, variant: bool = False) -> str:
    parts: list[str] = []
    for field in ("title", "abstract", "problem", "statement"):
        if isinstance(value.get(field), str):
            parts.append(value[field])
    sections = value.get("sections", [])
    if isinstance(sections, list):
        for item in sections:
            if isinstance(item, Mapping) and isinstance(item.get("content"), str):
                parts.append(item["content"])
    blocks: Any = value.get("body", {}).get("blocks", []) if isinstance(value.get("body"), Mapping) else value.get("blocks", [])
    if isinstance(blocks, list):
        for item in blocks:
            if isinstance(item, Mapping):
                for field in ("localized_text", "text", "content", "disclosure"):
                    if isinstance(item.get(field), str):
                        parts.append(item[field])
    code_blocks = value.get("code_blocks", [])
    if isinstance(code_blocks, list):
        for item in code_blocks:
            if isinstance(item, Mapping) and isinstance(item.get("content"), str):
                parts.append(item["content"])
            elif isinstance(item, str):
                parts.append(item)
    return "\n".join(parts)


def _counts(text: str) -> dict[str, dict[str, int]]:
    code = _CODE.findall(text)
    without_code = _CODE.sub(" ", text)
    urls = _URL.findall(without_code)
    without_urls = _URL.sub(" ", without_code)
    return {
        "number": dict(sorted({token: _NUMBER.findall(without_urls).count(token) for token in set(_NUMBER.findall(without_urls))}.items())),
        "url": dict(sorted({token: urls.count(token) for token in set(urls)}.items())),
        "code": dict(sorted({token: code.count(token) for token in set(code)}.items())),
    }


class QAService:
    """Run QA checks over immutable projections and return a stable report."""

    rule_version = "qa-001/v1"

    def __init__(self, *, terminology_port: TerminologyPort | None = None) -> None:
        self.terminology_port = terminology_port
        self.audit: list[dict[str, Any]] = []
        self._results: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
        self._lock = RLock()

    def check_variant(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
                      idempotency_key: str, variant_version: Mapping[str, Any],
                      canonical_version: Mapping[str, Any], claims: Sequence[Mapping[str, Any]] = (),
                      evidence: Sequence[Mapping[str, Any]] = (),
                      source_map: Sequence[Mapping[str, Any]] = (),
                      evaluated_at: datetime | str | None = None) -> dict[str, Any]:
        tenant = _uuid(org_id, "org_id")
        actor = _uuid(actor_id, "actor_id")
        trace = _text(trace_id, "trace_id")
        key = _text(idempotency_key, "idempotency_key", 200)
        if not isinstance(variant_version, Mapping) or not isinstance(canonical_version, Mapping):
            raise QAError("INVALID_QA_INPUT", "variant_version and canonical_version must be objects")
        variant = deepcopy(dict(variant_version))
        canonical = deepcopy(dict(canonical_version))
        if variant.get("org_id") != tenant or canonical.get("org_id") != tenant:
            raise QAError("TENANT_SCOPE_VIOLATION", "variant or canonical version is outside this organization")
        variant_id = _uuid(variant.get("id"), "subject_id")
        canonical_id = _uuid(variant.get("canonical_content_version_id"), "canonical_content_version_id")
        if canonical.get("id") != canonical_id:
            raise QAError("QA_SOURCE_MISMATCH", "variant references a different Canonical version")
        check_time = _time(evaluated_at, "evaluated_at") if evaluated_at is not None else datetime.now(timezone.utc)
        if check_time is None:
            raise QAError("INVALID_QA_INPUT", "evaluated_at must be timezone-aware ISO-8601")
        claims_list = list(claims or ())
        evidence_list = list(evidence or ())
        map_list = list(source_map or ())
        request_hash = _hash({"variant": variant, "canonical": canonical, "claims": claims_list,
                              "evidence": evidence_list, "source_map": map_list, "evaluated_at": _stamp(check_time)})
        with self._lock:
            prior = self._results.get((tenant, key))
            if prior is not None:
                if prior[0] != request_hash:
                    raise QAError("IDEMPOTENCY_KEY_REUSED", "QA request differs from prior request")
                return deepcopy(prior[1])
            findings: list[dict[str, Any]] = []

            def add(code: str, severity: str, path: str, message: str, observed: Any = None,
                    expected: Any = None, *, claim_id: str | None = None, evidence_id: str | None = None) -> None:
                finding = {"code": code, "severity": severity, "path": path, "message": message,
                           "observed": observed, "expected": expected}
                if claim_id is not None:
                    finding["claim_id"] = claim_id
                if evidence_id is not None:
                    finding["evidence_id"] = evidence_id
                findings.append(finding)

            variant_errors = list(_VARIANT_VALIDATOR.iter_errors(variant))
            for error in variant_errors:
                add("VARIANT_SCHEMA_INVALID", "error", "/" + "/".join(str(part) for part in error.path), error.message)
            if variant.get("status") == "withdrawn":
                add("VARIANT_WITHDRAWN", "error", "/status", "Variant version is withdrawn", variant.get("status"), "draft|localized|qa_pending|approved")
            if canonical.get("status") == "withdrawn" or canonical.get("freshness_status") == "withdrawn":
                add("CANONICAL_WITHDRAWN", "error", "/canonical_version/status", "Canonical source is withdrawn")

            source_text = _texts(canonical)
            variant_text = _texts(variant, variant=True)
            source_counts, variant_counts = _counts(source_text), _counts(variant_text)
            for kind in ("number", "code", "url"):
                source_tokens, target_tokens = source_counts[kind], variant_counts[kind]
                for token, expected_count in source_tokens.items():
                    observed_count = target_tokens.get(token, 0)
                    if observed_count < expected_count:
                        add(f"MISSING_{kind.upper()}", "error", f"/body/{kind}",
                            f"{kind} token is missing or reduced", observed_count, expected_count)
                for token, observed_count in target_tokens.items():
                    expected_count = source_tokens.get(token, 0)
                    if observed_count > expected_count:
                        add(f"ADDED_{kind.upper()}", "error", f"/body/{kind}",
                            f"{kind} token was added or changed", observed_count, expected_count)

            claim_by_id: dict[str, Mapping[str, Any]] = {}
            for index, claim in enumerate(claims_list):
                if not isinstance(claim, Mapping) or claim.get("org_id") != tenant:
                    raise QAError("TENANT_SCOPE_VIOLATION", "claim is outside this organization")
                claim_id = _uuid(claim.get("id"), f"claims[{index}].id")
                claim_by_id[claim_id] = claim
                for error in _CLAIM_VALIDATOR.iter_errors(dict(claim)):
                    add("CLAIM_SCHEMA_INVALID", "error", f"/claims/{index}", error.message, claim_id=claim_id)
                if claim.get("status") != "verified":
                    add("CLAIM_NOT_VERIFIED", "error", f"/claims/{index}/status", "Claim is not verified", claim.get("status"), "verified", claim_id=claim_id)
                freshness = claim.get("freshness_status")
                if freshness in {"stale", "withdrawn"}:
                    add("CLAIM_STALE", "error", f"/claims/{index}/freshness_status", "Claim is stale or withdrawn", freshness, "fresh|review_due", claim_id=claim_id)
                elif freshness == "review_due":
                    add("CLAIM_REVIEW_DUE", "warning", f"/claims/{index}/freshness_status", "Claim freshness needs review", freshness, "fresh", claim_id=claim_id)
                valid_from, valid_to = _time(claim.get("valid_from"), "claim.valid_from"), _time(claim.get("valid_to"), "claim.valid_to")
                if valid_from is not None and check_time < valid_from or valid_to is not None and check_time >= valid_to:
                    add("CLAIM_OUT_OF_DATE", "error", f"/claims/{index}/validity", "Claim is outside its validity interval", _stamp(check_time), {"valid_from": claim.get("valid_from"), "valid_to": claim.get("valid_to")}, claim_id=claim_id)
                review_due = _time(claim.get("review_due_at"), "claim.review_due_at")
                if review_due is not None and check_time >= review_due and freshness not in {"stale", "withdrawn"}:
                    add("CLAIM_REVIEW_DUE", "warning", f"/claims/{index}/review_due_at", "Claim review is due", claim.get("review_due_at"), "future review_due_at", claim_id=claim_id)
                if claim.get("applicable_versions") and canonical_id not in claim.get("applicable_versions", []):
                    add("CLAIM_VERSION_SCOPE", "error", f"/claims/{index}/applicable_versions", "Claim does not apply to this Canonical version", canonical_id, claim.get("applicable_versions"), claim_id=claim_id)
                if claim.get("applicable_locales") and variant.get("locale") not in claim.get("applicable_locales", []):
                    add("CLAIM_LOCALE_SCOPE", "error", f"/claims/{index}/applicable_locales", "Claim does not apply to this locale", variant.get("locale"), claim.get("applicable_locales"), claim_id=claim_id)

            evidence_by_claim: dict[str, list[tuple[str, Mapping[str, Any]]]] = {}
            for index, item in enumerate(evidence_list):
                if not isinstance(item, Mapping) or item.get("org_id") != tenant:
                    raise QAError("TENANT_SCOPE_VIOLATION", "evidence is outside this organization")
                evidence_id = _uuid(item.get("id"), f"evidence[{index}].id")
                claim_id = item.get("claim_id")
                if claim_id is not None:
                    claim_id = _uuid(claim_id, f"evidence[{index}].claim_id")
                    evidence_by_claim.setdefault(claim_id, []).append((evidence_id, item))
                for error in _EVIDENCE_VALIDATOR.iter_errors(dict(item)):
                    add("EVIDENCE_SCHEMA_INVALID", "error", f"/evidence/{index}", error.message, evidence_id=evidence_id)
                if item.get("status") not in {"captured", "valid"}:
                    add("EVIDENCE_NOT_VALID", "error", f"/evidence/{index}/status", "Evidence is not valid", item.get("status"), "captured|valid", evidence_id=evidence_id)
                valid_from, valid_to = _time(item.get("valid_from"), "evidence.valid_from"), _time(item.get("valid_to"), "evidence.valid_to")
                if valid_from is not None and check_time < valid_from or valid_to is not None and check_time >= valid_to:
                    add("EVIDENCE_OUT_OF_DATE", "error", f"/evidence/{index}/validity", "Evidence is outside its validity interval", _stamp(check_time), {"valid_from": item.get("valid_from"), "valid_to": item.get("valid_to")}, evidence_id=evidence_id)
                if not isinstance(item.get("quote"), str) or not item["quote"].strip():
                    add("EVIDENCE_QUOTE_MISSING", "error", f"/evidence/{index}/quote", "Evidence quote is required", item.get("quote"), "nonempty", evidence_id=evidence_id)
                if not isinstance(item.get("locator"), str) or not item["locator"].strip():
                    add("EVIDENCE_LOCATOR_MISSING", "error", f"/evidence/{index}/locator", "Evidence locator is required", item.get("locator"), "nonempty", evidence_id=evidence_id)
                if not isinstance(item.get("source_snapshot_id"), str):
                    add("EVIDENCE_SOURCE_MISSING", "error", f"/evidence/{index}/source_snapshot_id", "Source snapshot is required", item.get("source_snapshot_id"), "uuid", evidence_id=evidence_id)
                review_due = _time(item.get("review_due_at"), "evidence.review_due_at")
                if review_due is not None and check_time >= review_due and item.get("status") in {"captured", "valid"}:
                    add("EVIDENCE_REVIEW_DUE", "warning", f"/evidence/{index}/review_due_at", "Evidence review is due", item.get("review_due_at"), "future review_due_at", evidence_id=evidence_id)

            mapped_claims = {str(item.get("claim_id")) for item in map_list if isinstance(item, Mapping) and item.get("claim_id")}
            for linked_claim_id, linked_evidence in sorted(evidence_by_claim.items()):
                if linked_claim_id not in claim_by_id:
                    for evidence_id, _ in linked_evidence:
                        add("EVIDENCE_CLAIM_UNKNOWN", "error", "/evidence", "Evidence references an unknown Claim", linked_claim_id, "known claim id", evidence_id=evidence_id)
            for claim_id, claim in sorted(claim_by_id.items()):
                linked = evidence_by_claim.get(claim_id, [])
                if not linked:
                    add("CLAIM_EVIDENCE_MISSING", "error", "/claims", "Verified Claim has no linked Evidence", [], "at least one evidence", claim_id=claim_id)
                if claim_id not in mapped_claims:
                    add("CLAIM_NOT_MAPPED", "error", "/source_map", "Claim is not mapped into the Variant", [], claim_id, claim_id=claim_id)

            if self.terminology_port is not None:
                try:
                    terminology_findings = self.terminology_port.check(
                        org_id=tenant, source=canonical, variant=variant, locale=str(variant.get("locale", "")),
                    )
                except Exception as exc:
                    add("TERMINOLOGY_CHECK_ERROR", "warning", "/terminology", "Terminology Port failed and needs review", str(exc), "structured findings")
                else:
                    for item in terminology_findings or ():
                        if not isinstance(item, Mapping):
                            add("TERMINOLOGY_FINDING_INVALID", "warning", "/terminology", "Terminology Port returned an invalid finding", item, "object")
                            continue
                        add(str(item.get("code", "TERMINOLOGY_REVIEW")), str(item.get("severity", "warning")),
                            str(item.get("path", "/terminology")), str(item.get("message", "Terminology review required")),
                            item.get("observed"), item.get("expected"))

            findings.sort(key=lambda item: (item["code"], item["severity"], item["path"], item["message"], str(item.get("claim_id", "")), str(item.get("evidence_id", ""))))
            has_error = any(item["severity"] == "error" for item in findings)
            has_warning = any(item["severity"] == "warning" for item in findings)
            report = {
                "id": str(uuid4()), "org_id": tenant, "subject_type": "variant_version", "subject_id": variant_id,
                "rule_version": self.rule_version,
                "status": "failed" if has_error else "needs_review" if has_warning else "passed",
                "findings": findings, "created_at": _stamp(check_time),
            }
            errors = list(_REPORT_VALIDATOR.iter_errors(report))
            if errors:
                raise QAError("INVALID_QA_REPORT", errors[0].message)
            self.audit.append({"event_type": "qa.report.created", "org_id": tenant, "actor_id": actor,
                               "trace_id": trace, "idempotency_key": key, "input_hash": request_hash,
                               "output_hash": _hash(report), "status": report["status"]})
            self._results[(tenant, key)] = (request_hash, deepcopy(report))
            return deepcopy(report)


__all__ = ["QAError", "QAService", "TerminologyPort"]
