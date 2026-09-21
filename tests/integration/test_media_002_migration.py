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


def _insert(connection, table: str, row: dict) -> None:
    columns = ",".join(row)
    connection.execute(sa.text(f"INSERT INTO {table} ({columns}) VALUES ({','.join(':'+key for key in row)})"), row)


def _seed_script(connection, *, org: str, actor: str) -> tuple[str, str, str, str, str]:
    canonical, variant_root, variant_version, policy, region = (str(uuid4()) for _ in range(5))
    claim = str(uuid4())
    _insert(connection, "canonical_contents", {
        "id": str(uuid4()), "org_id": org, "topic_brief_id": str(uuid4()), "stable_key": str(uuid4()),
        "current_version_id": None, "status": "approved", "created_by": actor,
        "created_at": STAMP, "updated_at": STAMP, "payload": "{}",
    })
    canonical_root = connection.execute(sa.text("SELECT id FROM canonical_contents WHERE org_id=:org"), {"org": org}).scalar_one()
    _insert(connection, "canonical_content_versions", {
        "id": canonical, "org_id": org, "canonical_content_id": canonical_root, "topic_brief_id": str(uuid4()),
        "version_no": 1, "title": "Canonical", "abstract": "", "sections_json": "[]", "claims_json": "[]",
        "code_blocks_json": "[]", "examples_json": "[]", "limitations_json": "[]", "source_snapshot_refs_json": "[]",
        "knowledge_core_version_id": None, "input_snapshot_hash": "1" * 64, "content_hash": "2" * 64,
        "rights_snapshot_ids_json": "[]", "supersedes_version_id": None, "status": "approved",
        "created_by": actor, "created_at": STAMP, "payload": "{}",
    })
    _insert(connection, "content_variants", {
        "id": variant_root, "org_id": org, "canonical_content_id": canonical_root, "locale": "en-US",
        "market": "US", "audience": "engineers", "current_version_id": None, "status": "active",
        "created_by": actor, "created_at": STAMP, "updated_at": STAMP, "payload": "{}",
    })
    _insert(connection, "variant_versions", {
        "id": variant_version, "org_id": org, "content_variant_id": variant_root,
        "canonical_content_version_id": canonical, "region_profile_version_id": region, "version_no": 1,
        "status": "approved", "snapshot_hash": "3" * 64, "source_map_json": "[]", "created_by": actor,
        "created_at": STAMP, "payload": json.dumps({"id": variant_version, "org_id": org, "policy_snapshot_id": policy, "status": "approved", "snapshot_hash": "3" * 64}),
    })
    _insert(connection, "claims", {
        "id": claim, "org_id": org, "statement": "Verified fact", "fact_type": "product.fact", "entity_ids_json": "[]",
        "applicable_versions_json": "[]", "applicable_regions_json": "[]", "applicable_locales_json": "[]",
        "valid_from": None, "valid_to": None, "review_due_at": None, "supersedes_claim_id": None,
        "freshness_status": "fresh", "status": "verified", "version": 1, "content_hash": "4" * 64,
        "created_by": actor, "created_at": STAMP, "updated_at": STAMP,
        "payload": json.dumps({"id": claim, "org_id": org, "status": "verified", "freshness_status": "fresh"}),
    })
    script = str(uuid4())
    _insert(connection, "media_scripts", {
        "id": script, "org_id": org, "variant_version_id": variant_version, "duration_seconds": 30,
        "current_version_id": None, "status": "draft", "created_by": actor, "created_at": STAMP, "updated_at": STAMP,
    })
    script_version = str(uuid4())
    _insert(connection, "media_script_versions", {
        "id": script_version, "org_id": org, "media_script_id": script, "variant_version_id": variant_version,
        "version_no": 1, "duration_seconds": 30, "locale": "en-US", "market": "US", "region_profile_version_id": region,
        "policy_snapshot_id": policy, "template_version": "media-script-v1", "status": "draft", "title": "Fact",
        "segments_json": json.dumps([
            {"sequence": 1, "kind": "hook", "text": "Hook", "start_ms": 0, "end_ms": 4000, "source_block_ids": [], "claim_refs": []},
            {"sequence": 2, "kind": "body", "text": "Body", "start_ms": 4000, "end_ms": 26000, "source_block_ids": [], "claim_refs": []},
            {"sequence": 3, "kind": "cta", "text": "CTA", "start_ms": 26000, "end_ms": 30000, "source_block_ids": [], "claim_refs": []},
        ]),
        "claim_refs_json": "[]", "claim_snapshot_hashes_json": "[]", "source_variant_snapshot_hash": "3" * 64,
        "word_count": 3, "estimated_duration_seconds": 30.0, "human_edited": False, "edit_reason": None,
        "supersedes_version_id": None, "snapshot_hash": "5" * 64, "created_by": actor, "created_at": STAMP,
    })
    return script_version, variant_version, region, policy, claim


