"""Immutable glossary, approved translation memory, and deterministic token checks."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
from threading import RLock
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker

from .service import CanonicalVersionPort, ProductionError, _hash, _sections, _text, _uuid


_ROOT = Path(__file__).resolve().parents[2] / "packages/contracts/jsonschema"
_VALIDATORS = {
    name: Draft202012Validator(json.loads((_ROOT / f"{name}.schema.json").read_text(encoding="utf-8")),
                                format_checker=FormatChecker())
    for name in ("terminology-version", "translation-memory-entry", "variant-draft")
}
_CODE = re.compile(r"```[\s\S]*?```|`[^`\n]+`")
_URL = re.compile(r"https?://[^\s<>]+")
_NUMBER = re.compile(r"(?<![\w])[-+]?\d+(?:[.,]\d+)*(?:%|ms|s|kg|km|GB|MB)?(?![\w])")
_DRAFT_HASH_FIELDS = (
    "org_id", "canonical_content_id", "canonical_content_version_id", "source_content_hash",
    "locale", "market", "audience", "tone", "title", "abstract", "blocks", "transform_mode",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _source_hash(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _tokens(text: str) -> dict[str, Counter[str]]:
    code = _CODE.findall(text)
    remaining = _CODE.sub(" ", text)
    urls = _URL.findall(remaining)
    remaining = _URL.sub(" ", remaining)
    return {"code": Counter(code), "url": Counter(urls), "number": Counter(_NUMBER.findall(remaining))}


class TerminologyService:
    def __init__(self, *, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS production_terminology_versions ("
            "id TEXT PRIMARY KEY, org_id TEXT NOT NULL, locale TEXT NOT NULL, version_no INTEGER NOT NULL, "
            "content_hash TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL, "
            "UNIQUE(org_id, id), UNIQUE(org_id, locale, version_no), "
            "CHECK(version_no >= 1), CHECK(length(content_hash) = 64))"
        )
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS production_translation_memory ("
            "id TEXT PRIMARY KEY, org_id TEXT NOT NULL, locale TEXT NOT NULL, source_hash TEXT NOT NULL, "
            "target_text TEXT NOT NULL, approved_by TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL, "
            "UNIQUE(org_id, id), UNIQUE(org_id, locale, source_hash, target_text), CHECK(length(source_hash) = 64))"
        )
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS production_terminology_commands ("
            "org_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, "
            "actor_id TEXT NOT NULL, trace_id TEXT NOT NULL, response TEXT NOT NULL, "
            "PRIMARY KEY(org_id, idempotency_key), CHECK(length(request_hash) = 64))"
        )
        self.connection.execute("CREATE INDEX IF NOT EXISTS ix_terminology_locale ON production_terminology_versions(org_id, locale, version_no)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS ix_translation_memory_lookup ON production_translation_memory(org_id, locale, source_hash)")
        for table in ("production_terminology_versions", "production_translation_memory", "production_terminology_commands"):
            for action in ("UPDATE", "DELETE"):
                self.connection.execute(
                    f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} BEFORE {action} ON {table} "
                    f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
                )
        self.connection.commit()
        self._lock = RLock()

    def _prior(self, tenant: str, key: str, digest: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT request_hash, response FROM production_terminology_commands WHERE org_id = ? AND idempotency_key = ?",
            (tenant, key),
        ).fetchone()
        if row is None:
            return None
        if row["request_hash"] != digest:
            raise ProductionError("IDEMPOTENCY_KEY_REUSED", "terminology command differs from prior request")
        return json.loads(row["response"])

    def _save(self, tenant: str, key: str, digest: str, actor: str, trace: str,
              response: Mapping[str, Any]) -> None:
        self.connection.execute(
            "INSERT INTO production_terminology_commands (org_id, idempotency_key, request_hash, actor_id, trace_id, response) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tenant, key, digest, actor, trace, json.dumps(response, ensure_ascii=False, sort_keys=True)),
        )

    def create_glossary(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
                        idempotency_key: str, locale: str, entries: Sequence[Mapping[str, str]],
                        locked_product_names: Sequence[str] = ()) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key, locale = _text(trace_id, "trace_id", 256), _text(idempotency_key, "idempotency_key", 200), _text(locale, "locale", 64)
        if isinstance(entries, (str, bytes, Mapping)) or not isinstance(entries, Sequence):
            raise ProductionError("INVALID_TERMINOLOGY", "entries must be an array")
        if any(not isinstance(item, Mapping) for item in entries):
            raise ProductionError("INVALID_TERMINOLOGY", "each term entry must be an object")
        normalized = sorted(({"source": _text(item.get("source"), "source", 256),
                              "target": _text(item.get("target"), "target", 256)} for item in entries),
                            key=lambda item: item["source"].casefold())
        if len({item["source"].casefold() for item in normalized}) != len(normalized):
            raise ProductionError("INVALID_TERMINOLOGY", "source terms must be unique")
        if isinstance(locked_product_names, (str, bytes)) or not isinstance(locked_product_names, Sequence):
            raise ProductionError("INVALID_TERMINOLOGY", "locked names must be an array")
        locked = sorted({_text(name, "locked_product_name", 256) for name in locked_product_names})
        digest = _hash({"locale": locale, "entries": normalized, "locked_product_names": locked})
        with self._lock:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self.connection.commit()
                    return prior
                row = self.connection.execute(
                    "SELECT COALESCE(MAX(version_no), 0) FROM production_terminology_versions WHERE org_id = ? AND locale = ?",
                    (tenant, locale),
                ).fetchone()
                version = {
                    "id": str(uuid4()), "org_id": tenant, "locale": locale,
                    "version_no": int(row[0]) + 1, "entries": normalized,
                    "locked_product_names": locked, "content_hash": digest,
                    "created_by": actor, "created_at": _now(),
                }
                _VALIDATORS["terminology-version"].validate(version)
                self.connection.execute(
                    "INSERT INTO production_terminology_versions (id, org_id, locale, version_no, content_hash, created_by, created_at, payload) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (version["id"], tenant, locale, version["version_no"], digest, actor,
                     version["created_at"], json.dumps(version, ensure_ascii=False, sort_keys=True)),
                )
                self._save(tenant, key, digest, actor, trace, version)
                self.connection.commit()
                return version
            except Exception:
                self.connection.rollback()
                raise

    def get_glossary(self, *, org_id: UUID | str, version_id: UUID | str) -> dict[str, Any]:
        tenant, identity = _uuid(org_id, "org_id"), _uuid(version_id, "version_id")
        row = self.connection.execute(
            "SELECT payload FROM production_terminology_versions WHERE org_id = ? AND id = ?",
            (tenant, identity),
        ).fetchone()
        if row is None:
            raise ProductionError("TENANT_SCOPE_VIOLATION", "glossary version is outside this organization")
        return json.loads(row["payload"])

    def add_memory(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
                   idempotency_key: str, locale: str, source_text: str, target_text: str) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key, locale = _text(trace_id, "trace_id", 256), _text(idempotency_key, "idempotency_key", 200), _text(locale, "locale", 64)
        source, target = _text(source_text, "source_text", 10000), _text(target_text, "target_text", 10000)
        source_hash = _source_hash(source)
        digest = _hash({"locale": locale, "source_hash": source_hash, "target_text": target})
        with self._lock:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self.connection.commit()
                    return prior
                row = self.connection.execute(
                    "SELECT payload FROM production_translation_memory WHERE org_id = ? AND locale = ? "
                    "AND source_hash = ? AND target_text = ?", (tenant, locale, source_hash, target),
                ).fetchone()
                if row is not None:
                    entry = json.loads(row["payload"])
                else:
                    entry = {
                        "id": str(uuid4()), "org_id": tenant, "locale": locale,
                        "source_hash": source_hash, "target_text": target, "status": "approved",
                        "approved_by": actor, "created_at": _now(),
                    }
                    _VALIDATORS["translation-memory-entry"].validate(entry)
                    self.connection.execute(
                        "INSERT INTO production_translation_memory (id, org_id, locale, source_hash, target_text, approved_by, created_at, payload) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (entry["id"], tenant, locale, source_hash, target, actor, entry["created_at"],
                         json.dumps(entry, ensure_ascii=False, sort_keys=True)),
                    )
                self._save(tenant, key, digest, actor, trace, entry)
                self.connection.commit()
                return entry
            except Exception:
                self.connection.rollback()
                raise

    def suggestions(self, *, org_id: UUID | str, locale: str, source_text: str) -> list[dict[str, Any]]:
        tenant, locale = _uuid(org_id, "org_id"), _text(locale, "locale", 64)
        source_hash = _source_hash(_text(source_text, "source_text", 10000))
        rows = self.connection.execute(
            "SELECT payload FROM production_translation_memory WHERE org_id = ? AND locale = ? AND source_hash = ? "
            "ORDER BY created_at, id", (tenant, locale, source_hash),
        ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def check_translation(self, *, org_id: UUID | str, glossary_version_id: UUID | str,
                          source_text: str, target_text: str) -> list[dict[str, str]]:
        glossary = self.get_glossary(org_id=org_id, version_id=glossary_version_id)
        source, target = _text(source_text, "source_text", 10000), _text(target_text, "target_text", 10000)
        before, after = _tokens(source), _tokens(target)
        issues: list[dict[str, str]] = []
        for kind in ("code", "url", "number"):
            for token, count in sorted((before[kind] - after[kind]).items()):
                issues.append({"code": f"MISSING_{kind.upper()}", "token": token, "count": str(count)})
            for token, count in sorted((after[kind] - before[kind]).items()):
                issues.append({"code": f"ADDED_{kind.upper()}", "token": token, "count": str(count)})
        for name in glossary["locked_product_names"]:
            if source.count(name) > target.count(name):
                issues.append({"code": "PRODUCT_NAME_CHANGED", "token": name,
                               "count": str(source.count(name) - target.count(name))})
        for entry in glossary["entries"]:
            if entry["source"].casefold() in source.casefold() and entry["target"].casefold() not in target.casefold():
                issues.append({"code": "PREFERRED_TERM_MISSING", "token": entry["target"], "count": "1"})
        return issues

    def check_draft(self, *, org_id: UUID | str, glossary_version_id: UUID | str,
                    draft: Mapping[str, Any], canonical_versions: CanonicalVersionPort) -> dict[str, Any]:
        tenant = _uuid(org_id, "org_id")
        _VALIDATORS["variant-draft"].validate(draft)
        if draft["org_id"] != tenant:
            raise ProductionError("TENANT_SCOPE_VIOLATION", "draft is outside this organization")
        if _hash({name: draft[name] for name in _DRAFT_HASH_FIELDS}) != draft["draft_hash"]:
            raise ProductionError("INVALID_VARIANT_DRAFT", "draft hash does not match content")
        glossary = self.get_glossary(org_id=tenant, version_id=glossary_version_id)
        if glossary["locale"] != draft["locale"]:
            raise ProductionError("TERMINOLOGY_LOCALE_MISMATCH", "glossary locale differs from draft")
        source = canonical_versions.get_version(org_id=tenant, version_id=draft["canonical_content_version_id"])
        if (not isinstance(source, Mapping) or source.get("org_id") != tenant or
            source.get("id") != draft["canonical_content_version_id"]):
            raise ProductionError("TENANT_SCOPE_VIOLATION", "canonical source is outside this organization")
        if (source.get("canonical_content_id") != draft["canonical_content_id"] or
            source.get("content_hash") != draft["source_content_hash"]):
            raise ProductionError("CANONICAL_SOURCE_CHANGED", "draft source version changed")
        sections = _sections(source)
        if len(sections) != len(draft["blocks"]):
            raise ProductionError("INVALID_VARIANT_DRAFT", "draft block count differs from source")
        issues: list[dict[str, str]] = []
        memory: dict[str, list[dict[str, Any]]] = {}
        for section, block in zip(sections, draft["blocks"], strict=True):
            if (block["source_key"] != section["key"] or
                block["block_id"] != (section.get("block_id") or section["key"]) or
                block["source_text_hash"] != _hash(section["content"]) or
                block["claim_id"] != section.get("claim_id")):
                raise ProductionError("INVALID_VARIANT_DRAFT", "draft block source mapping differs")
            for issue in self.check_translation(
                org_id=tenant, glossary_version_id=glossary_version_id,
                source_text=section["content"], target_text=block["localized_text"],
            ):
                issues.append({"block_id": block["block_id"], **issue})
            memory[block["block_id"]] = self.suggestions(
                org_id=tenant, locale=draft["locale"], source_text=section["content"],
            )
        return {"glossary_version_id": glossary["id"], "draft_id": draft["id"],
                "passed": not issues, "issues": issues, "memory_suggestions": memory}


__all__ = ["TerminologyService"]
