"""Small, optional model bridge used by the local web console.

The bridge reads configuration only from the server process environment.  It
never returns or logs the API key and deliberately keeps a deterministic caller
available when the provider is not configured or temporarily fails.
"""
from __future__ import annotations

import os
from typing import Any, Mapping
from uuid import uuid4

from integrations.langchain.model import ModelError
from integrations.langchain.responses import ResponsesProvider


def model_config() -> dict[str, Any]:
    provider = os.getenv("MODEL_PROVIDER", "").strip()
    base_url = os.getenv("MODEL_BASE_URL", "https://webaiproxy.top/v1").strip()
    model = (os.getenv("MODEL_ID") or os.getenv("OPENAI_MODEL") or
             os.getenv("MODEL_CONTENT_ID") or "gpt-5.6-sol").strip()
    key_present = bool(os.getenv("OPENAI_API_KEY", "").strip())
    enabled = provider == "zpproxy" and key_present and bool(model)
    return {
        "provider": provider or "未配置",
        "base_url": base_url,
        "model": model,
        "configured": enabled,
        "key_present": key_present,
    }


def generate_structured(*, messages: list[Mapping[str, str]], schema: dict[str, Any],
                        purpose: str) -> dict[str, Any]:
    """Call the configured Responses endpoint and return the parsed object."""
    config = model_config()
    if not config["configured"]:
        raise ModelError("MODEL_NOT_CONFIGURED", "model provider is not configured")
    provider = ResponsesProvider(
        base_url=config["base_url"],
        api_key=os.environ["OPENAI_API_KEY"],
        timeout=float(os.getenv("MODEL_TIMEOUT_SECONDS", "20")),
    )
    result = provider(messages=messages, model=config["model"], response_schema=schema)
    output = result.get("output")
    if not isinstance(output, dict):
        raise ModelError("MODEL_RESPONSE_INVALID", "model output must be an object")
    return {
        **output,
        "source": "model",
        "model_used": True,
        "provider": config["provider"],
        "model": config["model"],
        "purpose": purpose,
        "request_id": str(uuid4()),
        "input_tokens": result.get("input_tokens", 0),
        "output_tokens": result.get("output_tokens", 0),
    }


__all__ = ["generate_structured", "model_config"]