def test_media_002_migration_guards_refs_append_only_and_downgrade(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = f"sqlite:///{(tmp_path / 'media002.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "20260920_media_002")
    engine = sa.create_engine(database_url)
    org, other, actor = str(uuid4()), str(uuid4()), str(uuid4())
    with engine.begin() as connection:
        script_version, variant, region, policy, _claim = _seed_script(connection, org=org, actor=actor)
        storyboard, version, shot = str(uuid4()), str(uuid4()), str(uuid4())
        _insert(connection, "media_storyboards", {
            "id": storyboard, "org_id": org, "media_script_version_id": script_version, "duration_seconds": 30,
            "current_version_id": None, "status": "draft", "created_by": actor, "created_at": STAMP, "updated_at": STAMP,
        })
        _insert(connection, "media_storyboard_versions", {
            "id": version, "org_id": org, "storyboard_id": storyboard, "media_script_version_id": script_version,
            "version_no": 1, "duration_seconds": 30, "locale": "en-US", "market": "US", "region_profile_version_id": region,
            "policy_snapshot_id": policy, "template_version": "media-storyboard-v1", "status": "draft",
            "shots_json": json.dumps([{"sequence": 1, "start_ms": 0, "end_ms": 4000}]), "asset_reference_count": 0, "rights_snapshot_ids_json": "[]",
            "revision_reason": None, "supersedes_version_id": None, "source_script_snapshot_hash": "5" * 64,
            "snapshot_hash": "6" * 64, "created_by": actor, "created_at": STAMP,
        })
        _insert(connection, "media_storyboard_shots", {
            "org_id": org, "storyboard_version_id": version, "sequence": 1, "script_segment_sequence": 1,
            "start_ms": 0, "end_ms": 4000, "purpose": "Hook", "transition": "cut", "asset_refs_json": "[]", "created_at": STAMP,
        })
        rights_record, rights_version = str(uuid4()), str(uuid4())
        _insert(connection, "rights_record_versions", {
            "id": rights_version, "org_id": org, "rights_record_id": rights_record, "version_no": 1,
            "source_snapshot_ids": json.dumps([str(uuid4())]), "license_ref": "license://fixture", "contract_ref": None,
            "evidence_object_refs": json.dumps(["private://evidence/1"]), "terms_snapshot_hash": "7" * 64,
            "rights_holder": "Holder", "permitted_regions": json.dumps(["US"]), "permitted_locales": json.dumps(["en-US"]),
            "permitted_media": json.dumps(["image"]), "permitted_use": "commercial", "valid_from": None, "valid_to": None,
            "status": "verified", "policy_rule_version": "rights-v1", "verified_by": actor, "verified_at": STAMP,
            "verification_reason": "reviewed", "supersedes_version_id": None, "snapshot_hash": "8" * 64,
            "created_by": actor, "created_at": STAMP, "payload": "{}",
        })
        _insert(connection, "media_storyboard_asset_refs", {
            "org_id": org, "storyboard_version_id": version, "shot_sequence": 1, "role": "visual",
            "asset_version_id": str(uuid4()), "media_type": "image", "format": "png", "storage_object_ref": "private://asset/1",
            "asset_snapshot_hash": "9" * 64, "rights_record_version_ids_json": json.dumps([rights_version]),
            "rights_snapshots_json": json.dumps([{"id": rights_version, "snapshot_hash": "8" * 64}]), "created_at": STAMP,
        })
        _insert(connection, "media_storyboard_commands", {
            "org_id": org, "namespace": "create", "idempotency_key": "one", "request_hash": "a" * 64,
            "storyboard_id": storyboard, "result_version_id": version, "response_json": "{}", "actor_id": actor,
            "trace_id": "trace", "created_at": STAMP,
        })
        with pytest.raises(sa.exc.IntegrityError, match="version validation failed"):
            with connection.begin_nested():
                bad = {
                    "id": str(uuid4()), "org_id": other, "storyboard_id": storyboard, "media_script_version_id": script_version,
                    "version_no": 2, "duration_seconds": 30, "locale": "en-US", "market": "US", "region_profile_version_id": region,
                    "policy_snapshot_id": policy, "template_version": "media-storyboard-v1", "status": "edited", "shots_json": json.dumps([{"sequence": 1}]),
                    "asset_reference_count": 0, "rights_snapshot_ids_json": "[]", "revision_reason": "x", "supersedes_version_id": None,
                    "source_script_snapshot_hash": "5" * 64, "snapshot_hash": "b" * 64, "created_by": actor, "created_at": STAMP,
                }
                _insert(connection, "media_storyboard_versions", bad)
        with pytest.raises(sa.exc.IntegrityError, match="append-only"):
            with connection.begin_nested():
                connection.execute(sa.text("UPDATE media_storyboard_shots SET purpose='changed' WHERE storyboard_version_id=:id"), {"id": version})
        with pytest.raises(sa.exc.IntegrityError, match="append-only"):
            with connection.begin_nested():
                connection.execute(sa.text("DELETE FROM media_storyboard_asset_refs WHERE storyboard_version_id=:id"), {"id": version})
        with pytest.raises(sa.exc.IntegrityError, match="identity is immutable"):
            with connection.begin_nested():
                connection.execute(sa.text("UPDATE media_storyboards SET duration_seconds=60 WHERE id=:id"), {"id": storyboard})
        with pytest.raises(sa.exc.IntegrityError, match="rights reference invalid|asset reference validation failed"):
            with connection.begin_nested():
                _insert(connection, "media_storyboard_asset_refs", {
                    "org_id": org, "storyboard_version_id": version, "shot_sequence": 1, "role": "music",
                    "asset_version_id": str(uuid4()), "media_type": "audio", "format": "wav", "storage_object_ref": "private://asset/2",
                    "asset_snapshot_hash": "a" * 64, "rights_record_version_ids_json": json.dumps([str(uuid4())]),
                    "rights_snapshots_json": "[]", "created_at": STAMP,
                })
    command.downgrade(config, "20260920_media_001")
    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        for table in ("media_storyboards", "media_storyboard_versions", "media_storyboard_shots", "media_storyboard_asset_refs", "media_storyboard_commands"):
            assert not inspector.has_table(table)
        assert inspector.has_table("media_script_versions")
        assert inspector.has_table("rights_record_versions")
    engine.dispose()
