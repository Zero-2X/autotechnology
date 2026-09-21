from __future__ import annotations

import json
import sqlite3
from uuid import UUID, uuid4

from modules.agent import TransformAgent, TransformModelRequest
from modules.agent.transform import OUTPUT_REF, OUTPUT_SCHEMA
from modules.canonical_content import CanonicalContentService
from modules.model_gateway import FakeModelProvider


def test_transform_agent_reads_real_canonical_version_and_keeps_variant_persistence_out_of_scope() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE topic_briefs (id TEXT, org_id TEXT, status TEXT, input_snapshot_hash TEXT, payload TEXT)")
    tenant, actor, brief_id, request_id = (uuid4() for _ in range(4))
    connection.execute("INSERT INTO topic_briefs VALUES (?, ?, 'locked', ?, ?)", (
        str(brief_id), str(tenant), "a" * 64,
        json.dumps({"id": str(brief_id), "org_id": str(tenant), "status": "locked", "input_snapshot_hash": "a" * 64}),
    ))
    canonical = CanonicalContentService(connection=connection)
    root = canonical.create(org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="root", topic_brief_id=brief_id)["content"]
    claim_id = uuid4()
    version = canonical.create_version(
        org_id=tenant, canonical_content_id=root["id"], actor_id=actor,
        trace_id="trace", idempotency_key="version", content={
            "title": "Source", "input_snapshot_hash": "a" * 64,
            "sections": [{"key": "intro", "position": 1, "content": "Latency is 20 ms; see https://example.test and `x=1`.", "claim_id": str(claim_id)}],
        },
    )["version"]
    terms = [{"term_key": "latency_term", "source_key": "intro", "source_term": "Latency", "target_term": "延迟"}]
    context, sections, protected = TransformAgent._source_context(tenant, UUID(version["id"]), version, terms)
    values = {
        "transform_request_id": str(request_id), "source_context": context,
        "target": {"locale": "zh-CN", "market": "CN", "audience": "engineers", "tone": "neutral"},
        "tool_calls": [],
    }
    output = {
        "title": "来源", "abstract": "",
        "blocks": [{"block_id": "intro", "source_key": "intro", "localized_text": "延迟是 20 ms；见 https://example.test 和 `x=1`。", "claim_id": str(claim_id), "disclosure": None}],
        "preservation_map": protected, "transform_mode": "agent_candidate", "needs_review": True,
    }
    request = TransformModelRequest("fake", "transform/v1", values, OUTPUT_REF, 3000, 40, "trace", str(tenant))
    provider = FakeModelProvider(fixtures={request.request_hash: output}, schema_registry={OUTPUT_REF: OUTPUT_SCHEMA})
    agent = TransformAgent(canonical_versions=canonical, model_port=provider)
    result = agent.generate(
        org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="transform",
        transform_request_id=request_id, canonical_content_version_id=version["id"],
        locale="zh-CN", market="CN", audience="engineers", tone="neutral", terminology=terms,
    )

    assert result["variant_draft"]["transform_mode"] == "agent_candidate"
    assert result["variant_draft"]["blocks"][0]["claim_id"] == str(claim_id)
    assert result["content_variant_created"] is False and result["variant_version_created"] is False
    assert connection.execute("SELECT COUNT(*) FROM canonical_content_versions").fetchone()[0] == 1
    assert "content_variants" not in {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
