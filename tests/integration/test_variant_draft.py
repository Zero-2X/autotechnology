from __future__ import annotations

import json
import sqlite3
from uuid import uuid4

from modules.canonical_content import CanonicalContentService
from modules.production import VariantDraftService


def test_production_draft_reads_real_canonical_version_without_writing_variant_facts() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE topic_briefs (id TEXT, org_id TEXT, status TEXT, input_snapshot_hash TEXT, payload TEXT)")
    tenant, actor, brief_id = (str(uuid4()) for _ in range(3))
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
            "sections": [{"key": "intro", "position": 1, "content": "Original code `print(1)`"}],
        },
    )["version"]
    before = connection.execute("SELECT COUNT(*) FROM canonical_content_versions").fetchone()[0]
    draft = VariantDraftService(canonical_versions=canonical).generate(
        org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="draft",
        canonical_content_version_id=version["id"], locale="en-US", market="US",
        audience="engineers", tone="neutral",
    )
    assert draft["canonical_content_id"] == root["id"]
    assert draft["blocks"][0]["localized_text"] == "Original code `print(1)`"
    assert connection.execute("SELECT COUNT(*) FROM canonical_content_versions").fetchone()[0] == before
    assert "content_variants" not in {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
