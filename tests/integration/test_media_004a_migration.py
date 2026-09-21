from __future__ import annotations

import json
import importlib.util
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
import sqlalchemy as sa


ROOT = Path(__file__).resolve().parents[2]
STAMP = "2026-09-20T12:00:00Z"
_SPEC = importlib.util.spec_from_file_location("media_003c_migration_fixture", ROOT / "tests/integration/test_media_003c_migration.py")
assert _SPEC and _SPEC.loader
_FIXTURE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURE)
_insert = _FIXTURE.insert
_seed_script = _FIXTURE._fixture._seed_script


def _source(connection, *, org: str, actor: str) -> tuple[str, str, str, str, str]:
    script, _variant, region, policy, _claim = _seed_script(connection, org=org, actor=actor)
    visual_root, visual, output_root, output, item = (str(uuid4()) for _ in range(5))
    _insert(connection, "media_visual_asset_sets", dict(id=visual_root, org_id=org, media_script_version_id=script,
           media_storyboard_version_id=None, duration_seconds=30, current_version_id=None, status="draft",
           created_by=actor, created_at=STAMP, updated_at=STAMP))
    _insert(connection, "media_visual_asset_set_versions", dict(id=visual, org_id=org, set_id=visual_root,
           media_script_version_id=script, media_storyboard_version_id=None, duration_seconds=30,
           version_no=1, region_profile_version_id=region, policy_snapshot_id=policy,
           template_version="media-visual-asset-set-v1", status="draft", items_json=json.dumps([{"role": "cover"}]),
           item_count=1, rights_snapshot_ids_json="[]", revision_reason=None, supersedes_version_id=None,
           source_script_snapshot_hash="5" * 64, source_storyboard_snapshot_hash=None, snapshot_hash="6" * 64,
           created_by=actor, created_at=STAMP))
    profile = dict(sequence=1, profile_key="square", aspect_ratio="1:1", width=1080, height=1080, frame_rate=30,
                   container_format="mp4", video_codec="h264", pixel_format="yuv420p", audio_codec="aac",
                   audio_sample_rate_hz=48000, audio_channels=2, subtitle_track_ids=[])
    _insert(connection, "media_output_specs", dict(id=output_root, org_id=org,
           media_visual_asset_set_version_id=visual, media_script_version_id=script, media_storyboard_version_id=None,
           duration_seconds=30, region_profile_version_id=region, policy_snapshot_id=policy, current_version_id=None,
           status="draft", created_by=actor, created_at=STAMP, updated_at=STAMP))
    _insert(connection, "media_output_spec_versions", dict(id=output, org_id=org, spec_id=output_root,
           media_visual_asset_set_version_id=visual, media_script_version_id=script, media_storyboard_version_id=None,
           version_no=1, duration_seconds=30, region_profile_version_id=region, policy_snapshot_id=policy,
           template_version="media-output-spec-v1", status="draft", profiles_json=json.dumps([profile]), profile_count=1,
           require_all_ratios=False, revision_reason=None, supersedes_version_id=None,
           source_visual_snapshot_hash="6" * 64, source_script_snapshot_hash="5" * 64,
           source_storyboard_snapshot_hash=None, snapshot_hash="7" * 64, created_by=actor, created_at=STAMP))
    _insert(connection, "media_output_spec_items", dict(org_id=org, spec_version_id=output, **{k: v for k, v in profile.items() if k != "subtitle_track_ids"},
           subtitle_track_ids_json="[]", created_at=STAMP))
    connection.execute(sa.text("UPDATE media_output_specs SET current_version_id=:version WHERE id=:root"), {"version": output, "root": output_root})
    return script, visual, output, region, policy


