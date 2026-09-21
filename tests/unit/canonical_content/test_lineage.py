from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from modules.canonical_content import CanonicalContentError, CanonicalContentService, CanonicalLineageService


STAMP = "2026-09-19T00:00:00Z"


class Port:
    def __init__(self, records: list[dict]) -> None:
        self.records = records
        self.calls = 0

    def list_children(self, *, org_id: str, parent_ids: tuple[str, ...]) -> list[dict]:
        self.calls += 1
        return list(self.records)


def _canonical(*, with_version: bool = True):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE topic_briefs (id TEXT, org_id TEXT, status TEXT, input_snapshot_hash TEXT, payload TEXT)")
    tenant, actor, brief = (str(uuid4()) for _ in range(3))
    connection.execute("INSERT INTO topic_briefs VALUES (?, ?, 'locked', ?, ?)", (
        brief, tenant, "a" * 64,
        json.dumps({"id": brief, "org_id": tenant, "status": "locked", "input_snapshot_hash": "a" * 64}),
    ))
    service = CanonicalContentService(connection=connection)
    root = service.create(org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="root",
                          topic_brief_id=brief)["content"]
    if not with_version:
        return service, tenant, actor, root, None
    version = service.create_version(
        org_id=tenant, canonical_content_id=root["id"], actor_id=actor,
        trace_id="trace", idempotency_key="version", content={
            "title": "A", "input_snapshot_hash": "a" * 64,
        },
    )["version"]
    return service, tenant, actor, root, version


def _child(tenant: str, parent: str, *, kind: str, version: int | None = 1,
           parent_type: str | None = None) -> dict:
    child = {
        "id": str(uuid4()), "org_id": tenant, "parent_id": parent,
        "status": "published" if kind == "publication" else "active",
        "version": version, "metadata_ref": None, "created_at": STAMP,
    }
    if parent_type is not None:
        child["parent_type"] = parent_type
    return child


def test_full_lineage_is_sorted_valid_and_replayed_without_port_reads() -> None:
    service, tenant, actor, root, version = _canonical()
    first = _child(tenant, version["id"], kind="variant", version=2)
    second = _child(tenant, version["id"], kind="variant", version=1)
    asset = _child(tenant, first["id"], kind="asset")
    published = [_child(tenant, asset["id"], kind="publication", version=None,
                        parent_type="asset_version") for _ in range(2)]
    variants, assets, publications = Port([first, second]), Port([asset]), Port(list(reversed(published)))
    lineage = CanonicalLineageService(service, variant_port=variants, asset_port=assets,
                                      publication_port=publications)
    args = dict(org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="lineage",
                canonical_content_id=root["id"])
    result = lineage.query(**args)
    assert [node["type"] for node in result["nodes"]] == [
        "canonical_content", "canonical_content_version", "variant_version",
        "variant_version", "asset_version", "publication_record", "publication_record",
    ]
    assert [node["id"] for node in result["nodes"] if node["type"] == "variant_version"] == [second["id"], first["id"]]
    assert [edge["relation"] for edge in result["edges"]] == [
        "has_version", "derived_variant", "derived_variant", "derived_asset",
        "recorded_publication", "recorded_publication",
    ]
    assert result["unavailable_stages"] == []
    schema = json.loads((Path(__file__).resolve().parents[3] /
                         "packages/contracts/jsonschema/lineage-query.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(result)
    assert lineage.query(**args) == result
    assert (variants.calls, assets.calls, publications.calls) == (1, 1, 1)
    assert service.connection.execute("SELECT COUNT(*) FROM canonical_lineage_queries").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        service.connection.execute("DELETE FROM canonical_lineage_queries")


def test_empty_root_and_unavailable_stages_are_explicit() -> None:
    service, tenant, actor, root, _ = _canonical(with_version=False)
    result = CanonicalLineageService(service).query(
        org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="empty",
        canonical_content_id=root["id"],
    )
    assert [node["type"] for node in result["nodes"]] == ["canonical_content"]
    assert result["edges"] == []
    assert result["unavailable_stages"] == ["variant", "asset", "publication"]


def test_tenant_and_parent_violations_leave_no_audit_snapshot() -> None:
    service, tenant, actor, root, version = _canonical()
    with pytest.raises(CanonicalContentError) as error:
        CanonicalLineageService(service).query(
            org_id=str(uuid4()), actor_id=actor, trace_id="trace", idempotency_key="foreign-root",
            canonical_content_id=root["id"],
        )
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    foreign = _child(str(uuid4()), version["id"], kind="variant")
    with pytest.raises(CanonicalContentError) as error:
        CanonicalLineageService(service, variant_port=Port([foreign])).query(
            org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="foreign-child",
            canonical_content_id=root["id"],
        )
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    wrong_parent = _child(tenant, str(uuid4()), kind="variant")
    with pytest.raises(CanonicalContentError) as error:
        CanonicalLineageService(service, variant_port=Port([wrong_parent])).query(
            org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="wrong-parent",
            canonical_content_id=root["id"],
        )
    assert error.value.code == "CROSS_CANONICAL_ROOT"
    assert service.connection.execute("SELECT COUNT(*) FROM canonical_lineage_queries").fetchone()[0] == 0


def test_version_root_and_idempotency_mismatch() -> None:
    service, tenant, actor, root, first = _canonical()
    second = service.create_version(
        org_id=tenant, canonical_content_id=root["id"], actor_id=actor,
        trace_id="trace", idempotency_key="v2", content={
            "title": "B", "input_snapshot_hash": "a" * 64,
        },
    )["version"]
    lineage = CanonicalLineageService(service)
    result = lineage.query(org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="history",
                           canonical_content_version_id=first["id"])
    assert [node["id"] for node in result["nodes"]] == [root["id"], first["id"]]
    assert result["nodes"][1]["status"] == "superseded"
    assert result["nodes"][1]["is_current"] is False
    with pytest.raises(CanonicalContentError) as error:
        lineage.query(org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="history",
                      canonical_content_version_id=second["id"])
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"
    with pytest.raises(CanonicalContentError) as error:
        lineage.query(org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="missing",
                      canonical_content_version_id=str(uuid4()))
    assert error.value.code == "TENANT_SCOPE_VIOLATION"


def test_text_publication_can_attach_directly_to_variant() -> None:
    service, tenant, actor, root, version = _canonical()
    variant = _child(tenant, version["id"], kind="variant")
    publication = _child(tenant, variant["id"], kind="publication", version=None,
                         parent_type="variant_version")
    result = CanonicalLineageService(
        service, variant_port=Port([variant]), publication_port=Port([publication]),
    ).query(org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="text",
            canonical_content_id=root["id"])
    assert result["unavailable_stages"] == ["asset"]
    assert result["edges"][-1]["from"] == variant["id"]
    assert result["edges"][-1]["to"] == publication["id"]
