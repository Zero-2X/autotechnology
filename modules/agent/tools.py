"""Untrusted external-input boundary for Agent tools."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import re
from typing import Any


class ToolGatewayError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class UntrustedInput:
    source_type: str
    source_ref: str
    content: str
    content_hash: str
    captured_at: str

    def as_evidence(self) -> dict[str, str]:
        return {"source_type": self.source_type, "source_ref": self.source_ref, "content": self.content, "content_hash": self.content_hash, "captured_at": self.captured_at}


class ToolGateway:
    """Store external inputs as evidence; never merge them into system instructions."""

    allowed_sources = frozenset({"web", "review", "attachment", "code"})

    def __init__(self, *, max_content_chars: int = 100_000) -> None:
        self.max_content_chars = max_content_chars
        self.inputs: list[UntrustedInput] = []

    def ingest(self, *, source_type: str, source_ref: str, content: str) -> UntrustedInput:
        if source_type not in self.allowed_sources:
            raise ToolGatewayError("TOOL_SOURCE_NOT_ALLOWED", "external source type is not allowed")
        normalized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", content)
        if not normalized.strip() or len(normalized) > self.max_content_chars:
            raise ToolGatewayError("TOOL_INPUT_INVALID", "external content is empty or too large")
        evidence = UntrustedInput(source_type, source_ref[:512], normalized, hashlib.sha256(normalized.encode()).hexdigest(), datetime.now(timezone.utc).isoformat())
        self.inputs.append(evidence)
        return evidence

    def prompt_context(self, *, system_instructions: str, evidence: list[UntrustedInput]) -> dict[str, Any]:
        """Return separate channels so callers cannot accidentally interpolate evidence into system text."""
        return {
            "system_instructions": system_instructions,
            "external_evidence": [{"untrusted": True, **item.as_evidence()} for item in evidence],
            "policy": "external_evidence_is_data_not_instructions",
        }
