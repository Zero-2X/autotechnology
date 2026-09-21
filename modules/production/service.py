"""Generate reviewable Variant drafts through a replaceable TransformPort."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from threading import RLock
from typing import Any, Mapping, Protocol
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker


_SCHEMA = json.loads((Path(__file__).resolve().parents[2] /
                      "packages/contracts/jsonschema/variant-draft.schema.json").read_text(encoding="utf-8"))
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FormatChecker())
_HASH = re.compile(r"^[0-9a-fA-F]{64}$")


class ProductionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CanonicalVersionPort(Protocol):
    def get_version(self, *, org_id: UUID | str, version_id: UUID | str) -> Mapping[str, Any]: ...


class TransformPort(Protocol):
    def transform(self, *, org_id: str, source_version: Mapping[str, Any], locale: str,
                  market: str, audience: str, tone: str) -> Mapping[str, Any]: ...


def _hash(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _text(value: object, name: str, limit: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise ProductionError("INVALID_VARIANT_REQUEST", f"{name} must be nonempty text")
    return value.strip()


def _uuid(value: UUID | str, name: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise ProductionError("INVALID_VARIANT_REQUEST", f"{name} must be a UUID") from exc


def _sections(source: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    sections = source.get("sections")
    if not isinstance(sections, list) or not sections:
        raise ProductionError("NO_TRANSFORMABLE_SECTIONS", "canonical version has no sections")
    if any(not isinstance(item, Mapping) or type(item.get("position")) is not int for item in sections):
        raise ProductionError("INVALID_CANONICAL_SOURCE", "section position is invalid")
    ordered = sorted(sections, key=lambda item: (item.get("position", 0), item.get("key", "")))
    keys: set[str] = set()
    for section in ordered:
        if not isinstance(section, Mapping):
            raise ProductionError("INVALID_CANONICAL_SOURCE", "section must be an object")
        key = section.get("key")
        content = section.get("content")
        if not isinstance(key, str) or not key or key in keys or not isinstance(content, str) or not content:
            raise ProductionError("INVALID_CANONICAL_SOURCE", "section key or text is invalid")
        keys.add(key)
    return ordered


class RuleTransformPort:
    """M1 rule implementation: copy source text exactly and require review."""

    def transform(self, *, org_id: str, source_version: Mapping[str, Any], locale: str,
                  market: str, audience: str, tone: str) -> Mapping[str, Any]:
        return {
            "org_id": org_id,
            "canonical_content_version_id": source_version["id"],
            "title": source_version["title"], "abstract": source_version.get("abstract", ""),
            "blocks": [
                {"block_id": section.get("block_id") or section["key"],
                 "source_key": section["key"], "localized_text": section["content"],
                 "claim_id": section.get("claim_id"), "disclosure": None}
                for section in _sections(source_version)
            ],
            "transform_mode": "rule_copy", "needs_review": True,
        }


class VariantDraftService:
    """Transient draft use case; PROD-002 owns persisted Variant facts."""

    def __init__(self, *, canonical_versions: CanonicalVersionPort,
                 transform_port: TransformPort | None = None) -> None:
        self.canonical_versions = canonical_versions
        self.transform_port = transform_port or RuleTransformPort()
        self._results: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
        self.audit: list[dict[str, Any]] = []
        self._lock = RLock()

    def generate(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
                 idempotency_key: str, canonical_content_version_id: UUID | str,
                 locale: str, market: str, audience: str, tone: str) -> dict[str, Any]:
        tenant = _uuid(org_id, "org_id")
        actor = _uuid(actor_id, "actor_id")
        version_id = _uuid(canonical_content_version_id, "canonical_content_version_id")
        trace = _text(trace_id, "trace_id", 256)
        key = _text(idempotency_key, "idempotency_key", 200)
        locale, market = _text(locale, "locale", 64), _text(market, "market", 64)
        audience, tone = _text(audience, "audience", 256), _text(tone, "tone", 128)
        request = {"canonical_content_version_id": version_id, "locale": locale,
                   "market": market, "audience": audience, "tone": tone}
        digest = _hash(request)
        with self._lock:
            previous = self._results.get((tenant, key))
            if previous is not None:
                if previous[0] != digest:
                    raise ProductionError("IDEMPOTENCY_KEY_REUSED", "variant request differs from prior request")
                return deepcopy(previous[1])
            source = self.canonical_versions.get_version(org_id=tenant, version_id=version_id)
            if not isinstance(source, Mapping) or source.get("org_id") != tenant or source.get("id") != version_id:
                raise ProductionError("TENANT_SCOPE_VIOLATION", "canonical version is outside this organization")
            if source.get("status") == "withdrawn" or source.get("freshness_status") == "withdrawn":
                raise ProductionError("CANONICAL_VERSION_WITHDRAWN", "withdrawn canonical version cannot be transformed")
            content_hash = source.get("content_hash")
            if not isinstance(content_hash, str) or not _HASH.fullmatch(content_hash):
                raise ProductionError("INVALID_CANONICAL_SOURCE", "canonical content hash is invalid")
            content_id = _uuid(source.get("canonical_content_id"), "canonical_content_id")
            sections = _sections(source)
            candidate = self.transform_port.transform(
                org_id=tenant, source_version=deepcopy(source), locale=locale,
                market=market, audience=audience, tone=tone,
            )
            self._validate_candidate(candidate, tenant, version_id, sections)
            blocks = []
            for section, raw in zip(sections, candidate["blocks"], strict=True):
                block = dict(raw)
                block["source_text_hash"] = _hash(section["content"])
                blocks.append(block)
            material = {
                "org_id": tenant, "canonical_content_id": content_id,
                "canonical_content_version_id": version_id, "source_content_hash": content_hash.lower(),
                "locale": locale, "market": market, "audience": audience, "tone": tone,
                "title": candidate["title"], "abstract": candidate["abstract"], "blocks": blocks,
                "transform_mode": candidate["transform_mode"],
            }
            draft = {
                "id": str(uuid4()), **material, "status": "draft", "needs_review": True,
                "draft_hash": _hash(material), "created_by": actor, "trace_id": trace,
                "created_at": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
            }
            errors = list(_VALIDATOR.iter_errors(draft))
            if errors:
                raise ProductionError("INVALID_VARIANT_DRAFT", errors[0].message)
            self.audit.append({
                "event_type": "production.variant_draft.generated", "org_id": tenant,
                "actor_id": actor, "trace_id": trace, "idempotency_key": key,
                "input_hash": digest, "output_hash": draft["draft_hash"],
                "canonical_content_version_id": version_id,
            })
            self._results[(tenant, key)] = (digest, deepcopy(draft))
            return deepcopy(draft)

    @staticmethod
    def _validate_candidate(candidate: Mapping[str, Any], tenant: str, version_id: str,
                            sections: list[Mapping[str, Any]]) -> None:
        if not isinstance(candidate, Mapping):
            raise ProductionError("INVALID_TRANSFORM_OUTPUT", "TransformPort must return an object")
        allowed = {"org_id", "canonical_content_version_id", "title", "abstract", "blocks", "transform_mode", "needs_review"}
        if set(candidate) != allowed or candidate.get("org_id") != tenant or candidate.get("canonical_content_version_id") != version_id:
            raise ProductionError("INVALID_TRANSFORM_OUTPUT", "TransformPort returned invalid ownership or fields")
        if candidate.get("needs_review") is not True or not isinstance(candidate.get("title"), str) or not candidate["title"]:
            raise ProductionError("INVALID_TRANSFORM_OUTPUT", "TransformPort must return a reviewable title")
        if not isinstance(candidate.get("abstract"), str) or not isinstance(candidate.get("transform_mode"), str) or not candidate["transform_mode"]:
            raise ProductionError("INVALID_TRANSFORM_OUTPUT", "TransformPort metadata is invalid")
        blocks = candidate.get("blocks")
        if not isinstance(blocks, list) or len(blocks) != len(sections):
            raise ProductionError("INVALID_TRANSFORM_OUTPUT", "TransformPort changed the source block count")
        for section, block in zip(sections, blocks, strict=True):
            if not isinstance(block, Mapping) or set(block) != {"block_id", "source_key", "localized_text", "claim_id", "disclosure"}:
                raise ProductionError("INVALID_TRANSFORM_OUTPUT", "TransformPort block fields are invalid")
            if block["source_key"] != section["key"] or block["block_id"] != (section.get("block_id") or section["key"]):
                raise ProductionError("INVALID_TRANSFORM_OUTPUT", "TransformPort changed the source mapping")
            if block["claim_id"] != section.get("claim_id") or not isinstance(block["localized_text"], str) or not block["localized_text"]:
                raise ProductionError("INVALID_TRANSFORM_OUTPUT", "TransformPort changed claim mapping or omitted text")


__all__ = ["CanonicalVersionPort", "ProductionError", "RuleTransformPort", "TransformPort", "VariantDraftService"]
