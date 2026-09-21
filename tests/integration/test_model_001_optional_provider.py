from __future__ import annotations

from modules.model_gateway import ApprovedExternalProvider, ApprovedProviderEvidence, FakeModelProvider, ModelGateway, ModelRequest, TransportResponse


class NoNetworkTransport:
    def __init__(self) -> None:
        self.calls = 0
    def invoke(self, *, request, credential_ref):
        self.calls += 1
        return TransportResponse({"answer": "unexpected"}, "external-v1", 1, 1, 1, 1)


def test_ci_path_keeps_optional_provider_offline_and_replays_fake_result() -> None:
    evidence = ApprovedProviderEvidence(
        vendor_id="approved-model", environment="staging", processing_regions=("eu-west",),
        selected_data_region="eu-west", retention_days=0,
        contract_ref="private://contract", dpa_ref="private://dpa",
        subprocessors_review_ref="private://subprocessors", exit_plan_ref="private://exit",
        deletion_proof_ref="private://deletion", owner_approval_ref="private://approval",
        terms_version="terms-v1", max_timeout_ms=1000, max_cost_cents_per_call=5,
    )
    request = ModelRequest("external-model", "prompt/v1", {"fixture": True}, None, 500, 5, "trace", "org-a")
    fake = FakeModelProvider(fixtures={request.request_hash: {"answer": "offline-fixture"}})
    transport = NoNetworkTransport()
    adapter = ApprovedExternalProvider(evidence=evidence, model_version="external-v1", transport=transport,
                                       credential_ref=None, fallback=fake)
    gateway = ModelGateway({"approved-model": adapter})
    config = gateway.register_approved_config(org_id="org-a", provider="approved-model", model="external-model",
                                              environment="staging", data_region="eu-west", retention_policy="zero-retention")
    first = gateway.call(org_id="org-a", config_id=config.id, request=request, idempotency_key="ci-fixture")
    second = gateway.call(org_id="org-a", config_id=config.id, request=request, idempotency_key="ci-fixture")
    assert first.id == second.id and first.output == {"answer": "offline-fixture"}
    assert first.provider == "fake" and transport.calls == 0 and fake.call_count == 1
