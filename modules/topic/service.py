"""Dependency-free topic taxonomy lifecycle with schema-backed contracts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any, Iterable, Mapping
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "packages" / "contracts" / "jsonschema" / "topic-taxonomy.schema.json"


class TopicError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _uuid(value: UUID | str, name: str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise TopicError("INVALID_TOPIC_TAXONOMY", f"{name} must be a UUID") from exc


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TopicError("INVALID_TOPIC_TAXONOMY", f"{name} is required")
    return value.strip()


def _items(values: Iterable[str], name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, Mapping)):
        raise TopicError("INVALID_TOPIC_TAXONOMY", f"{name} must be a sequence")
    result = tuple(dict.fromkeys(_text(value, name) for value in values))
    if not result:
        raise TopicError("INVALID_TOPIC_TAXONOMY", f"{name} must contain at least one item")
    return result


def _stamp(value: datetime | str | None = None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise TopicError("INVALID_TOPIC_TAXONOMY", "created_at must include a timezone")
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds")
    return _text(value, "created_at")


def _hash(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def validate_topic_taxonomy(value: Mapping[str, Any]) -> dict[str, Any]:
    candidate = dict(value)
    errors = sorted(Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")), format_checker=FormatChecker()).iter_errors(candidate), key=lambda item: list(item.path))
    if errors:
        location = ".".join(str(part) for part in errors[0].path) or "topic_taxonomy"
        raise TopicError("INVALID_TOPIC_TAXONOMY", f"{location}: {errors[0].message}")
    return candidate


@dataclass(frozen=True)
class TopicTaxonomy:
    id: UUID
    org_id: UUID
    key: str
    label: str
    technical_versions: tuple[str, ...]
    audiences: tuple[str, ...]
    status: str
    created_at: str
    version: int = 0
    tags: tuple[str, ...] = ()

    def as_contract(self) -> dict[str, Any]:
        return {"id": str(self.id), "org_id": str(self.org_id), "key": self.key, "label": self.label,
                "technical_versions": list(self.technical_versions), "audiences": list(self.audiences),
                "tags": list(self.tags), "status": self.status, "created_at": self.created_at}


class TopicTaxonomyService:
    transitions = {"draft": {"activate": "active", "retire": "retired"},
                   "active": {"retire": "retired"}, "retired": {}}

    def __init__(self, database: str | Path = ":memory:") -> None:
        from .infrastructure.taxonomy_schema import initialize

        self._connection = sqlite3.connect(str(database), check_same_thread=False)
        initialize(self._connection)
        self.taxonomies: dict[UUID, TopicTaxonomy] = {
            item.id: item for item in (
                _taxonomy(json.loads(row[0])) for row in self._connection.execute("SELECT payload FROM topic_taxonomies")
            )
        }
        self._commands: dict[tuple[UUID, str], tuple[str, TopicTaxonomy]] = {
            (UUID(row[0]), row[1]): (row[2], _taxonomy(json.loads(row[3])))
            for row in self._connection.execute(
                "SELECT org_id, idempotency_key, payload_hash, response FROM topic_commands"
            )
        }
        self._lock = RLock()

    def close(self) -> None:
        self._connection.close()

    def _persist(self, taxonomy: TopicTaxonomy, idem: str, digest: str, *, created: bool) -> None:
        payload = json.dumps({**taxonomy.as_contract(), "version": taxonomy.version}, sort_keys=True)
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            if created:
                self._connection.execute(
                    "INSERT INTO topic_taxonomies (id, org_id, taxonomy_key, version, payload) VALUES (?, ?, ?, ?, ?)",
                    (str(taxonomy.id), str(taxonomy.org_id), taxonomy.key, taxonomy.version, payload),
                )
            else:
                cursor = self._connection.execute(
                    "UPDATE topic_taxonomies SET taxonomy_key = ?, version = ?, payload = ? "
                    "WHERE id = ? AND org_id = ? AND version = ?",
                    (taxonomy.key, taxonomy.version, payload, str(taxonomy.id), str(taxonomy.org_id), taxonomy.version - 1),
                )
                if cursor.rowcount != 1:
                    raise TopicError("VERSION_CONFLICT", "taxonomy version changed")
            self._connection.execute(
                "INSERT INTO topic_commands (org_id, idempotency_key, payload_hash, response) VALUES (?, ?, ?, ?)",
                (str(taxonomy.org_id), idem, digest, payload),
            )
            self._connection.commit()
        except sqlite3.IntegrityError as exc:
            self._connection.rollback()
            raise TopicError("TOPIC_KEY_CONFLICT", "taxonomy key or idempotency key already exists") from exc
        except Exception:
            self._connection.rollback()
            raise

    def create(
        self, *, org_id: UUID | str, key: str, label: str,
        technical_versions: Iterable[str], audiences: Iterable[str],
        idempotency_key: str, tags: Iterable[str] = (), status: str = "draft",
        created_at: datetime | str | None = None,
    ) -> TopicTaxonomy:
        tenant = _uuid(org_id, "org_id")
        idem = _text(idempotency_key, "idempotency_key")
        normalized_key = _text(key, "key")
        normalized_label = _text(label, "label")
        versions = _items(technical_versions, "technical_versions")
        audience_values = _items(audiences, "audiences")
        tag_values = tuple(dict.fromkeys(_text(item, "tags") for item in tags))
        if status not in {"draft", "active", "retired"}:
            raise TopicError("INVALID_TOPIC_STATE", "status is invalid")
        command_hash = _hash({"key": normalized_key, "label": normalized_label, "technical_versions": versions,
                              "audiences": audience_values, "tags": tag_values, "status": status})
        with self._lock:
            prior = self._commands.get((tenant, idem))
            if prior is not None:
                if prior[0] != command_hash:
                    raise TopicError("IDEMPOTENCY_KEY_REUSED", "taxonomy idempotency key payload differs")
                return prior[1]
            if any(item.org_id == tenant and item.key == normalized_key for item in self.taxonomies.values()):
                raise TopicError("TOPIC_KEY_CONFLICT", "taxonomy key already exists in organization")
            taxonomy = TopicTaxonomy(uuid4(), tenant, normalized_key, normalized_label, versions, audience_values,
                                     status, _stamp(created_at), 0, tag_values)
            validate_topic_taxonomy(taxonomy.as_contract())
            self._persist(taxonomy, idem, command_hash, created=True)
            self.taxonomies[taxonomy.id] = taxonomy
            self._commands[(tenant, idem)] = (command_hash, taxonomy)
            return taxonomy

    def update(
        self, *, org_id: UUID | str, taxonomy_id: UUID | str, expected_version: int,
        idempotency_key: str, key: str | None = None, label: str | None = None,
        technical_versions: Iterable[str] | None = None, audiences: Iterable[str] | None = None,
        tags: Iterable[str] | None = None,
    ) -> TopicTaxonomy:
        tenant = _uuid(org_id, "org_id")
        current = self._get(taxonomy_id, tenant)
        idem = _text(idempotency_key, "idempotency_key")
        updated_values = {
            "key": _text(key, "key") if key is not None else current.key,
            "label": _text(label, "label") if label is not None else current.label,
            "technical_versions": _items(technical_versions, "technical_versions") if technical_versions is not None else current.technical_versions,
            "audiences": _items(audiences, "audiences") if audiences is not None else current.audiences,
            "tags": tuple(dict.fromkeys(_text(item, "tags") for item in tags)) if tags is not None else current.tags,
        }
        command_hash = _hash({"taxonomy_id": str(current.id), "expected_version": expected_version,
                              "key": _text(key, "key") if key is not None else None,
                              "label": _text(label, "label") if label is not None else None,
                              "technical_versions": updated_values["technical_versions"] if technical_versions is not None else None,
                              "audiences": updated_values["audiences"] if audiences is not None else None,
                              "tags": updated_values["tags"] if tags is not None else None})
        with self._lock:
            prior = self._commands.get((tenant, idem))
            if prior is not None:
                if prior[0] != command_hash:
                    raise TopicError("IDEMPOTENCY_KEY_REUSED", "taxonomy change idempotency key payload differs")
                return prior[1]
            if current.version != expected_version:
                raise TopicError("VERSION_CONFLICT", "taxonomy version changed")
            if current.status == "retired":
                raise TopicError("INVALID_TOPIC_STATE", "retired taxonomy cannot be changed")
            if updated_values["key"] != current.key and any(
                item.org_id == tenant and item.key == updated_values["key"] for item in self.taxonomies.values()
            ):
                raise TopicError("TOPIC_KEY_CONFLICT", "taxonomy key already exists in organization")
            updated = replace(current, **updated_values, version=current.version + 1)
            validate_topic_taxonomy(updated.as_contract())
            self._persist(updated, idem, command_hash, created=False)
            self.taxonomies[updated.id] = updated
            self._commands[(tenant, idem)] = (command_hash, updated)
            return updated

    def transition(self, *, org_id: UUID | str, taxonomy_id: UUID | str, action: str,
                   expected_version: int, idempotency_key: str) -> TopicTaxonomy:
        tenant = _uuid(org_id, "org_id")
        current = self._get(taxonomy_id, tenant)
        idem = _text(idempotency_key, "idempotency_key")
        action = _text(action, "action")
        command_hash = _hash({"taxonomy_id": str(current.id), "action": action, "expected_version": expected_version})
        with self._lock:
            prior = self._commands.get((tenant, idem))
            if prior is not None:
                if prior[0] != command_hash:
                    raise TopicError("IDEMPOTENCY_KEY_REUSED", "taxonomy transition idempotency key payload differs")
                return prior[1]
            if current.version != expected_version:
                raise TopicError("VERSION_CONFLICT", "taxonomy version changed")
            target = self.transitions.get(current.status, {}).get(action)
            if target is None:
                raise TopicError("INVALID_TOPIC_STATE", f"cannot {action} from {current.status}")
            updated = replace(current, status=target, version=current.version + 1)
            self._persist(updated, idem, command_hash, created=False)
            self.taxonomies[updated.id] = updated
            self._commands[(tenant, idem)] = (command_hash, updated)
            return updated

    def activate(self, **kwargs: Any) -> TopicTaxonomy:
        return self.transition(action="activate", **kwargs)

    def retire(self, **kwargs: Any) -> TopicTaxonomy:
        return self.transition(action="retire", **kwargs)

    def get(self, *, org_id: UUID | str, taxonomy_id: UUID | str) -> TopicTaxonomy:
        return self._get(taxonomy_id, _uuid(org_id, "org_id"))

    def list(self, *, org_id: UUID | str, status: str | None = None) -> tuple[TopicTaxonomy, ...]:
        tenant = _uuid(org_id, "org_id")
        return tuple(item for item in self.taxonomies.values() if item.org_id == tenant and (status is None or item.status == status))

    def _get(self, value: UUID | str, tenant: UUID) -> TopicTaxonomy:
        taxonomy = self.taxonomies.get(_uuid(value, "taxonomy_id"))
        if taxonomy is None or taxonomy.org_id != tenant:
            raise TopicError("TENANT_SCOPE_VIOLATION", "taxonomy does not belong to organization")
        return taxonomy


TopicService = TopicTaxonomyService


def _taxonomy(value: Mapping[str, Any]) -> TopicTaxonomy:
    return TopicTaxonomy(
        UUID(value["id"]), UUID(value["org_id"]), value["key"], value["label"],
        tuple(value["technical_versions"]), tuple(value["audiences"]), value["status"],
        value["created_at"], int(value["version"]), tuple(value.get("tags", [])),
    )

__all__ = ["TopicError", "TopicTaxonomy", "TopicTaxonomyService", "TopicService", "validate_topic_taxonomy"]
