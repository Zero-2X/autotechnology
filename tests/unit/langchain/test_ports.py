import time

import pytest

from integrations.langchain import (
    FakeModel, FakeModelRegistry, InMemoryRetriever, ParseError, PromptError, PromptTemplate,
    PromptTemplateRegistry, RetrievedDocument, StructuredOutputParser, ToolError, ToolRegistry, ToolSpec,
)


def test_fake_model_prompt_and_structured_parser_are_versioned():
    prompts = PromptTemplateRegistry()
    prompts.register(PromptTemplate("brief", 1, "Summarize {{ref}}", ("ref",)))
    assert prompts.resolve("brief").render({"ref": "ref://brief"}) == "Summarize ref://brief"
    with pytest.raises(PromptError): prompts.resolve("brief").render({"token": "x"})
    model = FakeModel(lambda **kwargs: {"output": {"status": "ok"}})
    registry = FakeModelRegistry(); registry.register("fake-v1", model)
    call = registry.resolve("fake-v1").generate(messages=[{"role": "user", "content": "ref://brief"}], model="fake", trace_id="t", idempotency_key="k")
    assert call.output["status"] == "ok" and "content" not in call.as_contract()
    parser = StructuredOutputParser({"type": "object", "required": ["status"], "properties": {"status": {"type": "string"}}, "additionalProperties": False})
    assert parser.parse('{"status":"ok"}') == {"status": "ok"}
    with pytest.raises(ParseError): parser.parse('{"status": 2}')


def test_retriever_enforces_tenant_and_private_evidence():
    retriever = InMemoryRetriever()
    retriever.add(RetrievedDocument("d1", "org-a", "private://text/1", .9, ("e1",), "private://snapshot/1"))
    retriever.add(RetrievedDocument("d2", "org-b", "private://text/2", .99, ("e1",), "private://snapshot/2"))
    assert [item.id for item in retriever.search(org_id="org-a", query="q", required_evidence=("e1",))] == ["d1"]


def test_tool_schema_side_effect_and_timeout_gates():
    registry = ToolRegistry()
    spec = {"type": "object", "required": ["x"], "properties": {"x": {"type": "integer"}}, "additionalProperties": False}
    registry.register(ToolSpec("sum", 1, spec, {"type": "object", "required": ["y"], "properties": {"y": {"type": "integer"}}, "additionalProperties": False}, lambda args: {"y": args["x"] + 1}))
    assert registry.execute("sum", version=1, arguments={"x": 1})["y"] == 2
    registry.register(ToolSpec("slow", 1, {"type": "object"}, {"type": "object"}, lambda args: (time.sleep(.05), {})[1], timeout_seconds=.001))
    with pytest.raises(ToolError) as error: registry.execute("slow", version=1, arguments={})
    assert error.value.code == "TOOL_TIMEOUT"
