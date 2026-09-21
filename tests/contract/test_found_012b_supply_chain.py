from __future__ import annotations

import json
from pathlib import Path

from scripts.check_supply_chain import generate, verify


def test_supply_chain_artifacts_are_reproducible_and_verified(tmp_path: Path) -> None:
    generate(tmp_path)
    assert verify(tmp_path) == []
    assert json.loads((tmp_path / "scan-report.json").read_text())['status'] == "pass"


def test_supply_chain_fails_closed_when_attestation_changes(tmp_path: Path) -> None:
    generate(tmp_path)
    attestation = tmp_path / "artifact-attestation.json"
    payload = json.loads(attestation.read_text())
    payload["digest"] = "sha256:tampered"
    attestation.write_text(json.dumps(payload))
    assert any("attestation" in error for error in verify(tmp_path))
