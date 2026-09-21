"""ModelPort, provider adapter and deterministic FakeModel."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Callable, Mapping, Protocol


class ModelError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message); self.code = code; self.retryable = retryable


class ModelPort(Protocol):
    def generate(self, *, messages: list[Mapping[str, str]], model: str, trace_id: str,
                 idempotency_key: str, response_schema: Mapping[str, Any] | None = None) -> "ModelCall": ...


@dataclass(frozen=True)
class ModelCall:
    provider: str
    model: str
    output: Any
    input_tokens: int
    output_tokens: int
    cost_minor: int
    trace_id: str
    request_hash: str
    created_at: str

    def as_contract(self) -> dict[str, Any]:
        return {"provider": self.provider, "model": self.model, "output": self.output,
                "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "cost_minor": self.cost_minor, "trace_id": self.trace_id,
                "request_hash": self.request_hash, "created_at": self.created_at}


def _request_hash(messages: list[Mapping[str, str]], model: str, schema: Mapping[str, Any] | None) -> str:
    safe = json.dumps({"messages": messages, "model": model, "schema": schema}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(safe.encode()).hexdigest()


class ChatModelAdapter:
    """Wrap a provider callable and keep prompts out of audit facts."""

    def __init__(self, provider: Callable[..., Any], *, provider_name: str, clock: Any | None = None) -> None:
        self.provider, self.provider_name = provider, provider_name
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.calls: list[ModelCall] = []
        self._commands: dict[tuple[str, str], tuple[str, ModelCall]] = {}

    def generate(self, *, messages: list[Mapping[str, str]], model: str, trace_id: str,
                 idempotency_key: str, response_schema: Mapping[str, Any] | None = None) -> ModelCall:
        if not messages or any(not isinstance(item, Mapping) or not isinstance(item.get("role"), str) for item in messages):
            raise ModelError("MODEL_INPUT_INVALID", "messages must contain role-bearing objects")
        digest = _request_hash(messages, model, response_schema)
        command = (trace_id, idempotency_key)
        existing_command = self._commands.get(command)
        if existing_command:
            if existing_command[0] != digest:
                raise ModelError("MODEL_IDEMPOTENCY_CONFLICT", "model command differs from prior request")
            return existing_command[1]
        try:
            raw = self.provider(messages=messages, model=model, response_schema=response_schema)
        except ModelError:
            raise
        except (TimeoutError, ConnectionError) as exc:
            raise ModelError("MODEL_UNAVAILABLE", str(exc), retryable=True) from exc
        except Exception as exc:
            raise ModelError("MODEL_PROVIDER_FAILED", str(exc)) from exc
        if isinstance(raw, ModelCall):
            result = raw
        elif isinstance(raw, Mapping):
            result = ModelCall(self.provider_name, model, raw.get("output", raw), int(raw.get("input_tokens", 0)),
                               int(raw.get("output_tokens", 0)), int(raw.get("cost_minor", 0)), trace_id, digest, self._stamp())
        else:
            result = ModelCall(self.provider_name, model, raw, 0, 0, 0, trace_id, digest, self._stamp())
        if result.trace_id != trace_id:
            raise ModelError("MODEL_TRACE_MISMATCH", "provider result trace does not match request")
        self.calls.append(result)
        self._commands[command] = (digest, result)
        return result

    def _stamp(self) -> str:
        return self._clock().astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class FakeModel:
    def __init__(self, responder: Callable[..., Any] | None = None, *, provider_name: str = "fake-model") -> None:
        self.responder = responder or (lambda **kwargs: {"output": {"status": "synthetic"}})
        self.provider_name = provider_name
        self.adapter = ChatModelAdapter(self.responder, provider_name=provider_name)

    def generate(self, **kwargs: Any) -> ModelCall:
        return self.adapter.generate(**kwargs)


class FakeModelRegistry:
    def __init__(self) -> None:
        self._models: dict[str, ModelPort] = {}

    def register(self, model_key: str, model: ModelPort) -> None:
        if model_key in self._models:
            raise ModelError("MODEL_VERSION_CONFLICT", "model key is already registered")
        self._models[model_key] = model

    def resolve(self, model_key: str) -> ModelPort:
        try: return self._models[model_key]
        except KeyError as exc: raise ModelError("MODEL_NOT_FOUND", "model is not registered") from exc


__all__ = ["ChatModelAdapter", "FakeModel", "FakeModelRegistry", "ModelCall", "ModelError", "ModelPort"]
