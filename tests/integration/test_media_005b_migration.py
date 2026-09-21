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
SPEC = importlib.util.spec_from_file_location("media_005b_migration_fixture", ROOT / "tests/integration/test_media_005a_migration.py")
assert SPEC and SPEC.loader
FIXTURE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIXTURE)


def test_media_005b_migration_guards_content_evidence_and_rolls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = f"sqlite:///{(tmp_path / 'media005b.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "20260920_media_005b")
    engine = sa.create_engine(database_url)
    org, actor = str(uuid4()), str(uuid4())
    with engine.begin() as connection:
        script, visual, output, region, policy = FIXTURE.FIXTURE._source(connection, org=org, actor=actor)
        job = str(uuid4())
        FIXTURE.FIXTURE._insert(connection, "media_render_jobs", FIXTURE.FIXTURE._job_row(org=org, actor=actor, script=script, visual=visual,
                              output=output, region=region, policy=policy, job=job))
        report = dict(id=str(uuid4()), org_id=org, subject_type="media_render_job", subject_id=job, render_job_id=job,
                      rule_version="media-005b/v1", status="passed", input_hash="a" * 64, report_hash="b" * 64,
                      finding_count=0, input_snapshot_json=json.dumps({}), artifact_facts_json=json.dumps([]),
                      created_by=actor, trace_id="trace", created_at=STAMP)
        FIXTURE.FIXTURE._insert(connection, "media_qa_reports", report)
        row = dict(org_id=org, report_id=report["id"], sequence=1, check_name="rights", source_hash="c" * 64,
                   observed_hash="d" * 64, rights_snapshot_hash="e" * 64, evidence_json=json.dumps({"rights_id": str(uuid4())}), created_at=STAMP)
        FIXTURE.FIXTURE._insert(connection, "media_qa_content_evaluations", row)
        with pytest.raises(sa.exc.IntegrityError, match="append-only"):
            with connection.begin_nested():
                connection.execute(sa.text("UPDATE media_qa_content_evaluations SET check_name='numbers' WHERE report_id=:id"), {"id": report["id"]})
        with pytest.raises(sa.exc.IntegrityError, match="append-only"):
            with connection.begin_nested():
                connection.execute(sa.text("DELETE FROM media_qa_content_evaluations WHERE report_id=:id"), {"id": report["id"]})
    command.downgrade(config, "20260920_media_005a")
    with engine.connect() as connection:
        assert not sa.inspect(connection).has_table("media_qa_content_evaluations")
        assert sa.inspect(connection).has_table("media_qa_reports")
    engine.dispose()
