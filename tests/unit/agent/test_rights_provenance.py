from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest

from modules.agent import AgentError, RightsProvenanceAgent, RightsProvenanceModelRequest
from modules.agent.rights_provenance import OUTPUT_REF, OUTPUT_SCHEMA
from modules.model_gateway import FakeModelProvider


STAMP = "2026-09-19T00:00:00Z"


class RightsVersions:
    def __init__(self, tenant, actor, record_id, version_id, snapshot_id) -> None:
        self.value = {
            "id": str(version_id), "org_id": str(tenant), "rights_record_id": str(record_id),
            "version_no": 1, "source_snapshot_ids": [str(snapshot_id)],
            "license_ref": "license:example", "contract_ref": None,
            "evidence_object_refs": ["evidence:owner-email"], "terms_snapshot_hash": "a" * 64,
            "rights_holder": "Example Holder", "permitted_regions": ["US"],
            "permitted_locales": ["en-US"], "permitted_media": ["text"],
            "permitted_use": "commercial", "valid_from": None, "valid_to": None,
            "status": "pending", "policy_rule_version": "rights-policy-v1",
            "verified_by": None, "verified_at": None, "verification_reason": None,
            "supersedes_version_id": None, "snapshot_hash": "b" * 64,
            "created_by": str(actor), "created_at": STAMP,
        }
        self.calls = 0

    def get_version(self, *, org_id, rights_record_id, version_id):
        self.calls += 1
        return deepcopy(self.value)


def _output() -> dict:
    return {
        "permission_clues": [{
            "clue_key": "commercial_use", "evidence_ref": "license:example",
            "locator": "section-2", "quote": "Commercial text use is permitted in the United States.",
            "signal": "permit", "normalized_value": "commercial text use; region US",
            "confidence": 0.9,
        }],
        "scope_candidates": [{
            "scope_key": "region_us", "dimension": "region", "value": "US",
            "evidence_clue_keys": ["commercial_use"], "confidence": 0.9,
        }],
        "gaps": [{
            "gap_key": "missing_expiry", "dimension": "validity",
            "description": "The excerpt does not state an expiry date.", "severity": "high",
            "related_clue_keys": [],
        }],
        "confidence": 0.84, "needs_review": True, "final_rights_decision": "deferred",
    }


def _values(request_id, version, excerpts) -> dict:
    return {
        "analysis_request_id": str(request_id),
        "rights_context": {
            "rights_record_id": version["rights_record_id"],
            "rights_record_version_id": version["id"],
            "version_no": version["version_no"], "snapshot_hash": version["snapshot_hash"],
            "source_snapshot_ids": list(version["source_snapshot_ids"]),
            "license_ref": version["license_ref"], "contract_ref": version["contract_ref"],
            "evidence_object_refs": list(version["evidence_object_refs"]),
            "recorded_scope": {
                "rights_holder": version["rights_holder"],
                "permitted_regions": list(version["permitted_regions"]),
                "permitted_locales": list(version["permitted_locales"]),
                "permitted_media": list(version["permitted_media"]),
                "permitted_use": version["permitted_use"], "valid_from": version["valid_from"],
                "valid_to": version["valid_to"], "policy_rule_version": version["policy_rule_version"],
                "status": version["status"],
            },
        },
        "evidence_excerpts": deepcopy(excerpts), "tool_calls": [],
    }


def _setup(output: dict | None = None):
    tenant, actor, request_id, record_id, version_id, snapshot_id = (uuid4() for _ in range(6))
    rights = RightsVersions(tenant, actor, record_id, version_id, snapshot_id)
    excerpts = [{
        "evidence_ref": "license:example", "locator": "section-2",
        "quote": "Commercial text use is permitted in the United States.",
    }]
    values = _values(request_id, rights.value, excerpts)
    request = RightsProvenanceModelRequest(
        "fake", "rights-provenance/v1", values, OUTPUT_REF, 2000, 20, "trace", str(tenant),
    )
    provider = FakeModelProvider(
        fixtures={request.request_hash: output or _output()}, schema_registry={OUTPUT_REF: OUTPUT_SCHEMA},
    )
    agent = RightsProvenanceAgent(rights=rights, model_port=provider)
    args = dict(
        org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="rights-analysis",
        analysis_request_id=request_id, rights_record_id=record_id,
        rights_record_version_id=version_id, evidence_excerpts=excerpts,
    )
    return agent, rights, provider, args


