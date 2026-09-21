"""Deterministic Graph golden-set and cost evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class GoldenCase:
    case_id: str
    input_refs: dict[str, str]
    expected_refs: dict[str, str]
    tags: tuple[str, ...] = ()


class GoldenSet:
    def __init__(self, cases: list[GoldenCase] | tuple[GoldenCase, ...] = ()) -> None:
        self.cases = tuple(cases)

    def add(self, case: GoldenCase) -> None:
        if any(item.case_id == case.case_id for item in self.cases):
            raise ValueError("golden case already exists")
        self.cases = (*self.cases, case)


class GraphEvaluator:
    def evaluate(self, golden: GoldenSet, runner: Callable[[Mapping[str, str]], Mapping[str, Any]]) -> dict[str, Any]:
        results = []
        for case in golden.cases:
            output = dict(runner(case.input_refs))
            actual = output.get("result_refs", {})
            matched = all(actual.get(key) == value for key, value in case.expected_refs.items())
            results.append({"case_id": case.case_id, "passed": matched, "expected": dict(case.expected_refs), "actual": dict(actual)})
        return {"total": len(results), "passed": sum(1 for item in results if item["passed"]),
                "failed": sum(1 for item in results if not item["passed"]), "cases": results}


__all__ = ["GoldenCase", "GoldenSet", "GraphEvaluator"]
