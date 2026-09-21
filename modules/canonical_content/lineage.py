"""Tenant-scoped, read-only lineage projection over canonical and downstream ports.

Downstream modules own their facts.  A port returns a small projection with a
``parent_id`` (and, for publications, ``parent_type``); this module never reads
or writes the downstream tables directly.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker

from .service import CanonicalContentError, CanonicalContentService, _now, _text, _uuid


_SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "packages/contracts/jsonschema/lineage-query.schema.json")
    .read_text(encoding="utf-8")
)
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FormatChecker())
_ORDER = {name: index for index, name in enumerate((
    "canonical_content", "canonical_content_version", "variant_version", "asset_version", "publication_record",
))}
_RELATION = {
    "canonical_content_version": "has_version",
    "variant_version": "derived_variant",
    "asset_version": "derived_asset",
    "publication_record": "recorded_publication",
}


class LineageQueryPort(Protocol):
    """A downstream owner's tenant-filtered, read-only child projection."""

    def list_children(self, *, org_id: str, parent_ids: tuple[str, ...]) -> Sequence[Mapping[str, Any]]: ...


def _digest(value: Mapping[str, Any]) -> str:
    material = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(material.encode("utf-8")).hexdigest()


def _node(kind: str, item: Mapping[str, Any], *, tenant: str, status: str | None = None,
          version: int | None = None) -> dict[str, Any]:
    if item.get("org_id") != tenant:
        raise CanonicalContentError("TENANT_SCOPE_VIOLATION", "lineage child is outside this organization")
    identity = _uuid(item.get("id"), "lineage child id")
    assert identity is not None
    effective_status = status if status is not None else item.get("status")
    if not isinstance(effective_status, str) or not effective_status:
        raise CanonicalContentError("INVALID_LINEAGE_PROJECTION", "lineage child status is invalid")
    effective_version = version if version is not None else item.get("version", item.get("version_no"))
    if effective_version is not None and (type(effective_version) is not int or effective_version < 1):
        raise CanonicalContentError("INVALID_LINEAGE_PROJECTION", "lineage child version is invalid")
    metadata_ref = item.get("metadata_ref")
    if metadata_ref is not None and (not isinstance(metadata_ref, str) or not metadata_ref):
        raise CanonicalContentError("INVALID_LINEAGE_PROJECTION", "lineage metadata reference is invalid")
    return {
        "type": kind, "id": identity, "org_id": tenant, "status": effective_status,
        "version": effective_version, "metadata_ref": metadata_ref,
    }


