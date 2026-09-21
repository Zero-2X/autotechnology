from __future__ import annotations

from copy import deepcopy
from uuid import UUID, uuid4

import pytest

from modules.agent import AgentError, TransformAgent, TransformModelRequest
from modules.agent.transform import OUTPUT_REF, OUTPUT_SCHEMA
from modules.model_gateway import FakeModelProvider


class Versions:
    def __init__(self, tenant, actor, content_id, version_id, claim_id) -> None:
        self.source = {
            "id": str(version_id), "org_id": str(tenant), "canonical_content_id": str(content_id),
            "status": "draft", "freshness_status": "fresh", "content_hash": "a" * 64,
            "title": "Latency guide", "abstract": "A protected source.",
            "sections": [{
                "key": "intro", "block_id": "block-intro", "position": 1,
                "content": "Latency is 20 ms; see https://example.test and `x=1`.",
                "claim_id": str(claim_id),
            }, {
                "key": "detail", "position": 2, "content": "Use latency budgets.", "claim_id": None,
            }],
        }
        self.calls = 0

    def get_version(self, *, org_id, version_id):
        self.calls += 1
        return deepcopy(self.source)


def _setup(output_override=None):
    tenant, actor, request_id, content_id, version_id, claim_id = (uuid4() for _ in range(6))
    versions = Versions(tenant, actor, content_id, version_id, claim_id)
    terms = [{"term_key": "latency_term", "source_key": "intro", "source_term": "Latency", "target_term": "延迟"}]
    target = {"locale": "zh-CN", "market": "CN", "audience": "engineers", "tone": "neutral"}
    context, sections, protected = TransformAgent._source_context(
        tenant, version_id, versions.source, terms,
    )
    values = {"transform_request_id": str(request_id), "source_context": context, "target": target, "tool_calls": []}
    request = TransformModelRequest("fake", "transform/v1", values, OUTPUT_REF, 3000, 40, "trace", str(tenant))
    output = output_override or {
        "title": "延迟指南", "abstract": "受保护的来源。",
        "blocks": [
            {"block_id": "block-intro", "source_key": "intro", "localized_text": "延迟是 20 ms；参见 https://example.test 和 `x=1`。", "claim_id": str(claim_id), "disclosure": None},
            {"block_id": "detail", "source_key": "detail", "localized_text": "使用延迟预算。", "claim_id": None, "disclosure": None},
        ],
        "preservation_map": deepcopy(protected), "transform_mode": "agent_candidate", "needs_review": True,
    }
    provider = FakeModelProvider(fixtures={request.request_hash: output}, schema_registry={OUTPUT_REF: OUTPUT_SCHEMA})
    agent = TransformAgent(canonical_versions=versions, model_port=provider)
    args = dict(
        org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="transform",
        transform_request_id=request_id, canonical_content_version_id=version_id,
        locale=target["locale"], market=target["market"], audience=target["audience"], tone=target["tone"],
        terminology=terms,
    )
    return agent, versions, provider, args, sections, protected


def test_transform_agent_returns_reviewable_draft_and_preserves_all_mappings() -> None:
    agent, versions, provider, args, sections, protected = _setup()
    result = agent.generate(**args)
    draft = result["variant_draft"]

    assert result["status"] == "needs_review" and result["needs_review"] is True
    assert result["draft_only"] is True and result["content_variant_created"] is False
    assert result["variant_version_created"] is False and result["publication_side_effect"] is False
    assert draft["status"] == "draft" and draft["needs_review"] is True
    assert [block["source_key"] for block in draft["blocks"]] == ["intro", "detail"]
    assert draft["blocks"][0]["claim_id"] == sections[0]["claim_id"]
    assert {item["mapping_key"] for item in result["preservation_map"]} == {item["mapping_key"] for item in protected}
    assert provider.call_count == versions.calls == 1
    assert len(agent.ledger.agent_runs) == len(agent.ledger.model_calls) == 1
    assert agent.registry.get(org_id=args["org_id"], key="transform").tool_allowlist == ()

    replay = agent.generate(**args)
    assert replay["variant_draft"]["blocks"][0]["localized_text"].startswith("延迟")
    assert provider.call_count == versions.calls == 1
    with pytest.raises(AgentError) as error:
        agent.generate(**{**args, "tone": "formal"})
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"


def test_transform_agent_rejects_foreign_or_withdrawn_source_before_model() -> None:
    agent, versions, provider, args, _, _ = _setup()
    versions.source["org_id"] = str(uuid4())
    with pytest.raises(AgentError) as error:
        agent.generate(**args)
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    versions.source["org_id"] = str(args["org_id"])
    versions.source["freshness_status"] = "withdrawn"
    with pytest.raises(AgentError) as error:
        agent.generate(**args)
    assert error.value.code == "CANONICAL_VERSION_WITHDRAWN"
    assert provider.call_count == 0


def test_transform_agent_rejects_claim_or_protected_mapping_changes() -> None:
    agent, versions, provider, args, _, _ = _setup()
    fixture = next(iter(provider.fixtures.values()))
    fixture["blocks"][0]["claim_id"] = str(uuid4())
    with pytest.raises(AgentError) as error:
        agent.generate(**args)
    assert error.value.code == "TRANSFORM_CLAIM_MAPPING_INVALID"

    fixture["blocks"][0]["claim_id"] = versions.source["sections"][0]["claim_id"]
    fixture["preservation_map"] = fixture["preservation_map"][:-1]
    with pytest.raises(AgentError) as error:
        agent.generate(**args)
    assert error.value.code == "TRANSFORM_PROTECTED_MAPPING_INVALID"

    fixture["preservation_map"] = deepcopy(TransformAgent._source_context(
        UUID(str(args["org_id"])), UUID(str(args["canonical_content_version_id"])), versions.source,
        args["terminology"],
    )[2])
    fixture["blocks"][0]["localized_text"] = "缺少受保护内容"
    with pytest.raises(AgentError) as error:
        agent.generate(**args)
    assert error.value.code == "TRANSFORM_PROTECTED_TOKEN_MISSING"


def test_transform_agent_rejects_term_not_present_and_closed_write_fields() -> None:
    agent, versions, provider, args, _, _ = _setup()
    args["terminology"] = [{"term_key": "missing", "source_key": "intro", "source_term": "Missing", "target_term": "缺失"}]
    with pytest.raises(AgentError) as error:
        agent.generate(**args)
    assert error.value.code == "TRANSFORM_TERM_NOT_IN_SOURCE"
    assert provider.call_count == 0

    agent, versions, provider, args, _, _ = _setup()
    fixture = next(iter(provider.fixtures.values()))
    fixture["content_variant_id"] = str(uuid4())
    with pytest.raises(ValueError) as error:
        agent.generate(**args)
    assert getattr(error.value, "code", None) == "MODEL_OUTPUT_SCHEMA_INVALID"
