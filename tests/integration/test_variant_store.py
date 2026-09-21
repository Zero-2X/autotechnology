from __future__ import annotations

import json
import sqlite3
from uuid import uuid4

import pytest

from modules.canonical_content import CanonicalContentService, CanonicalLineageService
from modules.production import ProductionError, RegionRuleService, VariantDraftService, VariantStore


class RegionVersions:
    def __init__(self, *, tenant: str, version_id: str) -> None:
        self.version = {
            "id": version_id, "org_id": tenant, "status": "active",
            "region_code": "US", "locales": ["en-US"],
        }

    def get_version(self, *, org_id, version_id):
        return dict(self.version)


def _setup():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE topic_briefs (id TEXT, org_id TEXT, status TEXT, input_snapshot_hash TEXT, payload TEXT)")
    tenant, actor, brief_id, region_id = (str(uuid4()) for _ in range(4))
    connection.execute("INSERT INTO topic_briefs VALUES (?, ?, 'locked', ?, ?)", (
        brief_id, tenant, "a" * 64,
        json.dumps({"id": brief_id, "org_id": tenant, "status": "locked", "input_snapshot_hash": "a" * 64}),
    ))
    canonical = CanonicalContentService(connection=connection)
    root = canonical.create(org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="root",
                            topic_brief_id=brief_id)["content"]
    version = canonical.create_version(
        org_id=tenant, canonical_content_id=root["id"], actor_id=actor,
        trace_id="trace", idempotency_key="version", content={
            "title": "Source", "input_snapshot_hash": "a" * 64,
            "sections": [{"key": "intro", "position": 1, "content": "An evidence-backed source."}],
        },
    )["version"]
    draft_service = VariantDraftService(canonical_versions=canonical)
    draft = draft_service.generate(
        org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="draft",
        canonical_content_version_id=version["id"], locale="en-US", market="US",
        audience="engineers", tone="neutral",
    )
    regions = RegionVersions(tenant=tenant, version_id=region_id)
    store = VariantStore(connection=connection, canonical_versions=canonical, region_versions=regions)
    args = dict(org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="save",
                draft=draft, region_profile_version_id=region_id, disclosure=None)
    return connection, canonical, draft_service, regions, store, root, version, args


def test_save_draft_creates_root_version_and_lineage_projection() -> None:
    connection, canonical, drafts, regions, store, root, source, args = _setup()
    saved = store.save_draft(**args)
    variant, version = saved["content_variant"], saved["version"]
    assert variant["current_version_id"] == version["id"]
    assert version["version_no"] == 1 and version["status"] == "draft"
    assert version["canonical_content_version_id"] == source["id"]
    assert version["body"]["blocks"][0]["localized_text"] == "An evidence-backed source."
    assert saved["source_map"][0]["source_key"] == "intro"
    assert store.get(org_id=args["org_id"], content_variant_id=variant["id"]) == variant
    assert store.list_versions(org_id=args["org_id"], content_variant_id=variant["id"]) == [version]
    lineage = CanonicalLineageService(canonical, variant_port=store).query(
        org_id=args["org_id"], actor_id=args["actor_id"], trace_id="trace", idempotency_key="lineage",
        canonical_content_id=root["id"],
    )
    assert [node["type"] for node in lineage["nodes"]] == [
        "canonical_content", "canonical_content_version", "variant_version",
    ]
    assert lineage["edges"][-1]["to"] == version["id"]
    assert lineage["unavailable_stages"] == ["asset", "publication"]
    assert connection.execute("SELECT COUNT(*) FROM variant_events").fetchone()[0] == 1
    assert store.save_draft(**args) == saved
    assert connection.execute("SELECT COUNT(*) FROM variant_versions").fetchone()[0] == 1


