"""Structured orchestration failures and human interrupts."""

from __future__ import annotations

from typing import Any, Mapping


class GraphError(RuntimeError):
    def __init__(self, code: str, message: str, *, category: str = "validation",
                 retryable: bool = False, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code, self.category, self.retryable = code, category, retryable
        self.details = dict(details or {})


class GraphInterrupt(GraphError):
    def __init__(self, interrupt_ref: str, message: str = "human decision required", *,
                 details: Mapping[str, Any] | None = None) -> None:
        super().__init__("HUMAN_REQUIRED", message, category="human_required", details=details)
        self.interrupt_ref = interrupt_ref
