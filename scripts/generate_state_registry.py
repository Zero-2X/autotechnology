"""Generate a machine-readable state-transition registry from section 4.5."""
from __future__ import annotations

from pathlib import Path
import re
import yaml

ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = ROOT / "AI跨境技术内容自动化工作流开发清单_审计与优化版.md"
OUTPUT = ROOT / "docs/contracts/state-registry.yaml"


def main() -> None:
    lines = DOCUMENT.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "### 4.5 关键状态转换表")
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("### "))
    transitions = []
    for line_no, line in enumerate(lines[start:end], start + 1):
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
        if len(cells) < 6 or cells[0] == "对象":
            continue
        event = cells[5] if re.fullmatch(r"[a-z0-9_.]+", cells[5]) else None
        transitions.append(
            {
                "row": line_no,
                "aggregate": cells[0],
                "from_state": cells[1],
                "command": cells[2],
                "guard": cells[3],
                "to_state": cells[4],
                "event_type": event,
                "event_source_note": None if event else cells[5],
            }
        )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "source_document": DOCUMENT.name,
                "transition_count": len(transitions),
                "transitions": transitions,
            },
            allow_unicode=True,
            sort_keys=False,
            width=160,
        ),
        encoding="utf-8",
    )
    print(f"wrote {OUTPUT} ({len(transitions)} transitions)")


if __name__ == "__main__":
    main()
