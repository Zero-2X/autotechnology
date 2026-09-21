from pathlib import Path
import sys

import yaml

from scripts import check_task_card_precision as checker


def test_v3_task_precision_uses_separate_registry(tmp_path: Path, monkeypatch, capsys):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "task-registry-langgraph-v3.yaml").write_text(yaml.safe_dump({"tasks": [
        {"id": "GRAPH-GOV-001", "task_spec_ref": "docs/card.md", "tier": "P0"}
    ]}), encoding="utf-8")
    card = docs / "card.md"
    card.write_text("\n".join(checker.REQUIRED), encoding="utf-8")
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["precision", "--task", "GRAPH-GOV-001", "--strict"])
    assert checker.main() == 0
    assert "precise=1" in capsys.readouterr().out
    card.write_text("# unfinished", encoding="utf-8")
    assert checker.main() == 1
    monkeypatch.setattr(sys, "argv", ["precision", "--task", "GRAPH-UNKNOWN", "--strict"])
    assert checker.main() == 1
    assert "unknown task" in capsys.readouterr().out
