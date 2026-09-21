from uuid import uuid4

from orchestration import ContentGraphPorts, GraphRegistry, GraphRunner, build_content_graph


def _port(name):
    def call(**kwargs):
        return {"refs": {name: f"private://{name}/1"}}
    return call


def test_account_free_content_graph_uses_only_injected_ports():
    registry = GraphRegistry()
    build_content_graph(registry=registry, ports=ContentGraphPorts(*[_port(name) for name in ("brief", "canonical", "quality", "approval", "export", "fake")]))
    runner = GraphRunner(registry)
    result = runner.run(org_id=uuid4(), actor_id=uuid4(), graph_key="content_pipeline", input_refs={"signal": "ref://signal/1"}, idempotency_key="content-1", trace_id="trace")
    assert result["status"] == "succeeded"
    assert set(result["result_refs"]) == {"brief", "canonical", "quality", "approval", "export", "fake"}
    assert result["state"]["input_refs"] == {"signal": "ref://signal/1"}