def test_rights_provenance_extracts_only_and_replays_without_deciding_or_writing() -> None:
    agent, rights, provider, args = _setup()
    result = agent.analyze(**args)

    assert result["status"] == "needs_review" and result["needs_review"] is True
    assert result["permission_clues"][0]["evidence_ref"] == "license:example"
    assert result["final_rights_decision"] == "deferred" and result["extraction_only"] is True
    assert result["rights_record_written"] is False and result["rights_status_mutated"] is False
    assert result["authorization_decision_created"] is False
    assert result["event"]["event_type"] == "agent_run.completed"
    definition = agent.registry.get(org_id=args["org_id"], key="rights-provenance")
    assert definition.tool_allowlist == () and definition.permissions == ()
    assert provider.call_count == rights.calls == 1
    assert len(agent.ledger.agent_runs) == len(agent.ledger.model_calls) == 1
    assert agent.audit[0]["policy_rule_version"] == "rights-policy-v1"

    result["permission_clues"][0]["normalized_value"] = "mutated"
    replay = agent.analyze(**args)
    assert replay["permission_clues"][0]["normalized_value"] == "commercial text use; region US"
    assert provider.call_count == rights.calls == 1
    with pytest.raises(AgentError) as error:
        agent.analyze(**{**args, "evidence_excerpts": [{
            "evidence_ref": "license:example", "locator": "section-3", "quote": "Changed input",
        }]})
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"


def test_rights_provenance_rejects_foreign_version_and_unknown_evidence_before_model() -> None:
    agent, rights, provider, args = _setup()
    rights.value["org_id"] = str(uuid4())
    with pytest.raises(AgentError) as error:
        agent.analyze(**args)
    assert error.value.code == "TENANT_SCOPE_VIOLATION"

    rights.value["org_id"] = str(args["org_id"])
    args["evidence_excerpts"] = [{
        "evidence_ref": "license:unbound", "locator": "section-2", "quote": "Unbound evidence",
    }]
    with pytest.raises(AgentError) as error:
        agent.analyze(**args)
    assert error.value.code == "RIGHTS_PROVENANCE_EVIDENCE_UNKNOWN"
    assert provider.call_count == 0


def test_rights_provenance_rejects_clue_not_present_in_controlled_excerpt() -> None:
    agent, rights, provider, args = _setup()
    fixture = next(iter(provider.fixtures.values()))
    fixture["permission_clues"][0]["quote"] = "A fabricated permission statement."
    with pytest.raises(AgentError) as error:
        agent.analyze(**args)
    assert error.value.code == "RIGHTS_PROVENANCE_CITATION_INVALID"
    assert next(iter(agent.runner.runs.values())).status == "failed"
    assert not agent.audit and not agent.ledger.agent_runs


def test_rights_provenance_rejects_decision_fields_duplicate_keys_and_unknown_links() -> None:
    agent, rights, provider, args = _setup()
    fixture = next(iter(provider.fixtures.values()))
    fixture["rights_status"] = "verified"
    with pytest.raises(ValueError) as error:
        agent.analyze(**args)
    assert getattr(error.value, "code", None) == "MODEL_OUTPUT_SCHEMA_INVALID"

    del fixture["rights_status"]
    fixture["permission_clues"].append(deepcopy(fixture["permission_clues"][0]))
    with pytest.raises(AgentError) as error:
        agent.analyze(**args)
    assert error.value.code == "RIGHTS_PROVENANCE_CLUE_DUPLICATE"

    fixture["permission_clues"].pop()
    fixture["scope_candidates"][0]["evidence_clue_keys"] = ["unknown_clue"]
    with pytest.raises(AgentError) as error:
        agent.analyze(**args)
    assert error.value.code == "RIGHTS_PROVENANCE_CLUE_REFERENCE_INVALID"
