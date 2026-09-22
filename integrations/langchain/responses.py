"""Server-side Responses transport for an explicitly configured proxy.

No account-pool management, browser credentials, implicit retries or fake fallback.
The existing ChatModelAdapter supplies process-local command deduplication.
"""
from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlsplit

import httpx
from jsonschema import Draft202012Validator

from .model import ChatModelAdapter, ModelError


class ResponsesProvider:
    def __init__(self, *, base_url: str, api_key: str,
                 transport: httpx.BaseTransport | None = None, timeout: float = 60) -> None:
        parsed = urlsplit(base_url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise ValueError('A credential-free HTTPS base URL is required')
        if not api_key.strip():
            raise ValueError('Model API key is missing')
        self._url = base_url.rstrip('/') + '/responses'
        self._key = api_key
        self._transport = transport
        self._timeout = timeout

    def __call__(self, *, messages: list, model: str, response_schema: dict | None = None) -> dict:
        if not model.strip():
            raise ModelError('MODEL_CONFIG_MISSING', 'An explicit model ID is required')
        payload: dict[str, Any] = {'model': model, 'input': messages, 'store': False, 'stream': False}
        if response_schema is not None:
            Draft202012Validator.check_schema(response_schema)
            payload['text'] = {'format': {'type': 'json_schema', 'name': 'workflow_output',
                                        'strict': True, 'schema': response_schema}}
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout,
                              follow_redirects=False) as client:
                response = client.post(self._url, json=payload,
                                       headers={'Authorization': f'Bearer {self._key}'})
        except httpx.RequestError:
            raise ModelError('MODEL_UNAVAILABLE', 'Model transport failed; inspect connectivity',
                             retryable=True) from None
        if response.status_code != 200:
            raise ModelError('MODEL_HTTP_ERROR', f'Model endpoint returned HTTP {response.status_code}',
                             retryable=response.status_code == 429 or response.status_code >= 500)
        try:
            data = response.json()
            if data.get('status') != 'completed':
                raise ValueError('incomplete response')
            texts = []
            for item in data.get('output', []):
                if item.get('type') != 'message':
                    continue
                for part in item.get('content', []):
                    if part.get('type') == 'refusal':
                        raise ValueError('refusal')
                    if part.get('type') == 'output_text':
                        texts.append(part['text'])
            output = '\n'.join(texts)
            if not output.strip():
                raise ValueError('no text output')
            if response_schema is not None:
                output = json.loads(output)
                if not Draft202012Validator(response_schema).is_valid(output):
                    raise ValueError('schema mismatch')
            usage = data.get('usage') or {}
            return {'output': output, 'input_tokens': int(usage.get('input_tokens', 0)),
                    'output_tokens': int(usage.get('output_tokens', 0))}
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ModelError('MODEL_RESPONSE_INVALID', 'Model response is incomplete or invalid') from None


def zpproxy_adapter(*, transport: httpx.BaseTransport | None = None, base_url: str | None = None) -> ChatModelAdapter:
    """Call only after the operator has bound OPENAI_API_KEY to this proxy.

Never reads ChatGPT login credentials; usage cost is not priced by this adapter.
"""
    if os.environ.get('MODEL_PROVIDER') != 'zpproxy':
        raise ValueError('Set MODEL_PROVIDER=zpproxy to explicitly select this credential destination')
    provider = ResponsesProvider(base_url=base_url or os.environ.get('MODEL_BASE_URL', 'https://webaiproxy.top/v1'),
                                 api_key=os.environ.get('OPENAI_API_KEY', ''), transport=transport)
    return ChatModelAdapter(provider, provider_name='zpproxy')
