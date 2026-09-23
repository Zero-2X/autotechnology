import json

import httpx

from modules.model_gateway.console_provider import generate_structured, model_config
import modules.model_gateway.console_provider as console_provider


def test_model_config_is_redacted(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "zpproxy")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("MODEL_ID", "gpt-5.6-sol")
    result = model_config()
    assert result["configured"] is True
    assert result["key_present"] is True
    assert "secret" not in json.dumps(result)


def test_generate_structured_uses_configured_responses(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "zpproxy")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("MODEL_ID", "test-model")
    monkeypatch.delenv("MODEL_TIMEOUT_SECONDS", raising=False)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        "status": "completed",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": '{"reply":"好的","requires_human":false}'}]}],
        "usage": {"input_tokens": 3, "output_tokens": 2},
    }))
    original = console_provider.ResponsesProvider
    captured = {}

    def provider_factory(**kwargs):
        captured.update(kwargs)
        return original(transport=transport, **kwargs)

    monkeypatch.setattr(console_provider, "ResponsesProvider", provider_factory)
    result = generate_structured(
        messages=[{"role": "user", "content": "测试"}],
        schema={"type": "object", "properties": {"reply": {"type": "string"}, "requires_human": {"type": "boolean"}}, "required": ["reply", "requires_human"]},
        purpose="support_reply",
    )
    assert result["reply"] == "好的"
    assert result["model_used"] is True
    assert captured["timeout"] == 60