def test_second_version_requires_expected_pointer_and_preserves_history() -> None:
    connection, canonical, drafts, regions, store, root, source, args = _setup()
    first = store.save_draft(**args)
    second_draft = drafts.generate(
        org_id=args["org_id"], actor_id=args["actor_id"], trace_id="trace", idempotency_key="draft-2",
        canonical_content_version_id=source["id"], locale="en-US", market="US",
        audience="engineers", tone="formal",
    )
    later = {**args, "idempotency_key": "save-2", "draft": second_draft}
    with pytest.raises(ProductionError) as error:
        store.save_draft(**later)
    assert error.value.code == "VERSION_CONFLICT"
    second = store.save_draft(**later, expected_version_no=1)
    assert second["version"]["version_no"] == 2
    assert second["version"]["source_variant_version_id"] == first["version"]["id"]
    history = store.list_versions(org_id=args["org_id"], content_variant_id=first["content_variant"]["id"])
    assert [item["id"] for item in history] == [first["version"]["id"], second["version"]["id"]]
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("UPDATE variant_versions SET status = 'approved' WHERE id = ?", (first["version"]["id"],))
    connection.rollback()
    with pytest.raises(ProductionError) as error:
        store.save_draft(**{**args, "draft": second_draft})
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"


def test_foreign_or_invalid_region_rejected_without_variant_fact() -> None:
    connection, canonical, drafts, regions, store, root, source, args = _setup()
    regions.version["org_id"] = str(uuid4())
    with pytest.raises(ProductionError) as error:
        store.save_draft(**args)
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    regions.version["org_id"] = args["org_id"]
    regions.version["locales"] = ["fr-FR"]
    with pytest.raises(ProductionError) as error:
        store.save_draft(**args)
    assert error.value.code == "REGION_PROFILE_MISMATCH"
    assert connection.execute("SELECT COUNT(*) FROM content_variants").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM variant_events").fetchone()[0] == 0


def test_cross_tenant_draft_and_source_hash_mismatch_rejected() -> None:
    connection, canonical, drafts, regions, store, root, source, args = _setup()
    foreign = dict(args["draft"])
    foreign["org_id"] = str(uuid4())
    with pytest.raises(ProductionError) as error:
        store.save_draft(**{**args, "draft": foreign})
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    changed = dict(args["draft"])
    changed["source_content_hash"] = "b" * 64
    with pytest.raises(ProductionError) as error:
        store.save_draft(**{**args, "draft": changed})
    assert error.value.code == "INVALID_VARIANT_DRAFT"
    assert connection.execute("SELECT COUNT(*) FROM variant_versions").fetchone()[0] == 0


def test_region_preflight_is_run_before_variant_write() -> None:
    connection, canonical, drafts, regions, _store, root, source, args = _setup()
    regions.version.update({
        "region_profile_id": str(uuid4()), "version_no": 1, "region_code": "US", "locales": ["en-US"],
        "timezone": "America/New_York", "units": "imperial", "currency": "USD", "data_residency": "US",
        "valid_from": "2026-09-01T00:00:00Z", "valid_to": "2026-10-01T00:00:00Z",
        "disclosure_rules": [], "restricted_topics": [], "platform_eligibility": [],
    })
    rules = RegionRuleService()
    store = VariantStore(connection=connection, canonical_versions=canonical, region_versions=regions,
                          region_rules=rules)
    saved = store.save_draft(**args)
    assert saved["region_decision"]["status"] == "eligible"
    assert connection.execute("SELECT COUNT(*) FROM variant_versions").fetchone()[0] == 1


def test_region_preflight_blocks_restricted_topic_without_writing_variant() -> None:
    connection, canonical, drafts, regions, _store, root, source, args = _setup()
    regions.version.update({
        "region_profile_id": str(uuid4()), "version_no": 1, "region_code": "US", "locales": ["en-US"],
        "timezone": "America/New_York", "units": "imperial", "currency": "USD", "data_residency": "US",
        "valid_from": "2026-09-01T00:00:00Z", "valid_to": "2026-10-01T00:00:00Z",
        "disclosure_rules": [], "restricted_topics": [{"topic": "evidence"}], "platform_eligibility": [],
    })
    store = VariantStore(connection=connection, canonical_versions=canonical, region_versions=regions,
                          region_rules=RegionRuleService())
    with pytest.raises(ProductionError) as error:
        store.save_draft(**args)
    assert error.value.code == "REGION_RULE_BLOCKED"
    assert connection.execute("SELECT COUNT(*) FROM content_variants").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM variant_versions").fetchone()[0] == 0
