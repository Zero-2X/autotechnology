from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
import sqlalchemy as sa


ROOT = Path(__file__).resolve().parents[2]
STAMP = "2026-09-20T12:00:00Z"


def insert(connection, table: str, row: dict) -> None:
    connection.execute(
        sa.text(f"INSERT INTO {table} ({','.join(row)}) VALUES ({','.join(':'+key for key in row)})"), row,
    )


def seed_predecessors(connection, *, org: str) -> dict[str, str]:
    actor, canonical_root, canonical_version, variant_root, variant_version, claim, policy = (
        str(uuid4()) for _ in range(7)
    )
    insert(connection, "canonical_contents", {
        "id": canonical_root, "org_id": org, "topic_brief_id": str(uuid4()), "stable_key": str(uuid4()),
        "current_version_id": None, "status": "approved", "created_by": actor,
        "created_at": STAMP, "updated_at": STAMP, "payload": "{}",
    })
    insert(connection, "canonical_content_versions", {
        "id": canonical_version, "org_id": org, "canonical_content_id": canonical_root,
        "topic_brief_id": str(uuid4()), "version_no": 1, "title": "Canonical", "abstract": "",
        "sections_json": "[]", "claims_json": "[]", "code_blocks_json": "[]", "examples_json": "[]",
        "limitations_json": "[]", "source_snapshot_refs_json": "[]", "knowledge_core_version_id": None,
        "input_snapshot_hash": "1" * 64, "content_hash": "2" * 64, "rights_snapshot_ids_json": "[]",
        "supersedes_version_id": None, "status": "approved", "created_by": actor, "created_at": STAMP,
        "payload": "{}",
    })
    insert(connection, "content_variants", {
        "id": variant_root, "org_id": org, "canonical_content_id": canonical_root, "locale": "en-US",
        "market": "US", "audience": "engineers", "current_version_id": None, "status": "active",
        "created_by": actor, "created_at": STAMP, "updated_at": STAMP, "payload": "{}",
    })
    variant_payload = {
        "id": variant_version, "org_id": org, "policy_snapshot_id": policy,
        "status": "approved", "snapshot_hash": "3" * 64,
    }
    insert(connection, "variant_versions", {
        "id": variant_version, "org_id": org, "content_variant_id": variant_root,
        "canonical_content_version_id": canonical_version, "region_profile_version_id": str(uuid4()),
        "version_no": 1, "status": "approved", "snapshot_hash": "3" * 64,
        "source_map_json": "[]", "created_by": actor, "created_at": STAMP,
        "payload": json.dumps(variant_payload),
    })
    claim_payload = {"id": claim, "org_id": org, "status": "verified", "freshness_status": "fresh"}
    insert(connection, "claims", {
        "id": claim, "org_id": org, "statement": "Verified fact", "fact_type": "product.fact",
        "entity_ids_json": "[]", "applicable_versions_json": "[]", "applicable_regions_json": "[]",
        "applicable_locales_json": "[]", "valid_from": None, "valid_to": None, "review_due_at": None,
        "supersedes_claim_id": None, "freshness_status": "fresh", "status": "verified", "version": 1,
        "content_hash": "4" * 64, "created_by": actor, "created_at": STAMP, "updated_at": STAMP,
        "payload": json.dumps(claim_payload),
    })
    return {"actor": actor, "variant": variant_version, "claim": claim, "policy": policy}


def version_row(*, org: str, script: str, variant: str, policy: str, actor: str, identity: str | None = None) -> dict:
    return {
        "id": identity or str(uuid4()), "org_id": org, "media_script_id": script,
        "variant_version_id": variant, "version_no": 1, "duration_seconds": 30,
        "locale": "en-US", "market": "US", "region_profile_version_id": str(uuid4()),
        "policy_snapshot_id": policy, "template_version": "media-script-v1", "status": "draft",
        "title": "Verified fact", "segments_json": '[{"sequence":1,"kind":"hook","text":"Verified fact"}]',
        "claim_refs_json": "[]", "claim_snapshot_hashes_json": "[]",
        "source_variant_snapshot_hash": "3" * 64, "word_count": 2,
        "estimated_duration_seconds": 0.8, "human_edited": False, "edit_reason": None,
        "supersedes_version_id": None, "snapshot_hash": "5" * 64,
        "created_by": actor, "created_at": STAMP,
    }


