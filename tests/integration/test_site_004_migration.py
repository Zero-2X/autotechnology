from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
import sqlalchemy as sa


ROOT = Path(__file__).resolve().parents[2]
STAMP = "2026-09-20T12:00:00Z"


def _seed_page(connection, *, org: str, page: str, version: str, status: str = "published") -> None:
    actor = str(uuid4())
    profile = str(uuid4())
    region = str(uuid4())
    connection.execute(sa.text(
        "INSERT INTO region_profiles (id,org_id,region_code,current_version_id,status,created_at) "
        "VALUES (:id,:org,'US',NULL,'active',:at)"
    ), {"id": profile, "org": org, "at": STAMP})
    connection.execute(sa.text(
        "INSERT INTO region_profile_versions "
        "(id,org_id,region_profile_id,version_no,region_code,locales,timezone,date_number_format,units,currency,"
        "terminology_version,disclosure_rules,restricted_topics,data_residency,retention_days,deletion_sla_hours,"
        "platform_eligibility,policy_snapshot_id,valid_from,valid_to,review_due_at,status,snapshot_hash,created_by,created_at) "
        "VALUES (:id,:org,:profile,1,'US','[\"en-US\"]','UTC','YYYY-MM-DD','imperial','USD','v1','[]','[]','US',"
        "30,24,'[\"web\"]',NULL,NULL,NULL,NULL,'active',:hash,:actor,:at)"
    ), {"id": region, "org": org, "profile": profile, "hash": "a" * 64, "actor": actor, "at": STAMP})
    connection.execute(sa.text(
        "INSERT INTO site_pages (id,org_id,page_key,locale,url_path,current_version_id,created_by,created_at,updated_at,payload) "
        "VALUES (:id,:org,'guide','en-US','/guide',NULL,:actor,:at,:at,'{}')"
    ), {"id": page, "org": org, "actor": actor, "at": STAMP})
    connection.execute(sa.text(
        "INSERT INTO site_page_versions "
        "(id,org_id,site_page_id,version_no,canonical_content_version_id,variant_version_id,region_profile_version_id,"
        "locale,url_path,render_mode,status,snapshot_hash,published_at,created_by,created_at,payload) "
        "VALUES (:id,:org,:page,1,:canonical,NULL,:region,'en-US','/guide','ssr',:status,:hash,:at,:actor,:at,'{}')"
    ), {
        "id": version, "org": org, "page": page, "canonical": str(uuid4()), "region": region,
        "status": status, "hash": "b" * 64, "at": STAMP, "actor": actor,
    })


def _report(*, org: str, version: str, identity: str | None = None) -> dict:
    return {
        "id": identity or str(uuid4()), "org_id": org, "site_page_version_id": version,
        "page_key": "guide", "canonical_url": "https://example.com/guide", "status": "passed",
        "rule_version": "site-004.v1", "threshold_version": "site-performance-v1",
        "input_snapshot_hash": "1" * 64, "source_html_hash": "2" * 64, "dynamic_html_hash": None,
        "thresholds_json": '{"lcp_ms":2500}', "metrics_json": '{"lcp_ms":1000}',
        "checks_json": "[]", "findings_json": "[]", "summary_json": '{"total":0}',
        "request_hash": "3" * 64, "report_hash": "4" * 64, "idempotency_key": str(uuid4()),
        "evaluated_at": STAMP, "actor_id": str(uuid4()), "trace_id": "trace-site-004", "created_at": STAMP,
    }


def _insert(connection, row: dict) -> None:
    columns = ",".join(row)
    connection.execute(
        sa.text(f"INSERT INTO site_quality_reports ({columns}) VALUES ({','.join(':'+name for name in row)})"),
        row,
    )


def test_site_004_migration_guards_projection_and_preserves_predecessors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = f"sqlite:///{(tmp_path / 'site004.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "20260920_site_004")
    engine = sa.create_engine(database_url)
    org, other = str(uuid4()), str(uuid4())
    page, version = str(uuid4()), str(uuid4())
    with engine.begin() as connection:
        _seed_page(connection, org=org, page=page, version=version)
        row = _report(org=org, version=version)
        _insert(connection, row)
        with pytest.raises(sa.exc.IntegrityError, match="tenant reference invalid"):
            with connection.begin_nested():
                _insert(connection, _report(org=other, version=version))
        with pytest.raises(sa.exc.IntegrityError, match="raw content or credentials"):
            with connection.begin_nested():
                unsafe = _report(org=org, version=version)
                unsafe["checks_json"] = '[{"html":"<main>raw</main>"}]'
                _insert(connection, unsafe)
        with pytest.raises(sa.exc.IntegrityError, match="hash projection invalid"):
            with connection.begin_nested():
                invalid_hash = _report(org=org, version=version)
                invalid_hash["report_hash"] = "not-a-hash"
                _insert(connection, invalid_hash)
        with pytest.raises(sa.exc.IntegrityError, match="append-only"):
            with connection.begin_nested():
                connection.execute(sa.text(
                    "UPDATE site_quality_reports SET status='blocked' WHERE id=:id"
                ), {"id": row["id"]})
        with pytest.raises(sa.exc.IntegrityError, match="append-only"):
            with connection.begin_nested():
                connection.execute(sa.text("DELETE FROM site_quality_reports WHERE id=:id"), {"id": row["id"]})

    command.downgrade(config, "20260920_geo_region_002")
    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        assert not inspector.has_table("site_quality_reports")
        assert inspector.has_table("site_page_versions")
        assert inspector.has_table("region_policy_decisions")
    engine.dispose()
