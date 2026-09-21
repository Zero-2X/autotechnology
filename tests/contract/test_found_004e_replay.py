from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / "docs/tasks/FOUND-004E.md"
SCHEMA = ROOT / "packages/contracts/jsonschema/task-job.schema.json"
MIGRATION = ROOT / "packages/db/migrations/versions/20260916_found_004e_replay.py"


def test_replay_contract_and_task_card_are_explicit() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    task = TASK.read_text(encoding="utf-8")
    assert {"replayed_from_job_id", "replayed_from_attempt_count", "replay_reason"} <= set(schema["required"])
    assert "REPLAY_SOURCE_NOT_FOUND" in task
    assert "REPLAY_SECRET_INPUT" in task
    assert "policy/kill-switch" in task
    assert "20260916_found_004e_replay.py" in task
    assert MIGRATION.exists()


def test_replay_migration_is_a_reversible_noop_checkpoint() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "20260916_found_004e"' in source
    assert 'down_revision = "20260916_found_004d"' in source
    assert "def upgrade()" in source and "def downgrade()" in source