def _job_row(*, org: str, actor: str, script: str, visual: str, output: str, region: str, policy: str, job: str) -> dict:
    profile = {"sequence": 1, "profile_key": "square", "aspect_ratio": "1:1", "width": 1080, "height": 1080,
               "frame_rate": 30, "container_format": "mp4", "video_codec": "h264", "pixel_format": "yuv420p",
               "audio_codec": "aac", "audio_sample_rate_hz": 48000, "audio_channels": 2, "subtitle_track_ids": []}
    hashes = {"script": "5" * 64, "storyboard": None, "subtitle": None, "visual_asset_set": "6" * 64,
              "output_spec": "7" * 64, "asset_version": None}
    return dict(id=job, org_id=org, asset_version_id=str(uuid4()), asset_version_no=None, media_script_version_id=script,
                media_storyboard_version_id=None, media_subtitle_version_id=None, media_visual_asset_set_version_id=visual,
                media_output_spec_version_id=output, output_profile_key="square", output_profile_json=json.dumps(profile),
                duration_seconds=30, region_profile_version_id=region, policy_snapshot_id=policy, status="planned",
                input_hash="a" * 64, attempt_count=0, input_snapshot_hashes_json=json.dumps(hashes), artifact_count=0,
                trace_id="trace", failure_code=None, created_by=actor, created_at=STAMP, updated_at=STAMP)


def test_media_004a_migration_locks_inputs_artifacts_and_rolls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = f"sqlite:///{(tmp_path / 'media004a.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "20260920_media_004a")
    engine = sa.create_engine(database_url)
    org, other, actor = str(uuid4()), str(uuid4()), str(uuid4())
    with engine.begin() as connection:
        script, visual, output, region, policy = _source(connection, org=org, actor=actor)
        job = str(uuid4())
        _insert(connection, "media_render_jobs", _job_row(org=org, actor=actor, script=script, visual=visual, output=output,
               region=region, policy=policy, job=job))
        input_rows = [(script, "script", "5" * 64), (visual, "visual_asset_set", "6" * 64), (output, "output_spec", "7" * 64)]
        for sequence, (identity, kind, digest) in enumerate(input_rows, 1):
            _insert(connection, "media_render_job_inputs", dict(org_id=org, render_job_id=job, sequence=sequence,
                   input_kind=kind, input_version_id=identity, snapshot_hash=digest, expected_version_no=1, created_at=STAMP))
        artifact = dict(org_id=org, render_job_id=job, sequence=1, stage="full", shot_sequence=None,
                        output_profile_key="square", storage_object_ref="private://render/job/artifact", content_hash="b" * 64,
                        size_bytes=12, content_type="video/mp4", input_hash="a" * 64, created_at=STAMP)
        _insert(connection, "media_render_artifacts", artifact)
        _insert(connection, "media_render_commands", dict(org_id=org, namespace="create", idempotency_key="one",
               request_hash="c" * 64, render_job_id=job, response_json=json.dumps({"render_job": {"id": job}}),
               actor_id=actor, trace_id="trace", created_at=STAMP))
        with pytest.raises(sa.exc.IntegrityError):
            with connection.begin_nested():
                _insert(connection, "media_render_jobs", {**_job_row(org=other, actor=actor, script=script, visual=visual,
                       output=output, region=region, policy=policy, job=str(uuid4()))})
        with pytest.raises(sa.exc.IntegrityError, match="private_ref|artifact validation"):
            with connection.begin_nested():
                _insert(connection, "media_render_artifacts", {**artifact, "sequence": 2, "stage": "preview", "storage_object_ref": "https://public.invalid/file"})
        with pytest.raises(sa.exc.IntegrityError, match="append-only"):
            with connection.begin_nested():
                connection.execute(sa.text("UPDATE media_render_job_inputs SET snapshot_hash=:hash WHERE render_job_id=:job"), {"hash": "d" * 64, "job": job})
        with pytest.raises(sa.exc.IntegrityError, match="append-only"):
            with connection.begin_nested():
                connection.execute(sa.text("DELETE FROM media_render_artifacts WHERE render_job_id=:job"), {"job": job})
    command.downgrade(config, "20260920_media_003c")
    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        for table in ("media_render_jobs", "media_render_job_inputs", "media_render_artifacts", "media_render_commands"):
            assert not inspector.has_table(table)
        assert inspector.has_table("media_output_specs")
    engine.dispose()
