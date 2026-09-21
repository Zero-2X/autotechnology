from __future__ import annotations

from dataclasses import replace

import pytest

from modules.model_gateway import (
    ApprovedExternalProvider,
    ApprovedProviderEvidence,
    FakeModelProvider,
    ModelError,
    ModelGateway,
    ModelRequest,
    TransportResponse,
)


class Transport:
    def __init__(self, *, response: TransportResponse | None = None, error: ModelError | None = None) -> None:
        self.response = response or TransportResponse({"answer": "external"}, "external-v1", 10, 4, 3, 12)
        self.error = error
        self.calls = 0

    def invoke(self, *, request, credential_ref):
        self.calls += 1
        assert credential_ref.startswith("secretref://")
        if self.error is not None:
            raise self.error
        return self.response


def evidence(**changes) -> ApprovedProviderEvidence:
    value = ApprovedProviderEvidence(
        vendor_id="approved-model", environment="dev", processing_regions=("us-east", "eu-west"),
        selected_data_region="us-east", retention_days=0,
        contract_ref="private://governance/model-contract-v1",
        dpa_ref="private://governance/model-dpa-v1",
        subprocessors_review_ref="private://governance/model-subprocessors-v1",
        exit_plan_ref="private://governance/model-exit-v1",
        deletion_proof_ref="private://governance/model-deletion-v1",
        owner_approval_ref="private://governance/model-owner-approval-v1",
        terms_version="terms-2026-09", max_timeout_ms=2000, max_cost_cents_per_call=20,
    )
    return replace(value, **changes)


def request(**changes) -> ModelRequest:
    values = dict(model_id="external-model", prompt_version="prompt/v1", input={"topic": "synthetic"},
                  response_schema_ref=None, timeout_ms=1000, budget_cents=10,
                  trace_id="trace", org_id="org-a")
    values.update(changes)
    return ModelRequest(**values)


def test_missing_credential_routes_to_fake_without_calling_external_transport() -> None:
    transport = Transport()
    fallback = FakeModelProvider(fixtures={request().request_hash: {"answer": "fixture"}})
    provider = ApprovedExternalProvider(evidence=evidence(), model_version="external-v1", transport=transport,
                                        credential_ref=None, fallback=fallback)
    gateway = ModelGateway({"approved-model": provider})
    config = gateway.register_approved_config(org_id="org-a", provider="approved-model", model="external-model",
                                              environment="dev", data_region="us-east", retention_policy="zero-retention")
    record = gateway.call(org_id="org-a", config_id=config.id, request=request(), idempotency_key="optional-provider")

    assert record.provider == "fake" and record.output == {"answer": "fixture"}
    assert transport.calls == 0 and fallback.call_count == 1
    assert gateway.events[-1]["fallback_reason"] == "credential_unavailable"
    stored = gateway.get_provider_evidence(org_id="org-a", config_id=config.id)
    assert stored["credential_ref_present"] is False and stored["terms_version"] == "terms-2026-09"


def test_approved_dev_provider_records_terms_region_timeout_cost_and_redacts_credential() -> None:
    transport = Transport()
    provider = ApprovedExternalProvider(evidence=evidence(), model_version="external-v1", transport=transport,
                                        credential_ref="secretref://dev/model-api")
    gateway = ModelGateway({"approved-model": provider})
    config = gateway.register_approved_config(org_id="org-a", provider="approved-model", model="external-model",
                                              environment="dev", data_region="us-east", retention_policy="zero-retention")
    record = gateway.call(org_id="org-a", config_id=config.id, request=request(), idempotency_key="external-success")

    assert record.provider == "approved-model" and record.cost_cents == 3 and record.latency_ms == 12
    assert record.input_tokens == 10 and record.output_tokens == 4 and transport.calls == 1
    assert gateway.events[-1]["terms_version"] == "terms-2026-09"
    assert gateway.events[-1]["data_region"] == "us-east" and gateway.events[-1]["fallback_reason"] is None
    assert "secretref://" not in repr(gateway.events) and "secretref://" not in repr(record.as_contract())


def test_provider_rejects_production_missing_evidence_region_and_raw_credentials() -> None:
    with pytest.raises(ModelError) as error:
        ApprovedExternalProvider(evidence=evidence(environment="production"), model_version="x",
                                 transport=Transport(), credential_ref=None)
    assert error.value.code == "PROVIDER_EVIDENCE_INVALID"
    with pytest.raises(ModelError) as error:
        ApprovedExternalProvider(evidence=evidence(contract_ref=""), model_version="x",
                                 transport=Transport(), credential_ref=None)
    assert error.value.code == "PROVIDER_EVIDENCE_INVALID"
    with pytest.raises(ModelError) as error:
        ApprovedExternalProvider(evidence=evidence(selected_data_region="ap-south"), model_version="x",
                                 transport=Transport(), credential_ref=None)
    assert error.value.code == "PROVIDER_DATA_REGION_NOT_APPROVED"
    with pytest.raises(ModelError) as error:
        ApprovedExternalProvider(evidence=evidence(), model_version="x", transport=Transport(), credential_ref="raw-token")
    assert error.value.code == "PROVIDER_CREDENTIAL_REF_INVALID"


def test_transient_external_failure_falls_back_but_schema_and_policy_fail_closed() -> None:
    probe = request()
    fallback = FakeModelProvider(fixtures={probe.request_hash: {"answer": "fallback"}})
    transport = Transport(error=ModelError("MODEL_TIMEOUT", "temporary"))
    provider = ApprovedExternalProvider(evidence=evidence(), model_version="external-v1", transport=transport,
                                        credential_ref="secretref://dev/model-api", fallback=fallback)
    response = provider.generate(probe)
    assert response.provider == "fake" and response.output == {"answer": "fallback"}
    assert provider.route_for(probe.request_hash)["fallback_reason"] == "model_timeout"

    with pytest.raises(ModelError) as error:
        provider.generate(request(timeout_ms=2500))
    assert error.value.code == "MODEL_TIMEOUT_POLICY_EXCEEDED"
    with pytest.raises(ModelError) as error:
        provider.generate(request(budget_cents=21))
    assert error.value.code == "MODEL_BUDGET_POLICY_EXCEEDED"

    schema_provider = ApprovedExternalProvider(
        evidence=evidence(), model_version="external-v1",
        transport=Transport(response=TransportResponse({"wrong": True}, "external-v1", 1, 1, 1, 1)),
        credential_ref="secretref://dev/model-api",
        schema_registry={"answer/v1": {"type": "object", "properties": {"answer": {"type": "string"}},
                                       "required": ["answer"], "additionalProperties": False}},
    )
    with pytest.raises(ModelError) as error:
        schema_provider.generate(request(response_schema_ref="answer/v1"))
    assert error.value.code == "MODEL_OUTPUT_SCHEMA_INVALID"
