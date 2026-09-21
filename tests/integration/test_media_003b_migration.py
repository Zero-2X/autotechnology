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
_SPEC = importlib.util.spec_from_file_location("media_002_migration_fixture", ROOT / "tests/integration/test_media_002_migration.py")
assert _SPEC and _SPEC.loader
_FIXTURE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURE)
_insert = _FIXTURE._insert
_seed_script = _FIXTURE._seed_script


def test_media_003b_migration_guards_items_and_downgrade(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = f"sqlite:///{(tmp_path / 'media003b.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "20260920_media_003b")
    engine = sa.create_engine(database_url)
    org, other, actor = str(uuid4()), str(uuid4()), str(uuid4())
    with engine.begin() as connection:
        script_version, _variant, region, policy, _claim = _seed_script(connection, org=org, actor=actor)
        asset_set, version = str(uuid4()), str(uuid4())
        _insert(connection, "media_visual_asset_sets", {
            "id": asset_set, "org_id": org, "media_script_version_id": script_version, "media_storyboard_version_id": None,
            "duration_seconds": 30, "current_version_id": None, "status": "draft", "created_by": actor,
            "created_at": STAMP, "updated_at": STAMP,
        })
        rights_id = str(uuid4())
        _insert(connection, "rights_record_versions", {
            "id": rights_id, "org_id": org, "rights_record_id": str(uuid4()), "version_no": 1,
            "source_snapshot_ids": json.dumps([str(uuid4())]), "license_ref": "license://fixture", "contract_ref": None,
            "evidence_object_refs": json.dumps(["private://evidence/1"]), "terms_snapshot_hash": "7" * 64,
            "rights_holder": "Holder", "permitted_regions": json.dumps(["US"]), "permitted_locales": json.dumps(["en-US"]),
            "permitted_media": json.dumps(["image"]), "permitted_use": "commercial", "valid_from": None, "valid_to": None,
            "status": "verified", "policy_rule_version": "rights-v1", "verified_by": actor, "verified_at": STAMP,
            "verification_reason": "reviewed", "supersedes_version_id": None, "snapshot_hash": "8" * 64,
            "created_by": actor, "created_at": STAMP, "payload": "{}",
        })
        _insert(connection, "media_visual_asset_set_versions", {
            "id": version, "org_id": org, "set_id": asset_set, "media_script_version_id": script_version,
            "media_storyboard_version_id": None, "version_no": 1, "duration_seconds": 30, "region_profile_version_id": region,
            "policy_snapshot_id": policy, "template_version": "media-visual-asset-set-v1", "status": "draft",
            "items_json": json.dumps([{"sequence": 1, "role": "cover"}]), "item_count": 1,
            "rights_snapshot_ids_json": json.dumps([rights_id]), "revision_reason": None, "supersedes_version_id": None,
            "source_script_snapshot_hash": "5" * 64, "source_storyboard_snapshot_hash": None, "snapshot_hash": "6" * 64,
            "created_by": actor, "created_at": STAMP,
        })
        _insert(connection, "media_visual_asset_items", {
            "org_id": org, "set_version_id": version, "sequence": 1, "role": "cover", "asset_version_id": str(uuid4()),
            "media_type": "image", "format": "png", "storage_object_ref": "private://asset/1", "asset_snapshot_hash": "9" * 64,
            "timestamp_ms": None, "alt_text": "Cover", "rights_record_version_ids_json": json.dumps([rights_id]),
            "rights_snapshots_json": json.dumps([{"id": rights_id, "snapshot_hash": "8" * 64}]), "created_at": STAMP,
        })
        _insert(connection, "media_visual_asset_commands", {
            "org_id": org, "namespace": "create", "idempotency_key": "one", "request_hash": "a" * 64,
            "set_id": asset_set, "result_version_id": version, "response_json": "{}", "actor_id": actor,
            "trace_id": "trace", "created_at": STAMP,
        })
        with pytest.raises(sa.exc.IntegrityError, match="version validation failed"):
            with connection.begin_nested():
                _insert(connection, "media_visual_asset_set_versions", {
                    "id": str(uuid4()), "org_id": other, "set_id": asset_set, "media_script_version_id": script_version,
                    "media_storyboard_version_id": None, "version_no": 2, "duration_seconds": 30, "region_profile_version_id": region,
                    "policy_snapshot_id": policy, "template_version": "media-visual-asset-set-v1", "status": "edited",
                    "items_json": json.dumps([{"sequence": 1}]), "item_count": 1, "rights_snapshot_ids_json": "[]",
                    "revision_reason": "x", "supersedes_version_id": None, "source_script_snapshot_hash": "5" * 64,
                    "source_storyboard_snapshot_hash": None, "snapshot_hash": "b" * 64, "created_by": actor, "created_at": STAMP,
                })
        with pytest.raises(sa.exc.IntegrityError, match="append-only"):
            with connection.begin_nested():
                connection.execute(sa.text("UPDATE media_visual_asset_items SET alt_text='changed' WHERE set_version_id=:id"), {"id": version})
        with pytest.raises(sa.exc.IntegrityError, match="item validation failed"):
            with connection.begin_nested():
                _insert(connection, "media_visual_asset_items", {
                    "org_id": org, "set_version_id": version, "sequence": 2, "role": "thumbnail", "asset_version_id": str(uuid4()),
                    "media_type": "video", "format": "mp4", "storage_object_ref": "private://asset/2", "asset_snapshot_hash": "a" * 64,
                    "timestamp_ms": None, "alt_text": "Wrong role", "rights_record_version_ids_json": json.dumps([str(uuid4())]),
                    "rights_snapshots_json": "[]", "created_at": STAMP,
                })
        with pytest.raises(sa.exc.IntegrityError, match="identity is immutable"):
            with connection.begin_nested():
                connection.execute(sa.text("UPDATE media_visual_asset_sets SET duration_seconds=60 WHERE id=:id"), {"id": asset_set})
    command.downgrade(config, "20260920_media_003a")
    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        for table in ("media_visual_asset_sets", "media_visual_asset_set_versions", "media_visual_asset_items", "media_visual_asset_commands"):
            assert not inspector.has_table(table)
        assert inspector.has_table("media_subtitles")
        assert inspector.has_table("media_storyboards")
    engine.dispose()
