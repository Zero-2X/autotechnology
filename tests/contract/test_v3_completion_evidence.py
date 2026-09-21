from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_v3_registry_and_evidence_are_synchronized() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_v3_completion_evidence.py"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