class CanonicalLineageService:
    """Build and audit a stable lineage snapshot for one tenant and root."""

    def __init__(self, canonical: CanonicalContentService, *, variant_port: LineageQueryPort | None = None,
                 asset_port: LineageQueryPort | None = None,
                 publication_port: LineageQueryPort | None = None) -> None:
        self.canonical = canonical
        self.variant_port = variant_port
        self.asset_port = asset_port
        self.publication_port = publication_port

    def _children(self, *, tenant: str, port: LineageQueryPort | None, kind: str,
                  parents: Mapping[str, str], nodes: dict[str, dict[str, Any]],
                  edges: set[tuple[str, str, str, str]]) -> dict[str, str]:
        if port is None or not parents:
            return {}
        children: dict[str, str] = {}
        for item in port.list_children(org_id=tenant, parent_ids=tuple(sorted(parents))):
            if not isinstance(item, Mapping):
                raise CanonicalContentError("INVALID_LINEAGE_PROJECTION", "lineage child must be an object")
            # Check ownership before examining identifiers so a foreign record leaks no details.
            if item.get("org_id") != tenant:
                raise CanonicalContentError("TENANT_SCOPE_VIOLATION", "lineage child is outside this organization")
            parent_id = _uuid(item.get("parent_id"), "lineage parent id")
            assert parent_id is not None
            if parent_id not in parents or (kind == "publication_record" and item.get("parent_type") != parents[parent_id]):
                raise CanonicalContentError("CROSS_CANONICAL_ROOT", "lineage child parent is outside the query root")
            node = _node(kind, item, tenant=tenant)
            previous = nodes.get(node["id"])
            if previous is not None and previous != node:
                raise CanonicalContentError("INVALID_LINEAGE_PROJECTION", "lineage child has conflicting projections")
            nodes[node["id"]] = node
            created_at = item.get("created_at")
            if not isinstance(created_at, str) or not created_at:
                raise CanonicalContentError("INVALID_LINEAGE_PROJECTION", "lineage child created_at is invalid")
            edges.add((parent_id, node["id"], _RELATION[kind], created_at))
            children[node["id"]] = kind
        return children

    def query(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
              canonical_content_id: UUID | str | None = None,
              canonical_content_version_id: UUID | str | None = None) -> dict[str, Any]:
        tenant = _uuid(org_id, "org_id")
        actor = _uuid(actor_id, "actor_id")
        assert tenant is not None and actor is not None
        trace = _text(trace_id, "trace_id", 256)
        key = _text(idempotency_key, "idempotency_key", 200)
        if (canonical_content_id is None) == (canonical_content_version_id is None):
            raise CanonicalContentError("INVALID_LINEAGE_ROOT", "provide exactly one canonical root")
        subject_type = "canonical_content" if canonical_content_id is not None else "canonical_content_version"
        subject_id = _uuid(canonical_content_id if canonical_content_id is not None else canonical_content_version_id,
                           "lineage subject id")
        assert subject_id is not None
        request_hash = _digest({"subject_type": subject_type, "subject_id": subject_id})
        connection = self.canonical.connection
        with self.canonical._lock:
            connection.execute("BEGIN IMMEDIATE")
            try:
                prior = connection.execute(
                    "SELECT request_hash, response FROM canonical_lineage_queries WHERE org_id = ? AND idempotency_key = ?",
                    (tenant, key),
                ).fetchone()
                if prior is not None:
                    if prior["request_hash"] != request_hash:
                        raise CanonicalContentError("IDEMPOTENCY_KEY_REUSED", "lineage query differs from prior request")
                    connection.commit()
                    return json.loads(prior["response"])
                if subject_type == "canonical_content":
                    root = self.canonical.get(org_id=tenant, canonical_content_id=subject_id)
                    versions = self.canonical.list_versions(org_id=tenant, canonical_content_id=subject_id)["versions"]
                else:
                    version = self.canonical.get_version(org_id=tenant, version_id=subject_id)
                    root = self.canonical.get(org_id=tenant, canonical_content_id=version["canonical_content_id"])
                    versions = [version]
                root_id = root["id"]
                nodes: dict[str, dict[str, Any]] = {root_id: _node("canonical_content", root, tenant=tenant)}
                edges: set[tuple[str, str, str, str]] = set()
                version_parents: dict[str, str] = {}
                for version in versions:
                    is_current = version["id"] == root["current_version_id"]
                    effective_status = (
                        "withdrawn" if version.get("freshness_status") == "withdrawn" else
                        version["status"] if is_current else "superseded"
                    )
                    node = _node("canonical_content_version", version, tenant=tenant,
                                 status=effective_status, version=version["version_no"])
                    node["is_current"] = is_current
                    nodes[node["id"]] = node
                    version_parents[node["id"]] = "canonical_content_version"
                    edges.add((root_id, node["id"], _RELATION["canonical_content_version"], version["created_at"]))
                variant_parents = self._children(tenant=tenant, port=self.variant_port, kind="variant_version",
                                                 parents=version_parents, nodes=nodes, edges=edges)
                asset_parents = self._children(tenant=tenant, port=self.asset_port, kind="asset_version",
                                               parents=variant_parents, nodes=nodes, edges=edges)
                self._children(tenant=tenant, port=self.publication_port, kind="publication_record",
                               parents={**variant_parents, **asset_parents}, nodes=nodes, edges=edges)
                result = {
                    "org_id": tenant, "subject_type": subject_type, "subject_id": subject_id,
                    "nodes": sorted(nodes.values(), key=lambda node: (_ORDER[node["type"]], node["version"] or 0, node["id"])),
                    "edges": [
                        {"from": source, "to": target, "relation": relation, "created_at": created_at}
                        for source, target, relation, created_at in sorted(
                            edges, key=lambda edge: (_ORDER[nodes[edge[0]]["type"]], edge[0], edge[1], edge[2], edge[3])
                        )
                    ],
                    "unavailable_stages": [stage for stage, port in (
                        ("variant", self.variant_port), ("asset", self.asset_port),
                        ("publication", self.publication_port),
                    ) if port is None],
                }
                result["query_hash"] = _digest(result)
                errors = list(_VALIDATOR.iter_errors(result))
                if errors:
                    raise CanonicalContentError("INVALID_LINEAGE_PROJECTION", errors[0].message)
                now = _now()
                connection.execute(
                    "INSERT INTO canonical_lineage_queries (id, org_id, idempotency_key, request_hash, query_hash, "
                    "subject_type, subject_id, actor_id, trace_id, created_at, response) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (str(uuid4()), tenant, key, request_hash, result["query_hash"], subject_type,
                     subject_id, actor, trace, now, json.dumps(result, ensure_ascii=False, sort_keys=True)),
                )
                connection.commit()
                return result
            except Exception:
                connection.rollback()
                raise


__all__ = ["CanonicalLineageService", "LineageQueryPort"]
