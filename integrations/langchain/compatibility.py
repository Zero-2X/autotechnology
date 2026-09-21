"""Frozen compatibility contract for the provider-optional V3 boundary."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CompatibilityWindow:
    python: str = "3.12"
    langgraph: str = "0.6.x-port-compatible"
    langgraph_locked: str = "0.6.7"
    langchain_core: str = "0.3.x-port-compatible"
    langchain_core_locked: str = "0.3.72"
    provider_count: int = 1
    upgrade_review_days: int = 30
    ci_mode: str = "dependency-free-fake"
    lock_file: str = "requirements-v3.lock"


V3_COMPATIBILITY = CompatibilityWindow()


def assert_compatible(*, python_line: str, langgraph_line: str, langchain_core_line: str) -> None:
    if python_line != V3_COMPATIBILITY.python:
        raise RuntimeError("unsupported Python compatibility line")
    if not langgraph_line.startswith("0.6.") or not langchain_core_line.startswith("0.3."):
        raise RuntimeError("unsupported LangGraph/LangChain compatibility line")


def assert_locked(*, python_line: str, langgraph_version: str, langchain_core_version: str) -> None:
    """Require the reviewed provider profile when composing a real runtime."""
    if (python_line, langgraph_version, langchain_core_version) != (
        V3_COMPATIBILITY.python, V3_COMPATIBILITY.langgraph_locked, V3_COMPATIBILITY.langchain_core_locked,
    ):
        raise RuntimeError("provider profile does not match requirements-v3.lock")


__all__ = ["CompatibilityWindow", "V3_COMPATIBILITY", "assert_compatible", "assert_locked"]
