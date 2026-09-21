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
SPEC = importlib.util.spec_from_file_location("media_005a_migration_fixture", ROOT / "tests/integration/test_media_004a_migration.py")
assert SPEC and SPEC.loader
FIXTURE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIXTURE)


def test_media_005a_migration_guards_qa_facts_and_rolls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = f"sqlite:///{(tmp_path / 'media005a.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "20260920_media_005a")
    engine = sa.create_engine(database_url)
    org, other, actor = str(uuid4()), str(uuid4()), str(uuid4())
    with engine.begin() as connection:
        script, visual, output, region, policy = FIXTURE._source(connection, org=org, actor=actor)
        job = str(uuid4())
        FIXTURE._insert(connection, "media_render_jobs", FIXTURE._job_row(org=org, actor=actor, script=script, visual=visual,
                       output=output, region=region, policy=policy, job=job))
        report = dict(id=str(uuid4()), org_id=org, subject_type="media_render_job", subject_id=job, render_job_id=job,
                      rule_version="media-005a/v1", status="passed", input_hash="a" * 64, report_hash="b" * 64,
                      finding_count=1, input_snapshot_json=json.dumps({"render_job_id": job}),
                      artifact_facts_json=json.dumps([]), created_by=actor, trace_id="trace", created_at=STAMP)
        FIXTURE._insert(connection, "media_qa_reports", report)
        finding = dict(org_id=org, report_id=report["id"], sequence=1, check_name="file_hash", code="FILE_HASH_MISMATCH",
                       severity="error", path="/artifacts/1/content_hash", message="hash differs",
                       observed_json=json.dumps("a" * 64), expected_json=json.dumps("b" * 64), artifact_id=None, created_at=STAMP)
        FIXTURE._insert(connection, "media_qa_findings", finding)
        FIXTURE._insert(connection, "media_qa_commands", dict(org_id=org, namespace="media-qa", idempotency_key="one",
                       request_hash="c" * 64, render_job_id=job, command="run_media_qa",
                       response_json=json.dumps({"report_id": report["id"], "status": "passed"}), actor_id=actor,
                       trace_id="trace", created_at=STAMP))
        with pytest.raises(sa.exc.IntegrityError, match="append-only"):
            with connection.begin_nested():
                connection.execute(sa.text("UPDATE media_qa_reports SET status='failed' WHERE id=:id"), {"id": report["id"]})
        with pytest.raises(sa.exc.IntegrityError, match="append-only"):
            with connection.begin_nested():
                connection.execute(sa.text("DELETE FROM media_qa_findings WHERE report_id=:id"), {"id": report["id"]})
        with pytest.raises(sa.exc.IntegrityError):
            with connection.begin_nested():
                FIXTURE._insert(connection, "media_qa_reports", {**report, "id": str(uuid4()), "org_id": other, "subject_id": job, "render_job_id": job})
    command.downgrade(config, "20260920_media_004b")
    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        for table in ("media_qa_reports", "media_qa_findings", "media_qa_commands"):
            assert not inspector.has_table(table)
        assert inspector.has_table("media_render_jobs")
    engine.dispose()