def test_media_001_migration_guards_append_only_lineage_and_downgrade(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = f"sqlite:///{(tmp_path / 'media001.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "20260920_media_001")
    engine = sa.create_engine(database_url)
    org, other = str(uuid4()), str(uuid4())
    script = str(uuid4())
    with engine.begin() as connection:
        facts = seed_predecessors(connection, org=org)
        insert(connection, "media_scripts", {
            "id": script, "org_id": org, "variant_version_id": facts["variant"], "duration_seconds": 30,
            "current_version_id": None, "status": "draft", "created_by": facts["actor"],
            "created_at": STAMP, "updated_at": STAMP,
        })
        version = version_row(org=org, script=script, variant=facts["variant"], policy=facts["policy"], actor=facts["actor"])
        insert(connection, "media_script_versions", version)
        connection.execute(sa.text("UPDATE media_scripts SET current_version_id=:version WHERE id=:script"),
                           {"version": version["id"], "script": script})
        insert(connection, "media_script_claim_refs", {
            "org_id": org, "script_version_id": version["id"], "claim_id": facts["claim"],
            "segment_sequence": 1, "source_block_ids_json": '["intro"]', "created_at": STAMP,
        })
        insert(connection, "media_script_commands", {
            "org_id": org, "namespace": "create", "idempotency_key": "create-1", "request_hash": "6" * 64,
            "media_script_id": script, "result_version_id": version["id"], "response_json": "{}",
            "actor_id": facts["actor"], "trace_id": "trace", "created_at": STAMP,
        })
        with pytest.raises(sa.exc.IntegrityError, match="version validation failed"):
            with connection.begin_nested():
                invalid = version_row(org=other, script=script, variant=facts["variant"], policy=facts["policy"], actor=facts["actor"])
                insert(connection, "media_script_versions", invalid)
        with pytest.raises(sa.exc.IntegrityError, match="Claim reference invalid"):
            with connection.begin_nested():
                insert(connection, "media_script_claim_refs", {
                    "org_id": other, "script_version_id": version["id"], "claim_id": facts["claim"],
                    "segment_sequence": 1, "source_block_ids_json": "[]", "created_at": STAMP,
                })
        with pytest.raises(sa.exc.IntegrityError, match="append-only"):
            with connection.begin_nested():
                connection.execute(sa.text("UPDATE media_script_versions SET title='changed' WHERE id=:id"), {"id": version["id"]})
        with pytest.raises(sa.exc.IntegrityError, match="append-only"):
            with connection.begin_nested():
                connection.execute(sa.text("DELETE FROM media_script_claim_refs WHERE script_version_id=:id"), {"id": version["id"]})
        with pytest.raises(sa.exc.IntegrityError, match="identity is immutable"):
            with connection.begin_nested():
                connection.execute(sa.text("UPDATE media_scripts SET duration_seconds=60 WHERE id=:id"), {"id": script})
        with pytest.raises(sa.exc.IntegrityError, match="version validation failed"):
            with connection.begin_nested():
                unsafe = version_row(org=org, script=script, variant=facts["variant"], policy=facts["policy"], actor=facts["actor"])
                unsafe["version_no"] = 2
                unsafe["segments_json"] = '[{"model":"raw-provider-output"}]'
                insert(connection, "media_script_versions", unsafe)

    command.downgrade(config, "20260920_site_004")
    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        for table in ("media_scripts", "media_script_versions", "media_script_claim_refs", "media_script_commands"):
            assert not inspector.has_table(table)
        assert inspector.has_table("variant_versions")
        assert inspector.has_table("claims")
        assert inspector.has_table("site_quality_reports")
    engine.dispose()
