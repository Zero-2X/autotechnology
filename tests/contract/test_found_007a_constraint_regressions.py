import pytest

from scripts.check_openapi_compatibility import _narrowed


@pytest.mark.parametrize("constraint", [
    {"minLength": 3}, {"maxLength": 5}, {"minimum": 1}, {"maximum": 5},
    {"exclusiveMinimum": 1}, {"exclusiveMaximum": 5}, {"enum": ["a"]}, {"pattern": "^a"},
])
def test_removing_constraint_widens_and_adding_constraint_narrows(constraint):
    assert _narrowed({"constraints": constraint}, {"constraints": {}}) == []
    assert _narrowed({"constraints": {}}, {"constraints": constraint})


@pytest.mark.parametrize("before,after,narrowed", [
    ({"minimum": 1}, {"exclusiveMinimum": 1}, True),
    ({"exclusiveMinimum": 1}, {"minimum": 1}, False),
    ({"maximum": 5}, {"exclusiveMaximum": 5}, True),
    ({"exclusiveMaximum": 5}, {"maximum": 5}, False),
    ({"minimum": 3, "exclusiveMinimum": 1}, {"minimum": 3}, False),
    ({"maximum": 3, "exclusiveMaximum": 5}, {"exclusiveMaximum": 3}, True),
    ({"enum": ["a"]}, {"enum": ["a", "b"]}, False),
    ({"enum": ["a", "b"]}, {"enum": ["a"]}, True),
])
def test_effective_bound_and_enum_changes(before, after, narrowed):
    assert bool(_narrowed({"constraints": before}, {"constraints": after})) is narrowed
