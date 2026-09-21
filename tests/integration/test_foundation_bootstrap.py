from pathlib import Path

import sqlalchemy as sa

from scripts.bootstrap_foundation_db import bootstrap, legacy_statements
from scripts.check_migrations import analyze_migrations


def test_empty_database_and_repeat_bootstrap_preserve_rows(tmp_path: Path, monkeypatch):
    # A caller-supplied connection must win over unrelated ambient config.
    monkeypatch.setenv("DATABASE_URL", "postgresql://invalid.example/never-connect")
    engine = sa.create_engine(f"sqlite:///{(tmp_path / 'bootstrap.db').as_posix()}")
    try:
        with engine.begin() as connection:
            bootstrap(connection)
            tables = set(sa.inspect(connection).get_table_names())
            assert {"task_jobs", "task_job_leases", "task_failures", "human_tasks",
                    "outbox_events", "policy_versions", "storage_object_metadata"} <= tables
            connection.exec_driver_sql("CREATE TABLE synthetic_sentinel (value TEXT)")
            connection.exec_driver_sql("INSERT INTO synthetic_sentinel VALUES ('keep')")
        with engine.begin() as connection:
            bootstrap(connection)
            assert connection.exec_driver_sql("SELECT value FROM synthetic_sentinel").scalar_one() == "keep"
            assert connection.exec_driver_sql("SELECT COUNT(*) FROM migration_framework_baselines").scalar_one() == 1
            assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == analyze_migrations()["heads"][0]
            indexes = sa.inspect(connection).get_indexes("task_jobs")
            assert {"idx_task_jobs_poll_ready", "idx_task_jobs_aggregate"} <= {i["name"] for i in indexes}
    finally:
        engine.dispose()


def test_legacy_preflight_is_explicit_and_non_destructive():
    statements = legacy_statements()
    assert len(statements) == 16
    assert all(s.startswith(("CREATE TABLE IF NOT EXISTS", "CREATE INDEX IF NOT EXISTS")) for s in statements)
