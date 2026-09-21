"""MEDIA-006 AssetVersion lineage and withdrawal propagation."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from hashlib import sha256
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid4, uuid5

from jsonschema import Draft202012Validator, FormatChecker

from .media_qa_service import EVENT_NAMESPACE, _context, _hash, _mapping, _safe, _stamp, _time, _text, _uuid


ROOT = Path(__file__).resolve().parents[2]
ASSET_SCHEMA = json.loads((ROOT / "packages/contracts/jsonschema/asset-version.schema.json").read_text(encoding="utf-8"))
ASSET_VALIDATOR = Draft202012Validator(ASSET_SCHEMA, format_checker=FormatChecker())
LINEAGE_SCHEMA = json.loads((ROOT / "packages/contracts/jsonschema/media-asset-lineage.schema.json").read_text(encoding="utf-8"))
LINEAGE_VALIDATOR = Draft202012Validator(LINEAGE_SCHEMA, format_checker=FormatChecker())


class MediaAssetLineageError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class InMemoryMediaAssetLineageStore:
    def __init__(self) -> None:
        self.versions: dict[tuple[str, str], dict[str, Any]] = {}
        self.status_projections: dict[tuple[str, str], dict[str, Any]] = {}
        self.edges: dict[tuple[str, str, int], dict[str, Any]] = {}
        self.commands: dict[tuple[str, str, str], tuple[str, dict[str, Any]]] = {}
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
            prior = self.commands.get((org_id, namespace, key))
            if prior is None:
                return None
            if prior[0] != request_hash:
                raise MediaAssetLineageError("IDEMPOTENCY_KEY_REUSED", "lineage command payload differs from prior request")
            return deepcopy(prior[1])

    def save(self, *, org_id: str, namespace: str, key: str, request_hash: str, asset: Mapping[str, Any], edges: Sequence[Mapping[str, Any]], response: Mapping[str, Any], audit: Mapping[str, Any], event: Mapping[str, Any]) -> dict[str, Any]:
        identity = (org_id, namespace, key)
        with self._lock:
            prior = self.commands.get(identity)
            if prior is not None:
                if prior[0] != request_hash:
                    raise MediaAssetLineageError("IDEMPOTENCY_KEY_REUSED", "lineage command payload differs from prior request")
                return deepcopy(prior[1])
            asset_id = str(asset["id"])
            existing = self.versions.get((org_id, asset_id))
            if existing is not None and _hash(existing) != _hash(asset):
                raise MediaAssetLineageError("ASSET_VERSION_IMMUTABLE", "AssetVersion is immutable")
            self.versions[(org_id, asset_id)] = deepcopy(dict(asset))
            lineage = response.get("lineage") if isinstance(response, Mapping) else None
            lineage_status = lineage.get("status") if isinstance(lineage, Mapping) else None
            current_status = "withdrawn" if lineage_status == "withdrawn" else "blocked" if lineage_status == "blocked" else asset.get("status")
            self.status_projections[(org_id, asset_id)] = {
                "status": current_status, "lineage_status": lineage_status,
                "lineage_checked_at": lineage.get("checked_at") if isinstance(lineage, Mapping) else None,
            }
            for sequence, edge in enumerate(edges, 1):
                self.edges[(org_id, asset_id, sequence)] = {"org_id": org_id, "asset_version_id": asset_id, "sequence": sequence, **deepcopy(dict(edge))}
            result = deepcopy(dict(response))
            self.commands[identity] = (request_hash, result)
            self.audit.append(deepcopy(dict(audit)))
            self.outbox.append(deepcopy(dict(event)))
            return result

    def save_transition(self, *, org_id: str, namespace: str, key: str, request_hash: str,
                        asset_id: str, projection: Mapping[str, Any], response: Mapping[str, Any],
                        audit: Mapping[str, Any], event: Mapping[str, Any]) -> dict[str, Any]:
        identity = (org_id, namespace, key)
        with self._lock:
            prior = self.commands.get(identity)
            if prior is not None:
                if prior[0] != request_hash:
                    raise MediaAssetLineageError("IDEMPOTENCY_KEY_REUSED", "lineage command payload differs from prior request")
                return deepcopy(prior[1])
            result = deepcopy(dict(response))
            self.status_projections[(org_id, asset_id)] = deepcopy(dict(projection))
            self.commands[identity] = (request_hash, result)
            self.audit.append(deepcopy(dict(audit)))
            self.outbox.append(deepcopy(dict(event)))
            return result


def _date_or_none(value: Any, field: str) -> datetime | None:
    if value is None:
        return None
    try:
        return _time(value, field)
    except Exception as exc:
        raise MediaAssetLineageError("INVALID_LINEAGE_INPUT", f"{field} must be timezone-aware ISO-8601") from exc


class MediaAssetLineageService:
    """Create and re-evaluate immutable AssetVersion lineage snapshots."""

    rule_version = "media-006/v1"

    def __init__(self, *, store: InMemoryMediaAssetLineageStore | None = None, clock: Any | None = None) -> None:
        self.store = store or InMemoryMediaAssetLineageStore()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def audit_log(self) -> tuple[dict[str, Any], ...]:
        return self.store.audit_log

    @property
    def outbox_events(self) -> tuple[dict[str, Any], ...]:
        return self.store.outbox_events

    def _validate_tenant_projections(self, *, org_id: str, variant: Mapping[str, Any], claims: Sequence[Mapping[str, Any]], rights: Sequence[Mapping[str, Any]]) -> None:
        if _uuid(variant.get("org_id"), "variant_version.org_id") != org_id:
            raise MediaAssetLineageError("TENANT_SCOPE_VIOLATION", "VariantVersion is outside this organization")
        for name, items in (("claim", claims), ("rights", rights)):
            for index, item in enumerate(items):
                if not isinstance(item, Mapping) or _uuid(item.get("org_id"), f"{name}[{index}].org_id") != org_id:
                    raise MediaAssetLineageError("TENANT_SCOPE_VIOLATION", f"{name} is outside this organization")

    def check_lineage(self, *, asset_version: Mapping[str, Any], variant_version: Mapping[str, Any],
                      claims: Sequence[Mapping[str, Any]] = (), rights_versions: Sequence[Mapping[str, Any]] = (),
                      lineage: Mapping[str, Any] | None = None, lineage_snapshot: Mapping[str, Any] | None = None,
                      org_id: Any = None, tenant_context: Any = None, evaluated_at: Any | None = None,
                      market: str | None = None, locale: str | None = None,
                      permitted_use: str = "commercial") -> dict[str, Any]:
        tenant, _ = _context(org_id=org_id or asset_version.get("org_id"), actor_id=None, tenant_context=tenant_context)
        asset = _mapping(asset_version, "asset_version")
        variant = _mapping(variant_version, "variant_version")
        if _uuid(asset.get("org_id"), "asset_version.org_id") != tenant:
            raise MediaAssetLineageError("TENANT_SCOPE_VIOLATION", "AssetVersion is outside this organization")
        self._validate_tenant_projections(org_id=tenant, variant=variant, claims=claims, rights=rights_versions)
        when = _time(evaluated_at, "evaluated_at") if evaluated_at is not None else _time(self.clock(), "clock")
        snapshot = _mapping(lineage or lineage_snapshot, "lineage") if (lineage is not None or lineage_snapshot is not None) else None
        reasons: list[str] = []
        variant_id = _uuid(variant.get("id"), "variant_version.id")
        if _uuid(asset.get("variant_version_id"), "asset_version.variant_version_id") != variant_id:
            reasons.append("variant_mismatch")
        if variant.get("status") != "approved":
            reasons.append("variant_not_approved")
        variant_hash = variant.get("snapshot_hash")
        expected_variant_hash = None
        if snapshot is not None:
            variant_source = snapshot.get("variant_version") if isinstance(snapshot.get("variant_version"), Mapping) else snapshot
            expected_variant_hash = variant_source.get("snapshot_hash") or snapshot.get("variant_snapshot_hash")
        if expected_variant_hash and expected_variant_hash != variant_hash:
            reasons.append("variant_snapshot_changed")
        if snapshot is not None and isinstance(snapshot.get("claims"), Sequence):
            claim_ids = [str(item.get("id")) for item in snapshot.get("claims", ()) if isinstance(item, Mapping)]
            claim_hashes = {str(item.get("id")): item.get("snapshot_hash") for item in snapshot.get("claims", ()) if isinstance(item, Mapping)}
        else:
            claim_ids = [str(item.get("id")) for item in claims]
            claim_hashes = {}
        claim_map = {str(item.get("id")): item for item in claims}
        for claim_id in claim_ids:
            claim = claim_map.get(claim_id)
            if claim is None:
                reasons.append(f"claim_missing:{claim_id}")
                continue
            if claim.get("status") != "verified" or claim.get("freshness_status") in {"stale", "withdrawn"}:
                reasons.append(f"claim_unusable:{claim_id}")
            applicable = claim.get("applicable_versions") or ()
            canonical_id = variant.get("canonical_content_version_id")
            if applicable and canonical_id not in applicable and variant_id not in applicable:
                reasons.append(f"claim_scope:{claim_id}")
            expected_hash = claim_hashes.get(claim_id)
            actual_hash = claim.get("content_hash") or claim.get("snapshot_hash")
            if expected_hash and actual_hash and expected_hash != actual_hash:
                reasons.append(f"claim_snapshot_changed:{claim_id}")
        if snapshot is not None and isinstance(snapshot.get("rights_record_versions"), Sequence):
            rights_ids = [str(item.get("id")) for item in snapshot.get("rights_record_versions", ()) if isinstance(item, Mapping)]
            rights_hashes = {str(item.get("id")): item.get("snapshot_hash") for item in snapshot.get("rights_record_versions", ()) if isinstance(item, Mapping)}
        else:
            rights_ids = [str(value) for value in (asset.get("rights_snapshot_ids") or ())]
            rights_hashes = {}
        rights_map = {str(item.get("id")): item for item in rights_versions}
        levels = {"research": 0, "derivative": 1, "commercial": 2}
        for rights_id in rights_ids:
            right = rights_map.get(rights_id)
            if right is None:
                reasons.append(f"rights_missing:{rights_id}")
                continue
            if right.get("status") not in {"verified", "current"}:
                reasons.append(f"rights_status:{rights_id}")
            valid_from, valid_to = _date_or_none(right.get("valid_from"), "rights.valid_from"), _date_or_none(right.get("valid_to"), "rights.valid_to")
            if valid_from is not None and when < valid_from:
                reasons.append(f"rights_not_yet_valid:{rights_id}")
            if valid_to is not None and when >= valid_to:
                reasons.append(f"rights_expired:{rights_id}")
            if market is not None and market not in (right.get("permitted_regions") or ()):
                reasons.append(f"rights_region:{rights_id}")
            if locale is not None and locale not in (right.get("permitted_locales") or ()):
                reasons.append(f"rights_locale:{rights_id}")
            if asset.get("media_type") not in (right.get("permitted_media") or ()):
                reasons.append(f"rights_media:{rights_id}")
            if levels.get(permitted_use, -1) > levels.get(str(right.get("permitted_use")), -1):
                reasons.append(f"rights_use:{rights_id}")
            expected_hash = rights_hashes.get(rights_id)
            actual_hash = right.get("snapshot_hash") or right.get("terms_snapshot_hash")
            if expected_hash and actual_hash and expected_hash != actual_hash:
                reasons.append(f"rights_snapshot_changed:{rights_id}")
        rights_reasons = [reason for reason in reasons if reason.startswith("rights_")]
        claim_reasons = [reason for reason in reasons if reason.startswith("claim_")]
        if not reasons:
            status = "valid"
        elif rights_reasons:
            status = "withdrawn"
        elif claim_reasons or any(reason.startswith("variant") for reason in reasons):
            status = "blocked"
        else:
            status = "needs_review"
        return {
            "status": status, "asset_version_id": _uuid(asset.get("id"), "asset_version.id"), "variant_version_id": variant_id,
            "reasons": sorted(set(reasons)), "checked_at": _stamp(when), "rule_version": self.rule_version,
        }

    def create_asset_version(self, *, asset_version: Mapping[str, Any], variant_version: Mapping[str, Any], claims: Sequence[Mapping[str, Any]] = (), rights_versions: Sequence[Mapping[str, Any]] = (), org_id: Any = None, tenant_context: Any = None, actor_id: Any = None, market: str | None = None, locale: str | None = None, permitted_use: str = "commercial", idempotency_key: str = "asset-lineage", trace_id: str = "media-lineage", expected_version: int | None = None, created_at: Any | None = None) -> dict[str, Any]:
        tenant, actor = _context(org_id=org_id or asset_version.get("org_id"), actor_id=actor_id, tenant_context=tenant_context)
        asset = _mapping(asset_version, "asset_version")
        variant = _mapping(variant_version, "variant_version")
        if _uuid(asset.get("org_id"), "asset_version.org_id") != tenant:
            raise MediaAssetLineageError("TENANT_SCOPE_VIOLATION", "AssetVersion is outside this organization")
        self._validate_tenant_projections(org_id=tenant, variant=variant, claims=claims, rights=rights_versions)
        asset_id = _uuid(asset.get("id"), "asset_version.id")
        if expected_version is not None and asset.get("version_no") != expected_version:
            raise MediaAssetLineageError("VERSION_CONFLICT", "AssetVersion differs from expected_version")
        timestamp = _time(created_at, "created_at") if created_at is not None else _time(self.clock(), "clock")
        claim_list = list(claims or ())
        rights_list = list(rights_versions or ())
        rights_ids = [str(item.get("id")) for item in rights_list]
        if asset.get("rights_snapshot_ids") is not None and sorted(str(value) for value in asset.get("rights_snapshot_ids") or ()) != sorted(rights_ids):
            raise MediaAssetLineageError("LINEAGE_SNAPSHOT_MISMATCH", "AssetVersion rights_snapshot_ids differ from supplied RightsRecordVersions")
        schema_errors = list(ASSET_VALIDATOR.iter_errors(asset))
        if schema_errors:
            raise MediaAssetLineageError("INVALID_ASSET_VERSION", schema_errors[0].message)
        claim_hashes = {str(item.get("id")): str(item.get("content_hash") or item.get("snapshot_hash") or _hash(item)) for item in claim_list}
        rights_hashes = {str(item.get("id")): str(item.get("snapshot_hash") or item.get("terms_snapshot_hash") or _hash(item)) for item in rights_list}
        lineage_sources = {
            "variant_version": {
                "id": _uuid(variant.get("id"), "variant_version.id"), "version_no": variant.get("version_no"),
                "snapshot_hash": variant.get("snapshot_hash") or _hash(variant),
            },
            "claims": [
                {"id": str(item["id"]), "version_no": item.get("version"), "snapshot_hash": claim_hashes[str(item["id"])]}
                for item in claim_list
            ],
            "rights_record_versions": [
                {"id": str(item["id"]), "version_no": item.get("version_no"), "snapshot_hash": rights_hashes[str(item["id"])]}
                for item in rights_list
            ],
        }
        decision = self.check_lineage(
            asset_version=asset, variant_version=variant, claims=claim_list, rights_versions=rights_list,
            lineage_snapshot=lineage_sources, org_id=tenant, evaluated_at=_stamp(timestamp), market=market,
            locale=locale, permitted_use=permitted_use,
        )
        lineage_body = {
            "org_id": tenant, "asset_version_id": asset_id, **lineage_sources,
            "status": decision["status"], "reasons": decision["reasons"], "rule_version": self.rule_version,
            "checked_at": decision["checked_at"], "created_by": actor, "created_at": _stamp(timestamp),
        }
        lineage_record = {
            "id": str(uuid5(EVENT_NAMESPACE, f"media-asset-lineage:{tenant}:{asset_id}:{_hash(lineage_sources)}")),
            **lineage_body, "snapshot_hash": _hash(lineage_body),
        }
        lineage_errors = list(LINEAGE_VALIDATOR.iter_errors(lineage_record))
        if lineage_errors:
            raise MediaAssetLineageError("INVALID_ASSET_LINEAGE", lineage_errors[0].message)
        key = _text(idempotency_key, "idempotency_key", 200)
        trace = _text(trace_id, "trace_id")
        request_hash = _hash({"asset": asset, "lineage": lineage_record, "variant": variant, "claims": claim_list, "rights": rights_list, "config": {"market": market, "locale": locale, "permitted_use": permitted_use}})
        prior = self.store.replay(org_id=tenant, namespace="create-lineage", key=key, request_hash=request_hash)
        if prior is not None:
            return prior
        edges: list[dict[str, Any]] = [{"lineage_type": "variant", "source_id": lineage_sources["variant_version"]["id"], "source_version_no": variant.get("version_no"), "source_snapshot_hash": lineage_sources["variant_version"]["snapshot_hash"], "relation": "derived_from", "created_at": _stamp(timestamp)}]
        edges.extend({"lineage_type": "claim", "source_id": item["id"], "source_version_no": item.get("version"), "source_snapshot_hash": claim_hashes[item["id"]], "relation": "fact_support", "created_at": _stamp(timestamp)} for item in claim_list)
        edges.extend({"lineage_type": "rights", "source_id": item["id"], "source_version_no": item.get("version_no"), "source_snapshot_hash": rights_hashes[item["id"]], "relation": "rights_snapshot", "created_at": _stamp(timestamp)} for item in rights_list)
        response = {"asset_version": asset, "lineage": lineage_record, "edges": edges}
        report_hash = _hash(response)
        event_type = "asset.withdrawn" if decision["status"] == "withdrawn" else "asset.blocked" if decision["status"] == "blocked" else "asset.created"
        payload = {"aggregate_id": asset_id, "aggregate_version": int(asset.get("version_no", 1)), "status": decision["status"], "lineage_hash": lineage_record["snapshot_hash"]}
        event = {"event_id": str(uuid5(EVENT_NAMESPACE, f"media-lineage:{tenant}:{asset_id}:{key}")), "event_type": event_type, "event_schema_version": 1, "org_id": tenant, "aggregate_id": asset_id, "aggregate_type": "AssetVersion", "aggregate_version": int(asset.get("version_no", 1)), "trace_id": trace, "actor_type": "user", "actor_id": actor, "idempotency_key": key, "occurred_at": _stamp(timestamp), "payload": payload, "payload_hash": _hash(payload)}
        audit = {"operation": "create_asset_version_lineage", "org_id": tenant, "asset_version_id": asset_id, "actor_id": actor, "trace_id": trace, "idempotency_key": key, "input_hash": request_hash, "output_hash": report_hash, "status": decision["status"], "created_at": _stamp(timestamp)}
        return self.store.save(org_id=tenant, namespace="create-lineage", key=key, request_hash=request_hash, asset=asset, edges=edges, response=response, audit=audit, event=event)

    def link_lineage(self, **kwargs: Any) -> dict[str, Any]:
        return self.create_asset_version(**kwargs)

    def create(self, **kwargs: Any) -> dict[str, Any]:
        return self.create_asset_version(**kwargs)

    def recheck_lineage(self, **kwargs: Any) -> dict[str, Any]:
        return self.check_lineage(**kwargs)

    def propagate_dependency_change(self, *, asset_version: Mapping[str, Any], variant_version: Mapping[str, Any], claims: Sequence[Mapping[str, Any]] = (), rights_versions: Sequence[Mapping[str, Any]] = (), **kwargs: Any) -> dict[str, Any]:
        decision = self.check_lineage(asset_version=asset_version, variant_version=variant_version, claims=claims, rights_versions=rights_versions, **kwargs)
        updated = deepcopy(dict(asset_version))
        if decision["status"] == "withdrawn":
            updated["status"] = "withdrawn"
        elif decision["status"] == "blocked":
            updated["status"] = "blocked"
        return {"asset_version": updated, "lineage": decision}

    def withdraw(self, *, asset_version: Mapping[str, Any], reason: str, org_id: Any = None, tenant_context: Any = None, actor_id: Any = None, idempotency_key: str = "asset-withdraw", trace_id: str = "media-lineage-withdraw", **kwargs: Any) -> dict[str, Any]:
        tenant, actor = _context(org_id=org_id or asset_version.get("org_id"), actor_id=actor_id, tenant_context=tenant_context)
        reason_text = _text(reason, "reason", 256)
        asset = _mapping(asset_version, "asset_version")
        if _uuid(asset.get("org_id"), "asset_version.org_id") != tenant:
            raise MediaAssetLineageError("TENANT_SCOPE_VIOLATION", "AssetVersion is outside this organization")
        updated = deepcopy(asset)
        updated["status"] = "withdrawn"
        checked_at = _stamp(_time(self.clock(), "clock"))
        key = _text(idempotency_key, "idempotency_key", 200)
        request_hash = _hash({"asset": asset, "reason": reason_text})
        prior = self.store.replay(org_id=tenant, namespace="withdraw", key=key, request_hash=request_hash)
        if prior is not None:
            return prior
        payload = {"aggregate_id": updated["id"], "aggregate_version": int(updated.get("version_no", 1)), "reason": reason_text}
        event = {"event_id": str(uuid5(EVENT_NAMESPACE, f"media-lineage-withdraw:{tenant}:{updated['id']}:{key}")), "event_type": "asset.withdrawn", "event_schema_version": 1, "org_id": tenant, "aggregate_id": updated["id"], "aggregate_type": "AssetVersion", "aggregate_version": int(updated.get("version_no", 1)), "trace_id": _text(trace_id, "trace_id"), "actor_type": "user", "actor_id": actor, "idempotency_key": key, "occurred_at": checked_at, "payload": payload, "payload_hash": _hash(payload)}
        audit = {"operation": "withdraw_asset_lineage", "org_id": tenant, "asset_version_id": updated["id"], "actor_id": actor, "trace_id": trace_id, "reason": reason_text, "status": "withdrawn", "created_at": checked_at}
        response = {"asset_version": updated, "lineage": {"status": "withdrawn", "reasons": [reason_text], "checked_at": checked_at}}
        return self.store.save_transition(
            org_id=tenant, namespace="withdraw", key=key, request_hash=request_hash,
            asset_id=str(updated["id"]), projection={"status": "withdrawn", "lineage_status": "withdrawn", "lineage_checked_at": checked_at},
            response=response, audit=audit, event=event,
        )


AssetLineageService = MediaAssetLineageService
MediaAssetVersionService = MediaAssetLineageService
AssetVersionLineageService = MediaAssetLineageService
MediaLineageService = MediaAssetLineageService
MediaAssetLineageError = MediaAssetLineageError
MediaAssetLineageStore = InMemoryMediaAssetLineageStore


__all__ = [
    "AssetLineageService", "AssetVersionLineageService", "InMemoryMediaAssetLineageStore", "MediaAssetLineageError",
    "MediaAssetLineageService", "MediaAssetLineageStore", "MediaAssetVersionService", "MediaLineageService",
]
