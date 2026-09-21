from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from modules.production import ProductionError, RuleTransformPort, VariantDraftService


class Versions:
    def __init__(self, source: dict) -> None:
        self.source = source
        self.calls = 0

    def get_version(self, *, org_id, version_id):
        self.calls += 1
        return deepcopy(self.source)


class Transform:
    def __init__(self) -> None:
        self.calls = 0
        self.bad_field = False

    def transform(self, **kwargs):
        self.calls += 1
        result = RuleTransformPort().transform(**kwargs)
        if self.bad_field:
            result["blocks"][0]["claim_id"] = str(uuid4())
        return result


def _setup():
    tenant, actor, content_id, version_id = (str(uuid4()) for _ in range(4))
    source = {
        "id": version_id, "org_id": tenant, "canonical_content_id": content_id,
        "status": "draft", "freshness_status": "fresh", "content_hash": "a" * 64,
        "title": "RAG design", "abstract": "Trade-offs", "sections": [
            {"key": "second", "block_id": "b2", "position": 2,
             "content": "Latency is 20 ms; see https://example.test. `x=1`"},
            {"key": "first", "block_id": "b1", "position": 1,
             "content": "Use citations for claims."},
        ],
    }
    versions, transform = Versions(source), Transform()
    service = VariantDraftService(canonical_versions=versions, transform_port=transform)
    args = dict(org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="draft",
                canonical_content_version_id=version_id, locale="en-US", market="US",
                audience="engineers", tone="neutral")
    return service, versions, transform, args


def test_rule_draft_preserves_source_order_text_and_mapping() -> None:
    service, versions, transform, args = _setup()
    result = service.generate(**args)
    assert result["status"] == "draft" and result["needs_review"] is True
    assert result["transform_mode"] == "rule_copy"
    assert [block["source_key"] for block in result["blocks"]] == ["first", "second"]
    assert "20 ms; see https://example.test. `x=1`" in result["blocks"][1]["localized_text"]
    schema = json.loads((Path(__file__).resolve().parents[3] /
                         "packages/contracts/jsonschema/variant-draft.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(result)
    assert service.audit[0]["output_hash"] == result["draft_hash"]
    result["blocks"][0]["localized_text"] = "mutated"
    replay = service.generate(**args)
    assert replay["blocks"][0]["localized_text"] == "Use citations for claims."
    assert (versions.calls, transform.calls) == (1, 1)
    with pytest.raises(ProductionError) as error:
        service.generate(**{**args, "tone": "casual"})
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"


def test_tenant_and_withdrawn_source_are_rejected_before_transform() -> None:
    service, versions, transform, args = _setup()
    versions.source["org_id"] = str(uuid4())
    with pytest.raises(ProductionError) as error:
        service.generate(**args)
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    versions.source["org_id"] = args["org_id"]
    versions.source["freshness_status"] = "withdrawn"
    with pytest.raises(ProductionError) as error:
        service.generate(**args)
    assert error.value.code == "CANONICAL_VERSION_WITHDRAWN"
    assert transform.calls == 0 and service.audit == []


def test_transform_cannot_change_source_mapping_or_add_action_fields() -> None:
    service, versions, transform, args = _setup()
    transform.bad_field = True
    with pytest.raises(ProductionError) as error:
        service.generate(**args)
    assert error.value.code == "INVALID_TRANSFORM_OUTPUT"
    assert service.audit == []


def test_empty_or_nontext_sections_fail_without_transform() -> None:
    service, versions, transform, args = _setup()
    versions.source["sections"] = []
    with pytest.raises(ProductionError) as error:
        service.generate(**args)
    assert error.value.code == "NO_TRANSFORMABLE_SECTIONS"
    versions.source["sections"] = [{"key": "x", "position": 1, "content": {"unsafe": "object"}}]
    with pytest.raises(ProductionError) as error:
        service.generate(**args)
    assert error.value.code == "INVALID_CANONICAL_SOURCE"
    assert transform.calls == 0
