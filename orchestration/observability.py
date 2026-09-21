"""Graph-specific trace and audit helpers."""

from __future__ import annotations

from typing import Any, Mapping

from packages.observability import TraceLedger


def record_graph_event(ledger: TraceLedger, *, event_type: str, org_id: str, actor_id: str,
                       trace_id: str, run_id: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return ledger.emit(event_type, org_id=org_id, actor_id=actor_id, trace_id=trace_id,
                       aggregate_id=run_id, payload=payload)


def record_model_call(ledger: TraceLedger, *, phase: str, org_id: str, actor_id: str,
                      trace_id: str, run_id: str, provider: str, input_tokens: int = 0,
                      output_tokens: int = 0, amount_minor: int = 0,
                      error_code: str | None = None) -> dict[str, Any]:
    event_type = f"model.call.{phase}"
    event = record_graph_event(ledger, event_type=event_type, org_id=org_id, actor_id=actor_id,
                               trace_id=trace_id, run_id=run_id,
                               payload={"provider": provider, "error_code": error_code})
    if phase == "succeeded":
        ledger.cost(org_id=org_id, trace_id=trace_id, provider=provider,
                    input_tokens=input_tokens, output_tokens=output_tokens, amount_minor=amount_minor)
    return event


__all__ = ["record_graph_event", "record_model_call"]
