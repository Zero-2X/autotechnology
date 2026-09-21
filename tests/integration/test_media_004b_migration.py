from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
import sqlalchemy as sa


ROOT = Path(__file__).resolve().parents[2]
STAMP = "2026-09-20T12:00:00Z"
_SPEC = importlib.util.spec_from_file_location("media_004a_migration_fixture_for_004b", ROOT / "tests/integration/test_media_004a_migration.py")
assert _SPEC and _SPEC.loader
_FIXTURE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURE)
_insert = _FIXTURE._insert


def test_media_004b_migration_guards_retry_facts_and_rolls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = f"sqlite:///{(tmp_path / 'media004b.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "20260920_media_004b")
    engine = sa.create_engine(database_url)
    org, other, actor = str(uuid4()), str(uuid4()), str(uuid4())
    with engine.begin() as connection:
        script, visual, output, region, policy = _FIXTURE._source(connection, org=org, actor=actor)
        job = str(uuid4())
        _insert(connection, "media_render_jobs", _FIXTURE._job_row(org=org, actor=actor, script=script, visual=visual,
               output=output, region=region, policy=policy, job=job))
        failure = dict(id=str(uuid4()), org_id=org, render_job_id=job, attempt_count=1,
                       error_class="transient", error_code="RENDER_BACKEND_UNAVAILABLE", message_redacted="temporary",
                       retryable=True, trace_id="trace", occurred_at=STAMP, idempotency_key="f-1", next_retry_at=STAMP)
        _insert(connection, "media_render_failures", failure)
        schedule = dict(id=str(uuid4()), org_id=org, render_job_id=job, attempt_count=1, failure_id=failure["id"],
                        available_at=STAMP, status="scheduled", delay_ms=1000, policy_max_attempts=3,
                        created_at=STAMP, claimed_at=None, completed_at=None)
        _insert(connection, "media_render_retry_schedules", schedule)
        _insert(connection, "media_render_retry_commands", dict(org_id=org, namespace="retry", idempotency_key="r-1",
               request_hash="c" * 64, render_job_id=job, command="retry", response_json=json.dumps({"status": "retry_scheduled"}),
               actor_id=actor, trace_id="trace", created_at=STAMP))
        target = dict(org_id=org, render_job_id=job, sequence=1, stage="scene", shot_sequence=2,
                      output_profile_key="square", input_hash="a" * 64, status="requested", artifact_sequence=None,
                      request_hash="d" * 64, created_at=STAMP)
        _insert(connection, "media_render_rerender_targets", target)
        connection.execute(sa.text("UPDATE media_render_retry_schedules SET status='claimed' WHERE id=:id"), {"id": schedule["id"]})
        with pytest.raises(sa.exc.IntegrityError, match="append-only"):
            with connection.begin_nested():
                connection.execute(sa.text("UPDATE media_render_failures SET error_code='OTHER' WHERE id=:id"), {"id": failure["id"]})
        with pytest.raises(sa.exc.IntegrityError):
            with connection.begin_nested():
                _insert(connection, "media_render_failures", {**failure, "id": str(uuid4()), "org_id": other})
        with pytest.raises(sa.exc.IntegrityError):
            with connection.begin_nested():
                _insert(connection, "media_render_rerender_targets", {**target, "sequence": 2, "request_hash": "e" * 64, "input_hash": "b" * 64})
    command.downgrade(config, "20260920_media_004a")
    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        for table in ("media_render_failures", "media_render_retry_schedules", "media_render_retry_commands", "media_render_rerender_targets"):
            assert not inspector.has_table(table)
        assert inspector.has_table("media_render_jobs")
    engine.dispose()
