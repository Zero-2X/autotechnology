import json

import httpx
import pytest

from integrations.langchain.responses import ResponsesProvider, zpproxy_adapter
from integrations.langchain.model import ModelError


def completed(text='draft'):
    return {'status': 'completed', 'output': [{'type': 'reasoning'},
            {'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}],
            'usage': {'input_tokens': 12, 'output_tokens': 5}}


def test_proxy_payload_parsing_and_deduplication(monkeypatch):
    calls = []
    def handle(request):
        calls.append(request)
        assert str(request.url) == 'https://webaiproxy.top/v1/responses'
        assert request.headers['authorization'] == 'Bearer test-secret'
        payload = json.loads(request.content)
        assert payload['store'] is False and payload['stream'] is False
        assert payload['model'] == 'test-model'
        return httpx.Response(200, json=completed())
    monkeypatch.setenv('MODEL_PROVIDER', 'zpproxy')
    monkeypatch.setenv('OPENAI_API_KEY', 'test-secret')
    adapter = zpproxy_adapter(transport=httpx.MockTransport(handle))
    args = dict(messages=[{'role': 'user', 'content': 'test'}], model='test-model',
                trace_id='trace', idempotency_key='once')
    first = adapter.generate(**args)
    assert adapter.generate(**args) is first
    assert first.output == 'draft' and first.input_tokens == 12 and len(calls) == 1


@pytest.mark.parametrize('status', [302, 401, 429, 500])
def test_errors_do_not_expose_body_or_credentials(status):
    provider = ResponsesProvider(base_url='https://proxy.example/v1', api_key='test-secret',
        transport=httpx.MockTransport(lambda _: httpx.Response(status, text='test-secret')))
    with pytest.raises(ModelError) as exc:
        provider(messages=[], model='test')
    assert 'test-secret' not in str(exc.value)
    assert exc.value.retryable == (status in [429, 500])


@pytest.mark.parametrize('body', [{'status': 'incomplete'}, completed(''), completed('{"x":1}')])
def test_invalid_structured_results_are_rejected(body):
    provider = ResponsesProvider(base_url='https://proxy.example/v1', api_key='test-secret',
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)))
    with pytest.raises(ModelError):
        provider(messages=[], model='test', response_schema={'type': 'object',
                 'properties': {'title': {'type': 'string'}}, 'required': ['title']})


def test_credential_destination_requires_explicit_selection(monkeypatch):
    monkeypatch.delenv('MODEL_PROVIDER', raising=False)
    with pytest.raises(ValueError, match='explicitly'):
        zpproxy_adapter()
