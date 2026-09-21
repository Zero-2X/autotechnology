"""Side-effect-free graph routing helpers."""

from __future__ import annotations

from typing import Any, Mapping


def route_status(state: Mapping[str, Any]) -> str:
    status = str(state.get("status", "running"))
    if status in {"failed", "cancelled", "waiting", "paused", "succeeded"}:
        return status
    return "next"


def route_quality(state: Mapping[str, Any], *, pass_key: str = "qa_passed") -> str:
    value = state.get(pass_key)
    if value is True:
        return "approved"
    if value is False:
        return "human_review"
    return "needs_evidence"


def route_error(error: Mapping[str, Any]) -> str:
    category = str(error.get("category", "validation"))
    if category == "transient" and bool(error.get("retryable")):
        return "retry"
    if category in {"unknown", "human_required"}:
        return "human_review"
    return "blocked"


__all__ = ["route_error", "route_quality", "route_status"]
