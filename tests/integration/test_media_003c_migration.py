import importlib.util
import json
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
import sqlalchemy as sa


ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("output_seed", ROOT / "tests/integration/test_media_002_migration.py")
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)
insert = _fixture._insert
STAMP = _fixture.STAMP


def test_output_migration_preserves_predecessors_and_rejects_invalid_profiles(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'output.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(config, "20260920_media_003c")
    engine = sa.create_engine(url)
    org, actor, visual_root, visual, root, version = (str(uuid4()) for _ in range(6))
    with engine.begin() as conn:
        script, _, region, policy, _ = _fixture._seed_script(conn, org=org, actor=actor)
        insert(conn, "media_visual_asset_sets", dict(id=visual_root, org_id=org, media_script_version_id=script,
               media_storyboard_version_id=None, duration_seconds=30, current_version_id=None, status="draft",
               created_by=actor, created_at=STAMP, updated_at=STAMP))
        insert(conn, "media_visual_asset_set_versions", dict(id=visual, org_id=org, set_id=visual_root,
               media_script_version_id=script, media_storyboard_version_id=None, duration_seconds=30,
               version_no=1, region_profile_version_id=region, policy_snapshot_id=policy,
               template_version="media-visual-asset-set-v1", status="draft", items_json='[{"role":"cover"}]',
               item_count=1, rights_snapshot_ids_json="[]", revision_reason=None, supersedes_version_id=None,
               source_script_snapshot_hash="5" * 64, source_storyboard_snapshot_hash=None, snapshot_hash="6" * 64,
               created_by=actor, created_at=STAMP))
        lineage = dict(org_id=org, media_visual_asset_set_version_id=visual, media_script_version_id=script,
                       media_storyboard_version_id=None, duration_seconds=30, region_profile_version_id=region,
                       policy_snapshot_id=policy)
        with pytest.raises(sa.exc.IntegrityError, match="initial pointer"):
            with conn.begin_nested():
                insert(conn, "media_output_specs", dict(id=root, **lineage, current_version_id=version, status="draft",
                       created_by=actor, created_at=STAMP, updated_at=STAMP))
        insert(conn, "media_output_specs", dict(id=root, **lineage, current_version_id=None, status="draft",
               created_by=actor, created_at=STAMP, updated_at=STAMP))
        profile = dict(sequence=1, profile_key="square", aspect_ratio="1:1", width=1080, height=1080,
                       frame_rate=30, container_format="mp4", video_codec="h264", pixel_format="yuv420p",
                       audio_codec="aac", audio_sample_rate_hz=48000, audio_channels=2, subtitle_track_ids=[])
        version_row = dict(id=version, **lineage, spec_id=root, version_no=1,
               template_version="media-output-spec-v1", status="draft", profiles_json=json.dumps([profile]),
               profile_count=1, require_all_ratios=False, revision_reason=None, supersedes_version_id=None,
               source_visual_snapshot_hash="6" * 64, source_script_snapshot_hash="5" * 64,
               source_storyboard_snapshot_hash=None, snapshot_hash="7" * 64, created_by=actor, created_at=STAMP)
        for invalid in ({}, {**profile, "width": 1920}, {**profile, "video_codec": "unknown"},
                        {**profile, "audio_channels": 0}, {**profile, "sequence": 2}, {**profile, "extra": "ignored?"},
                        {**profile, "subtitle_track_ids": ["invalid"]}, {**profile, "bitrate_kbps": -1}):
            with pytest.raises(sa.exc.IntegrityError):
                with conn.begin_nested():
                    insert(conn, "media_output_spec_versions", {**version_row, "profiles_json": json.dumps([invalid])})
        with pytest.raises(sa.exc.IntegrityError):
            with conn.begin_nested():
                insert(conn, "media_output_spec_versions", {**version_row, "profile_count": 2,
                       "profiles_json": json.dumps([profile, {**profile, "sequence": 2}])})
        insert(conn, "media_output_spec_versions", version_row)
        row = {k: v for k, v in profile.items() if k != "subtitle_track_ids"}
        row.update(org_id=org, spec_version_id=version, subtitle_track_ids_json="[]", created_at=STAMP)
        with pytest.raises(sa.exc.IntegrityError, match="pointer progression"):
            with conn.begin_nested():
                conn.execute(sa.text("UPDATE media_output_specs SET current_version_id=:version WHERE id=:root"),
                             {"version": version, "root": root})
        for overrides in ({"width": 1920}, {"width": 1081, "height": 1081}, {"width": 720, "height": 720},
                          {"audio_channels": 0}, {"org_id": str(uuid4())}):
            with pytest.raises(sa.exc.IntegrityError):
                with conn.begin_nested():
                    insert(conn, "media_output_spec_items", {**row, **overrides})
        insert(conn, "media_output_spec_items", row)
        conn.execute(sa.text("UPDATE media_output_specs SET current_version_id=:version WHERE id=:root"),
                     {"version": version, "root": root})
        for pointer in (None, str(uuid4())):
            with pytest.raises(sa.exc.IntegrityError):
                with conn.begin_nested():
                    conn.execute(sa.text("UPDATE media_output_specs SET current_version_id=:version WHERE id=:root"),
                                 {"version": pointer, "root": root})
        with pytest.raises(sa.exc.IntegrityError, match="append-only"):
            with conn.begin_nested():
                conn.execute(sa.text("DELETE FROM media_output_spec_items"))
    command.downgrade(config, "20260920_media_003b")
    assert not sa.inspect(engine).has_table("media_output_specs")
    assert sa.inspect(engine).has_table("media_visual_asset_sets")
    engine.dispose()
