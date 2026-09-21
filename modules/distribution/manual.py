"""Deterministic ManualAdapter export assembly for DIST-003A."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from threading import RLock
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker
from pathlib import Path
from hashlib import sha256

from .service import DistributionError, _hash, _stamp, _text, _time, _uuid, _validate


_ROOT = Path(__file__).resolve().parents[2]
_EVENT_VALIDATOR = Draft202012Validator(
    json.loads((_ROOT / "packages/contracts/events/event-envelope.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _file_hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


class ManualAdapter:
    """Build a private export artifact without writing public or platform state."""

    def __init__(self) -> None:
        self.packages: dict[tuple[str, str], dict[str, Any]] = {}
        self.files: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.events: list[dict[str, Any]] = []
        self.audit: list[dict[str, Any]] = []
        self._commands: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
        self._lock = RLock()

    def export(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        publication_intent: Mapping[str, Any], content: Mapping[str, Any] | None = None,
        media: Sequence[Mapping[str, Any]] = (), checklist: Sequence[Mapping[str, Any]] = (),
        evidence: Sequence[Mapping[str, Any]] = (), approval_refs: Sequence[UUID | str] = (),
        content_version_refs: Sequence[UUID | str] = (), expires_at: datetime | str | None = None,
        generated_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        if not isinstance(publication_intent, Mapping):
            raise DistributionError("INVALID_MANUAL_EXPORT", "publication_intent must be an object")
        if publication_intent.get("org_id") != tenant:
            raise DistributionError("TENANT_SCOPE_VIOLATION", "publication intent is outside this organization")
        intent_id = _uuid(publication_intent.get("id"), "publication_intent.id")
        payload = deepcopy(dict(content if content is not None else publication_intent.get("payload_snapshot", {})))
        if not isinstance(payload, Mapping):
            raise DistributionError("INVALID_MANUAL_EXPORT", "content must be an object")
        required = {"title", "body", "tags", "disclosure"}
        if set(payload) != required or not isinstance(payload["title"], str) or not payload["title"].strip() or not isinstance(payload["body"], Mapping) or not isinstance(payload["tags"], Sequence) or isinstance(payload["tags"], (str, bytes)):
            raise DistributionError("INVALID_MANUAL_EXPORT", "content must contain title, body, tags and disclosure")
        if any(not isinstance(item, str) or not item.strip() for item in payload["tags"]):
            raise DistributionError("INVALID_MANUAL_EXPORT", "tags must contain nonempty text")
        normalized_media = self._media(media)
        normalized_checklist = self._checklist(checklist)
        normalized_evidence = self._evidence(evidence)
        refs = [_uuid(item, "content_version_ref") for item in content_version_refs]
        if not refs:
            refs = [_uuid(publication_intent.get("variant_version_id"), "variant_version_id")]
            refs.extend(_uuid(item, "asset_version_id") for item in publication_intent.get("asset_version_ids", []))
        approvals = [_uuid(item, "approval_ref") for item in approval_refs]
        generated = _time(generated_at, "generated_at") or datetime.now(timezone.utc)
        expires = _time(expires_at, "expires_at") or generated + timedelta(days=7)
        if expires <= generated:
            raise DistributionError("INVALID_MANUAL_EXPORT", "expires_at must be after generated_at")
        manifest = {
            "schema_version": 1, "publication_intent_id": intent_id,
            "title": payload["title"], "body": deepcopy(dict(payload["body"])),
            "media": normalized_media, "tags": list(payload["tags"]), "disclosure": payload["disclosure"],
            "checklist": normalized_checklist, "evidence": normalized_evidence,
            "payload_snapshot_hash": _hash(payload), "generated_at": _stamp(generated),
        }
        manifest_text = _canonical(manifest)
        files = [
            {"name": "manifest.json", "kind": "manifest", "storage_object_ref": "", "sha256": _file_hash(manifest_text),
             "content": manifest_text},
            {"name": "content/title.txt", "kind": "title", "storage_object_ref": "", "sha256": _file_hash(payload["title"]),
             "content": payload["title"]},
            {"name": "content/body.json", "kind": "body", "storage_object_ref": "", "sha256": _file_hash(_canonical(payload["body"])),
             "content": _canonical(payload["body"])},
            {"name": "content/tags.json", "kind": "tags", "storage_object_ref": "", "sha256": _file_hash(_canonical(list(payload["tags"]))),
             "content": _canonical(list(payload["tags"]))},
            {"name": "content/checklist.json", "kind": "checklist", "storage_object_ref": "", "sha256": _file_hash(_canonical(normalized_checklist)),
             "content": _canonical(normalized_checklist)},
            {"name": "evidence/index.json", "kind": "evidence", "storage_object_ref": "", "sha256": _file_hash(_canonical(normalized_evidence)),
             "content": _canonical(normalized_evidence)},
        ]
        package_hash = _hash({"manifest": manifest, "files": [{key: value for key, value in item.items() if key != "content"} for item in files], "refs": refs, "approvals": approvals})
        private_prefix = f"private://distribution/{tenant}/{intent_id}/{package_hash}"
        for item in files:
            item["storage_object_ref"] = f"{private_prefix}/{item['name']}"
        package = {
            "id": str(uuid4()), "org_id": tenant, "publication_intent_id": intent_id,
            "storage_object_ref": f"{private_prefix}/package.json", "package_hash": package_hash,
            "content_version_refs": refs, "approval_refs": approvals, "expires_at": _stamp(expires),
            "revoked_at": None, "download_count": 0, "status": "available",
        }
        request_hash = _hash({"publication_intent": publication_intent, "content": payload, "media": normalized_media,
                              "checklist": normalized_checklist, "evidence": normalized_evidence,
                              "approval_refs": approvals, "content_version_refs": refs, "expires_at": _stamp(expires),
                              "generated_at": _stamp(generated)})
        with self._lock:
            prior = self._commands.get((tenant, key))
            if prior is not None:
                if prior[0] != request_hash:
                    raise DistributionError("IDEMPOTENCY_KEY_REUSED", "manual export differs from prior request")
                return deepcopy(prior[1])
            _validate("export-package", package)
            result = {"export_package": deepcopy(package), "package": deepcopy(package),
                      "manifest": deepcopy(manifest), "files": deepcopy(files)}
            self.packages[(tenant, intent_id)] = deepcopy(package)
            self.files[(tenant, intent_id)] = deepcopy(files)
            self._commands[(tenant, key)] = (request_hash, deepcopy(result))
            event = {
                "event_id": str(uuid4()), "event_type": "distribution.manual_export.created", "event_schema_version": 1,
                "occurred_at": _stamp(generated), "org_id": tenant, "trace_id": trace,
                "aggregate_type": "publication_intent", "aggregate_id": intent_id, "aggregate_version": 1,
                "actor_type": "service", "actor_id": actor, "idempotency_key": key,
                "payload": {"package_id": package["id"], "package_hash": package_hash, "storage_object_ref": package["storage_object_ref"]},
                "payload_hash": _hash({"package_id": package["id"], "package_hash": package_hash, "storage_object_ref": package["storage_object_ref"]}),
            }
            errors = list(_EVENT_VALIDATOR.iter_errors(event))
            if errors:
                raise DistributionError("INVALID_MANUAL_EXPORT_EVENT", errors[0].message)
            self.events.append(event)
            self.audit.append({"event_type": "distribution.manual_export.created", "org_id": tenant,
                               "actor_id": actor, "trace_id": trace, "idempotency_key": key,
                               "input_hash": request_hash, "output_hash": _hash(package), "package_id": package["id"]})
            return deepcopy(result)

    def _media(self, media: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        if not isinstance(media, Sequence) or isinstance(media, (str, bytes)):
            raise DistributionError("INVALID_MANUAL_EXPORT", "media must be a list")
        result: list[dict[str, Any]] = []
        for index, item in enumerate(media):
            if not isinstance(item, Mapping):
                raise DistributionError("INVALID_MANUAL_EXPORT", "media entries must be objects")
            asset_id = _uuid(item.get("asset_version_id"), "media.asset_version_id")
            source = item.get("storage_object_ref")
            if source is not None and (not isinstance(source, str) or not source.startswith("private://")):
                raise DistributionError("PUBLIC_MEDIA_URL_FORBIDDEN", "manual exports accept only private media references")
            result.append({"asset_version_id": asset_id, "storage_object_ref": source or f"private://asset/{asset_id}",
                           "position": item.get("position", index), "alt": str(item.get("alt", ""))})
        return sorted(result, key=lambda item: (item["position"], item["asset_version_id"]))

    def _checklist(self, checklist: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        if not isinstance(checklist, Sequence) or isinstance(checklist, (str, bytes)):
            raise DistributionError("INVALID_MANUAL_EXPORT", "checklist must be a list")
        result = []
        for item in checklist:
            if not isinstance(item, Mapping) or not isinstance(item.get("key"), str) or not item["key"].strip():
                raise DistributionError("INVALID_MANUAL_EXPORT", "checklist entries require key")
            status = item.get("status", "pending")
            if status not in {"pending", "passed", "failed", "not_applicable"}:
                raise DistributionError("INVALID_MANUAL_EXPORT", "checklist status is invalid")
            result.append({"key": item["key"].strip(), "status": status, "detail": str(item.get("detail", ""))})
        return sorted(result, key=lambda item: item["key"])

    def _evidence(self, evidence: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        if not isinstance(evidence, Sequence) or isinstance(evidence, (str, bytes)):
            raise DistributionError("INVALID_MANUAL_EXPORT", "evidence must be a list")
        result = []
        for item in evidence:
            if not isinstance(item, Mapping) or not isinstance(item.get("ref"), str) or not item["ref"].strip():
                raise DistributionError("INVALID_MANUAL_EXPORT", "evidence entries require ref")
            result.append({"ref": item["ref"].strip(), "kind": str(item.get("kind", "evidence")),
                           "sha256": str(item.get("sha256", _hash(item)))})
        return sorted(result, key=lambda item: (item["kind"], item["ref"]))


__all__ = ["ManualAdapter"]
