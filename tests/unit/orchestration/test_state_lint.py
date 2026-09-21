from pathlib import Path

import pytest

from orchestration.state import StateViolation
from orchestration.state_lint import lint_source, lint_state


def test_state_lint_bounds_size_and_forbidden_fields(tmp_path: Path):
    with pytest.raises(StateViolation): lint_state({"run_id": "bad"})
    with pytest.raises(StateViolation): lint_state({"token": "bad"})
    source = tmp_path / "safe.py"
    source.write_text("value = 'secret'\n", encoding="utf-8")
    assert lint_source(source)
