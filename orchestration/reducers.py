"""Pure parallel-branch reducers."""

from __future__ import annotations

from typing import Any, Mapping

from .state import merge_state


def merge_parallel_states(base: Mapping[str, Any], branches: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...]) -> dict[str, Any]:
    return merge_state(base, *branches)


def reduce_artifact_refs(branches: list[Mapping[str, str]] | tuple[Mapping[str, str], ...]) -> dict[str, str]:
    result: dict[str, str] = {}
    for branch in branches:
        for key, value in branch.items():
            if key in result and result[key] != value:
                raise ValueError(f"parallel artifact conflict on {key}")
            result[key] = value
    return result


__all__ = ["merge_parallel_states", "reduce_artifact_refs"]
