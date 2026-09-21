from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _version_row(org_id: str, profile_id: str, version_id: str) -> dict[str, str | int | None]:
    return {
        "id": version_id,
        "org_id": org_id,
        "region_profile_id": profile_id,
        "version_no": 1,
        "region_code": "EU-FR",
        "locales": '["fr-FR"]',
        "timezone": "Europe/Paris",
        "date_number_format": "DD/MM/YYYY",
        "units": "metric",
        "currency": "EUR",
        "terminology_version": "terms-v1",
        "disclosure_rules": "[]",
        "restricted_topics": "[]",
        "data_residency": "EU",
        "retention_days": 30,
        "deletion_sla_hours": 24,
        "platform_eligibility": '["web"]',
        "policy_snapshot_id": None,
        "valid_from": NOW,
        "valid_to": None,
        "review_due_at": None,
        "status": "active",
        "snapshot_hash": "a" * 64,
        "created_by": str(uuid4()),
        "created_at": NOW,
    }


def test_geo_region_002_sqlite_projection_guards_and_downgrade(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sa = pytest.importorskip("sqlalchemy")
    command = pytest.importorskip("alembic.command")
    config_module = pytest.importorskip("alembic.config")
    database_url = f"sqlite:///{(tmp_path / 'geo-region-002.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = config_module.Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "20260920_geo_region_002")

    engine = sa.create_engine(database_url)
    org_id, other_org = str(uuid4()), str(uuid4())
    profile_id, version_id = str(uuid4()), str(uuid4())
    with engine.begin() as connection:
        connection.execute(
            sa.text("INSERT INTO region_profiles (id,org_id,region_code,current_version_id,status,created_at) VALUES (:id,:org,:code,NULL,'active',:at)"),
            {"id": profile_id, "org": org_id, "code": "EU-FR", "at": NOW},
        )
        version = _version_row(org_id, profile_id, version_id)
        columns = ",".join(version)
        connection.execute(
            sa.text(f"INSERT INTO region_profile_versions ({columns}) VALUES ({','.join(':'+key for key in version)})"),
            version,
        )
        values = {
            "id": str(uuid4()),
            "org_id": org_id,
            "decision_type": "page",
            "region_profile_version_id": version_id,
            "page_version_id": None,
            "page_key": "guide",
            "locale": "fr-FR",
            "market": "EU-FR",
            "region": "EU-FR",
            "decision": "eligible",
            "status": "eligible",
            "checks_json": "[]",
            "reasons_json": "[]",
            "hreflang_json": "[]",
            "targets_json": "[]",
            "required_disclosures_json": "[]",
            "matched_restrictions_json": "[]",
            "input_snapshot_hash": "b" * 64,
            "decision_hash": "c" * 64,
            "request_hash": "d" * 64,
            "idempotency_key": "check-1",
            "actor_id": str(uuid4()),
            "trace_id": "trace-1",
            "created_at": NOW,
        }
        columns = ",".join(values)
        connection.execute(
            sa.text(f"INSERT INTO region_policy_decisions ({columns}) VALUES ({','.join(':'+key for key in values)})"),
            values,
        )
        with pytest.raises(sa.exc.IntegrityError, match="tenant reference invalid"):
            connection.execute(
                sa.text(f"INSERT INTO region_policy_decisions ({columns}) VALUES ({','.join(':'+key for key in values)})"),
                values | {"id": str(uuid4()), "org_id": other_org},
            )
        with pytest.raises(sa.exc.IntegrityError, match="raw body"):
            connection.execute(
                sa.text("INSERT INTO region_policy_decisions (id,org_id,decision_type,region_profile_version_id,status,checks_json,input_snapshot_hash,decision_hash,request_hash,created_at) VALUES (:id,:org,'page',:version,'eligible',:checks,:input,:decision,:request,:at)"),
                {"id": str(uuid4()), "org": org_id, "version": version_id, "checks": '[{"answer":"secret"}]', "input": "e" * 64, "decision": "f" * 64, "request": "1" * 64, "at": NOW},
            )
        with pytest.raises(sa.exc.IntegrityError, match="append-only"):
            connection.execute(sa.text("UPDATE region_policy_decisions SET status='deny' WHERE id=:id"), {"id": values["id"]})
        with pytest.raises(sa.exc.IntegrityError, match="append-only"):
            connection.execute(sa.text("DELETE FROM region_policy_decisions WHERE id=:id"), {"id": values["id"]})

    command.downgrade(config, "20260920_geo_region_001")
    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        assert not inspector.has_table("region_policy_decisions")
        assert inspector.has_table("region_profiles")
        assert inspector.has_table("region_profile_versions")
