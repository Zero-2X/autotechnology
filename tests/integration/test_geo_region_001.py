from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker
import pytest

from modules.geo_region import InMemoryRegionService


ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def _payload() -> dict[str, object]:
    return {
        "locales": ["en-US", "fr-FR"], "timezone": "Europe/Paris",
        "date_number_format": "DD/MM/YYYY | 1 234,56", "units": "metric", "currency": "EUR",
        "terminology_version": "legal-v3", "disclosure_rules": [{"name": "sponsorship", "required": True}],
        "restricted_topics": ["medical-claims"], "data_residency": "EU",
        "retention_days": 90, "deletion_sla_hours": 48, "platform_eligibility": ["web"],
        "policy_snapshot_id": uuid4(), "valid_from": NOW, "valid_to": NOW + timedelta(days=90),
        "review_due_at": NOW + timedelta(days=30),
    }


def test_geo_region_end_to_end_contract_events_and_audit() -> None:
    service = InMemoryRegionService(clock=lambda: NOW)
    org_id, actor = uuid4(), uuid4()
    profile = service.create_profile(org_id=org_id, region_code="EU-FR", actor_id=actor, trace_id="trace-profile", idempotency_key="p1")
    draft = service.create_draft(org_id=org_id, profile_id=profile.id, idempotency_key="v1", expected_current_version_id=None, **_payload())
    active = service.activate_version(org_id=org_id, version_id=draft.id, expected_version=1, idempotency_key="a1", actor_id=actor, trace_id="trace-activate")

    profile_schema = json.loads((ROOT / "packages/contracts/jsonschema/region-profile.schema.json").read_text(encoding="utf-8"))
    version_schema = json.loads((ROOT / "packages/contracts/jsonschema/region-profile-version.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(profile_schema, format_checker=FormatChecker()).validate(service.get_profile(org_id=org_id, profile_id=profile.id).as_contract())
    Draft202012Validator(version_schema, format_checker=FormatChecker()).validate(active.as_contract())
    assert service.get_profile(org_id=org_id, profile_id=profile.id).current_version_id == active.id
    assert {event["event_type"] for event in service.events} == {"region.profile.created", "region.profile_version.created", "region.profile_version.activated"}
    assert all(event["org_id"] == str(org_id) and event["payload_hash"] for event in service.events)
    assert {entry["status"] for entry in service.audit} == {"active", "draft"}
    assert all(entry["trace_id"] for entry in service.audit)


def test_geo_region_isolation_and_replay_hold_across_service_queries() -> None:
    service = InMemoryRegionService(clock=lambda: NOW)
    first_org, second_org = uuid4(), uuid4()
    first = service.create_profile(org_id=first_org, region_code="US", idempotency_key="p")
    second = service.create_profile(org_id=second_org, region_code="US", idempotency_key="p")
    assert first.id != second.id
    assert [item.region_code for item in service.list_profiles(org_id=first_org)] == ["US"]
    assert service.list_profiles(org_id=second_org)[0].org_id == second_org
    assert service.audit_for(org_id=first_org)

    replay = service.create_profile(org_id=first_org, region_code="US", idempotency_key="p", actor_id=uuid4(), trace_id="ignored")
    assert replay == first and len(service.events) == 2


def test_sqlite_migration_guards_region_references_lifecycle_and_rollback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the real Alembic revisions against a disposable SQLite database."""
    from alembic import command
    from alembic.config import Config
    import sqlalchemy as sa

    database_url = f"sqlite:///{(tmp_path / 'geo-region.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "20260920_geo_content_003")
    command.upgrade(config, "20260920_geo_region_001")
    engine = sa.create_engine(database_url)
    org_id, other_org = str(uuid4()), str(uuid4())
    profile_id, version_id = str(uuid4()), str(uuid4())
    now = NOW.isoformat().replace("+00:00", "Z")
    valid_version = {
        "id": version_id, "org_id": org_id, "region_profile_id": profile_id, "version_no": 1,
        "region_code": "EU-FR", "locales": '["fr-FR"]', "timezone": "Europe/Paris",
        "date_number_format": "DD/MM/YYYY", "units": "metric", "currency": "EUR",
        "terminology_version": "terms-v1", "disclosure_rules": '["sponsor"]',
        "restricted_topics": '["medical"]', "data_residency": "EU", "retention_days": 90,
        "deletion_sla_hours": 48, "platform_eligibility": '["web"]', "policy_snapshot_id": None,
        "valid_from": now, "valid_to": (NOW + timedelta(days=30)).isoformat().replace("+00:00", "Z"),
        "review_due_at": (NOW + timedelta(days=7)).isoformat().replace("+00:00", "Z"),
        "status": "draft", "snapshot_hash": "a" * 64, "created_by": str(uuid4()), "created_at": now,
    }
    with engine.begin() as connection:
        tables = set(sa.inspect(connection).get_table_names())
        assert {"region_profiles", "region_profile_versions", "site_page_versions", "geo_runs"} <= tables
        fk = connection.execute(sa.text("PRAGMA foreign_key_list(region_profile_versions)")).mappings().all()
        assert {row["from"] for row in fk} >= {"org_id", "region_profile_id"}
        connection.execute(sa.text("INSERT INTO region_profiles VALUES (:id,:org,:code,NULL,'active',:at)"), {"id": profile_id, "org": org_id, "code": "EU-FR", "at": now})
        connection.execute(sa.text("INSERT INTO region_profile_versions (" + ",".join(valid_version) + ") VALUES (" + ",".join(f":{key}" for key in valid_version) + ")"), valid_version)
        # Same tenant profile/version references are accepted; cross-tenant references are rejected.
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(sa.text("INSERT INTO region_profile_versions (" + ",".join(valid_version) + ") VALUES (" + ",".join(f":{key}" for key in valid_version) + ")"), valid_version | {"id": str(uuid4()), "org_id": other_org})
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(sa.text("INSERT OR REPLACE INTO region_profiles VALUES (:id,:org,:code,NULL,'active',:at)"), {"id": profile_id, "org": org_id, "code": "EU-FR", "at": now})
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(sa.text("DELETE FROM region_profile_versions WHERE id=:id"), {"id": version_id})
        connection.execute(sa.text("UPDATE region_profile_versions SET status='active' WHERE id=:id"), {"id": version_id})
        connection.execute(sa.text("UPDATE region_profile_versions SET status='retired' WHERE id=:id"), {"id": version_id})
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(sa.text("UPDATE region_profile_versions SET currency='USD' WHERE id=:id"), {"id": version_id})
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(sa.text("UPDATE region_profiles SET region_code='EU-DE' WHERE id=:id"), {"id": profile_id})

        site_id = str(uuid4())
        site_columns = "id,org_id,site_page_id,version_no,canonical_content_version_id,variant_version_id,region_profile_version_id,locale,url_path,render_mode,status,snapshot_hash,published_at,created_by,created_at,payload"
        site_values = {"id": site_id, "org": org_id, "page": str(uuid4()), "canonical": str(uuid4()), "region": version_id, "at": now}
        site_sql = "INSERT INTO site_page_versions (" + site_columns + ") VALUES (:id,:org,:page,1,:canonical,NULL,:region,'fr-FR','/fr','ssr','ready',:hash,NULL,:actor,:at,'{}')"
        site_values |= {"hash": "b" * 64, "actor": str(uuid4()), "at": now}
        connection.execute(sa.text(site_sql), site_values)
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(sa.text(site_sql), site_values | {"id": str(uuid4()), "region": str(uuid4())})
        # GEO_CONTENT-003's geo_runs guard requires a ready/published page and active fixture.
        fixture_id, fixture_hash = str(uuid4()), "c" * 64
        connection.execute(sa.text("INSERT INTO geo_query_fixtures (id,org_id,query,locale,region,expected_entities,expected_claim_ids,status,version,fixture_hash,created_by,created_at,updated_by,updated_at,payload) VALUES (:id,:org,'q','fr-FR','EU-FR','[]','[]','active',1,:hash,:actor,:at,NULL,NULL,'{}')"), {"id": fixture_id, "org": org_id, "hash": fixture_hash, "actor": str(uuid4()), "at": now})
        connection.execute(sa.text("INSERT INTO geo_runs (id,org_id,page_version_id,query_fixture_id,locale,region,sample_count,parser_version,mention_count,citation_count,position_values,correctness_values,confidence,data_quality,fixture_hash,status,created_at,payload) VALUES (:id,:org,:page,:fixture,'fr-FR','EU-FR',2,'p1',0,0,'[1,2]','[\"correct\"]',0.9,'estimated',:hash,'planned',:at,'{}')"), {"id": str(uuid4()), "org": org_id, "page": site_id, "fixture": fixture_id, "hash": fixture_hash, "at": now})
    command.downgrade(config, "20260920_geo_content_003")
    with engine.connect() as connection:
        assert "geo_runs" in set(sa.inspect(connection).get_table_names())
        assert "region_profiles" not in set(sa.inspect(connection).get_table_names())
