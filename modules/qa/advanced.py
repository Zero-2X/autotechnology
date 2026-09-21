"""Deterministic similarity, disclosure, duplication, and rights checks for QA-002."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from difflib import SequenceMatcher
import json
from pathlib import Path
from re import compile as regex
from threading import RLock
from typing import Any, Mapping, Protocol, Sequence
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker

from .service import (
    QAError,
    _REPORT_VALIDATOR,
    _hash,
    _stamp,
    _text,
    _texts,
    _time,
    _uuid,
)


_ROOT = Path(__file__).resolve().parents[2]
_VARIANT_VALIDATOR = Draft202012Validator(
    json.loads((_ROOT / "packages/contracts/jsonschema/variant-version.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
_RIGHTS_VALIDATOR = Draft202012Validator(
    json.loads((_ROOT / "packages/contracts/jsonschema/rights-record-version.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
_TOKEN = regex(r"[\w]+(?:[-'][\w]+)*", flags=0)
_AI_LABEL = regex(r"(?:\bai\b|artificial\s+intelligence|machine[- ]generated|ai[- ]generated|人工智能|生成式)", flags=2)


class SimilarityPort(Protocol):
    def score(self, *, source: str, variant: str, locale: str) -> float | Mapping[str, Any]: ...


class RightsPort(Protocol):
    def check(self, *, org_id: str, variant: Mapping[str, Any], rights_versions: Sequence[Mapping[str, Any]],
              media: str, permitted_use: str, evaluated_at: str) -> Mapping[str, Any]: ...


def _tokens(text: str) -> list[str]:
    return [item.casefold() for item in _TOKEN.findall(text)]


def _similarity(source: str, variant: str) -> float:
    left, right = _tokens(source), _tokens(variant)
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return round(SequenceMatcher(a=left, b=right, autojunk=False).ratio(), 6)


def _disclosure_text(variant: Mapping[str, Any]) -> str:
    values: list[str] = []
    if isinstance(variant.get("disclosure"), str):
        values.append(variant["disclosure"])
    body = variant.get("body")
    blocks = body.get("blocks", []) if isinstance(body, Mapping) else []
    if isinstance(blocks, list):
        for block in blocks:
            if isinstance(block, Mapping) and isinstance(block.get("disclosure"), str):
                values.append(block["disclosure"])
    return " ".join(value.strip() for value in values if value.strip())


def _duplicate_blocks(variant: Mapping[str, Any]) -> list[tuple[str, str]]:
    body = variant.get("body")
    blocks = body.get("blocks", []) if isinstance(body, Mapping) else []
    seen: dict[str, str] = {}
    duplicate_pairs: list[tuple[str, str]] = []
    if not isinstance(blocks, list):
        return duplicate_pairs
    for block in blocks:
        if not isinstance(block, Mapping) or not isinstance(block.get("localized_text"), str):
            continue
        normalized = " ".join(_tokens(block["localized_text"]))
        if not normalized:
            continue
        block_id = str(block.get("block_id", ""))
        if normalized in seen:
            duplicate_pairs.append((seen[normalized], block_id))
        else:
            seen[normalized] = block_id
    return duplicate_pairs


class AdvancedQAService:
    """Run deterministic QA-002 checks over immutable projections."""

    rule_version = "qa-002/v1"

    def __init__(self, *, similarity_port: SimilarityPort | None = None,
                 rights_port: RightsPort | None = None) -> None:
        self.similarity_port = similarity_port
        self.rights_port = rights_port
        self.audit: list[dict[str, Any]] = []
        self._results: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
        self._lock = RLock()

    def check_variant(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        variant_version: Mapping[str, Any], canonical_version: Mapping[str, Any],
        existing_variants: Sequence[Mapping[str, Any]] = (),
        rights_versions: Sequence[Mapping[str, Any]] = (),
        ai_generated: bool = False, advertising_required: bool = False,
        required_ad_disclosure: str | None = None, rights_required: bool = False,
        media: str = "text", permitted_use: str = "commercial",
        min_similarity: float = 0.0, duplicate_similarity: float = 0.92,
        policy: Mapping[str, Any] | None = None,
        evaluated_at: datetime | str | None = None,
    ) -> dict[str, Any]:
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
        if policy is not None and not isinstance(policy, Mapping):
            raise QAError("INVALID_QA_INPUT", "policy must be an object")
        config: dict[str, Any] = {
            "min_similarity": min_similarity, "duplicate_similarity": duplicate_similarity,
            "ai_generated": ai_generated, "advertising_required": advertising_required,
            "required_ad_disclosure": required_ad_disclosure, "rights_required": rights_required,
            "media": media, "permitted_use": permitted_use,
        }
        config.update(dict(policy or {}))
        for name in ("min_similarity", "duplicate_similarity"):
            value = config.get(name)
            if type(value) not in (int, float) or not 0 <= value <= 1:
                raise QAError("INVALID_QA_INPUT", f"{name} must be between 0 and 1")
        if not isinstance(config.get("media"), str) or not config["media"].strip():
            raise QAError("INVALID_QA_INPUT", "media must be nonempty text")
        if not isinstance(config.get("permitted_use"), str) or config["permitted_use"] not in {"research", "derivative", "commercial"}:
            raise QAError("INVALID_QA_INPUT", "permitted_use is invalid")
        existing_list, rights_list = list(existing_variants or ()), list(rights_versions or ())
        request_hash = _hash({
            "variant": variant, "canonical": canonical, "existing_variants": existing_list,
            "rights_versions": rights_list, "config": config, "evaluated_at": _stamp(check_time),
        })
        with self._lock:
            prior = self._results.get((tenant, key))
            if prior is not None:
                if prior[0] != request_hash:
                    raise QAError("IDEMPOTENCY_KEY_REUSED", "QA request differs from prior request")
                return deepcopy(prior[1])
            findings: list[dict[str, Any]] = []

            def add(code: str, severity: str, path: str, message: str, observed: Any = None,
                    expected: Any = None, *, object_id: str | None = None) -> None:
                finding: dict[str, Any] = {
                    "code": code, "severity": severity, "path": path, "message": message,
                    "observed": observed, "expected": expected,
                }
                if object_id is not None:
                    finding["object_id"] = object_id
                findings.append(finding)

            for error in _VARIANT_VALIDATOR.iter_errors(variant):
                add("VARIANT_SCHEMA_INVALID", "error", "/" + "/".join(str(part) for part in error.path), error.message)
            if variant.get("status") == "withdrawn":
                add("VARIANT_WITHDRAWN", "error", "/status", "Variant version is withdrawn", variant.get("status"), "usable status")

            source_text, variant_text = _texts(canonical), _texts(variant, variant=True)
            similarity = _similarity(source_text, variant_text)
            similarity_unavailable = False
            if self.similarity_port is not None:
                try:
                    port_result = self.similarity_port.score(source=source_text, variant=variant_text, locale=str(variant.get("locale", "")))
                    similarity = float(port_result.get("score") if isinstance(port_result, Mapping) else port_result)
                except Exception as exc:
                    add("SIMILARITY_CHECK_ERROR", "warning", "/similarity", "Similarity Port failed and needs review", str(exc), "finite score")
                    similarity_unavailable = True
                else:
                    if not 0 <= similarity <= 1:
                        add("SIMILARITY_SCORE_INVALID", "warning", "/similarity", "Similarity Port returned an invalid score", similarity, "0..1")
                        similarity_unavailable = True
                        similarity = max(0.0, min(1.0, similarity))
            if not similarity_unavailable and similarity < float(config["min_similarity"]):
                add("SIMILARITY_TOO_LOW", "error", "/similarity", "Variant similarity is below the required threshold", round(similarity, 6), config["min_similarity"])

            for index, existing in enumerate(existing_list):
                if not isinstance(existing, Mapping) or existing.get("org_id") != tenant:
                    raise QAError("TENANT_SCOPE_VIOLATION", "existing Variant is outside this organization")
                existing_id = _uuid(existing.get("id"), f"existing_variants[{index}].id")
                if existing_id == variant_id:
                    continue
                score = _similarity(_texts(existing, variant=True), variant_text)
                if score >= float(config["duplicate_similarity"]):
                    add("DUPLICATE_VARIANT", "error", f"/existing_variants/{index}", "Variant is too similar to an existing version", {"id": existing_id, "score": round(score, 6)}, f"below {config['duplicate_similarity']}", object_id=existing_id)

            for first, second in _duplicate_blocks(variant):
                add("DUPLICATE_BLOCK", "error", "/body/blocks", "Variant repeats an identical block", {"first": first, "second": second}, "unique block text", object_id=second)

            disclosure = _disclosure_text(variant)
            if bool(config.get("ai_generated")) and not _AI_LABEL.search(disclosure):
                add("AI_LABEL_MISSING", "error", "/disclosure", "AI generated content requires an AI disclosure", disclosure or None, "AI or artificial intelligence label")
            if bool(config.get("advertising_required")):
                if not disclosure:
                    add("AD_DISCLOSURE_MISSING", "error", "/disclosure", "Advertising content requires a disclosure", None, "nonempty disclosure")
                elif config.get("required_ad_disclosure") and str(config["required_ad_disclosure"]).casefold() not in disclosure.casefold():
                    add("AD_DISCLOSURE_MISMATCH", "error", "/disclosure", "Required advertising disclosure text is missing", disclosure, config["required_ad_disclosure"])

            allowed_rights = False
            rights_details: list[dict[str, Any]] = []
            if rights_list:
                for index, rights in enumerate(rights_list):
                    if not isinstance(rights, Mapping) or rights.get("org_id") != tenant:
                        raise QAError("TENANT_SCOPE_VIOLATION", "rights version is outside this organization")
                    rights_id = _uuid(rights.get("id"), f"rights_versions[{index}].id")
                    errors = list(_RIGHTS_VALIDATOR.iter_errors(dict(rights)))
                    if errors:
                        add("RIGHTS_SCHEMA_INVALID", "error", f"/rights_versions/{index}", errors[0].message, object_id=rights_id)
                        continue
                    reasons: list[str] = []
                    if rights.get("status") != "verified":
                        reasons.append("status")
                    valid_from, valid_to = _time(rights.get("valid_from"), "rights.valid_from"), _time(rights.get("valid_to"), "rights.valid_to")
                    if valid_from is not None and check_time < valid_from:
                        reasons.append("not_yet_valid")
                    if valid_to is not None and check_time >= valid_to:
                        reasons.append("expired")
                    if variant.get("market") not in rights.get("permitted_regions", []):
                        reasons.append("region")
                    if variant.get("locale") not in rights.get("permitted_locales", []):
                        reasons.append("locale")
                    if config["media"] not in rights.get("permitted_media", []):
                        reasons.append("media")
                    levels = {"research": 0, "derivative": 1, "commercial": 2}
                    if levels.get(str(config["permitted_use"]), -1) > levels.get(str(rights.get("permitted_use")), -1):
                        reasons.append("use")
                    rights_details.append({"id": rights_id, "reasons": reasons})
                    if not reasons:
                        allowed_rights = True
            if bool(config.get("rights_required")) and not rights_list:
                add("RIGHTS_MISSING", "error", "/rights_versions", "Required material rights are missing", [], "at least one rights version")
            elif bool(config.get("rights_required")) and not allowed_rights:
                add("RIGHTS_NOT_ALLOWED", "error", "/rights_versions", "No rights version allows this Variant scope", rights_details, "one verified usable rights version")
            elif rights_list and not allowed_rights:
                add("RIGHTS_NOT_ALLOWED", "error", "/rights_versions", "Provided rights versions do not allow this Variant scope", rights_details, "one verified usable rights version")

            if self.rights_port is not None and (rights_list or bool(config.get("rights_required"))):
                try:
                    port_result = self.rights_port.check(
                        org_id=tenant, variant=variant, rights_versions=rights_list,
                        media=str(config["media"]), permitted_use=str(config["permitted_use"]), evaluated_at=_stamp(check_time),
                    )
                except Exception as exc:
                    add("RIGHTS_CHECK_ERROR", "warning", "/rights_versions", "Rights Port failed and needs review", str(exc), "structured authorization result")
                else:
                    if not isinstance(port_result, Mapping) or port_result.get("allowed") is not True:
                        add("RIGHTS_PORT_BLOCKED", "error", "/rights_versions", "Rights Port did not authorize this Variant", port_result, {"allowed": True})

            findings.sort(key=lambda item: (item["code"], item["severity"], item["path"], item["message"], str(item.get("object_id", ""))))
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


__all__ = ["AdvancedQAService", "RightsPort", "SimilarityPort"]
