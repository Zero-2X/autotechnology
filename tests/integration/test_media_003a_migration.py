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

_SPEC = importlib.util.spec_from_file_location("media_002_migration_fixture", ROOT / "tests/integration/test_media_002_migration.py")
assert _SPEC and _SPEC.loader
_FIXTURE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURE)
_insert = _FIXTURE._insert
_seed_script = _FIXTURE._seed_script


def test_media_003a_migration_guards_tracks_cues_and_downgrade(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = f"sqlite:///{(tmp_path / 'media003a.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "20260920_media_003a")
    engine = sa.create_engine(database_url)
    org, other, actor = str(uuid4()), str(uuid4()), str(uuid4())
    with engine.begin() as connection:
        script_version, _variant, region, policy, _claim = _seed_script(connection, org=org, actor=actor)
        subtitle, version = str(uuid4()), str(uuid4())
        _insert(connection, "media_subtitles", {
            "id": subtitle, "org_id": org, "media_script_version_id": script_version,
            "media_storyboard_version_id": None, "duration_seconds": 30, "current_version_id": None,
            "status": "draft", "created_by": actor, "created_at": STAMP, "updated_at": STAMP,
        })
        tracks = [{"locale": "en-US", "kind": "caption", "cues": [{"sequence": 1, "text": "Hook"}]}]
        accessibility = {"captions_complete": True, "speaker_labels_complete": False, "sound_descriptions_complete": False, "reading_order": "chronological", "max_lines": 2, "max_chars_per_line": 42}
        _insert(connection, "media_subtitle_versions", {
            "id": version, "org_id": org, "subtitle_id": subtitle, "media_script_version_id": script_version,
            "media_storyboard_version_id": None, "version_no": 1, "duration_seconds": 30,
            "policy_snapshot_id": policy, "template_version": "media-subtitle-v1", "status": "draft",
            "tracks_json": json.dumps(tracks), "track_count": 1, "accessibility_json": json.dumps(accessibility),
            "revision_reason": None, "supersedes_version_id": None, "source_script_snapshot_hash": "5" * 64,
            "source_storyboard_snapshot_hash": None, "snapshot_hash": "6" * 64, "created_by": actor, "created_at": STAMP,
        })
        _insert(connection, "media_subtitle_tracks", {
            "org_id": org, "subtitle_version_id": version, "locale": "en-US", "language_name": "English",
            "kind": "caption", "direction": "ltr", "is_default": True, "text_version": 1,
            "source_text_hash": "7" * 64, "cues_json": json.dumps([{"sequence": 1, "start_ms": 0, "end_ms": 1000, "text": "Hook"}]),
            "cue_count": 1, "accessibility_json": json.dumps(accessibility), "created_at": STAMP,
        })
        _insert(connection, "media_subtitle_cues", {
            "org_id": org, "subtitle_version_id": version, "locale": "en-US", "sequence": 1,
            "source_segment_sequence": 1, "start_ms": 0, "end_ms": 1000, "text": "Hook",
            "speaker_label": None, "sound_description": None, "is_forced": False, "line": 90,
            "position": 50, "align": "center", "created_at": STAMP,
        })
        _insert(connection, "media_subtitle_commands", {
            "org_id": org, "namespace": "create", "idempotency_key": "one", "request_hash": "a" * 64,
            "subtitle_id": subtitle, "result_version_id": version, "response_json": "{}", "actor_id": actor,
            "trace_id": "trace", "created_at": STAMP,
        })
        with pytest.raises(sa.exc.IntegrityError, match="version validation failed"):
            with connection.begin_nested():
                _insert(connection, "media_subtitle_versions", {
                    "id": str(uuid4()), "org_id": other, "subtitle_id": subtitle, "media_script_version_id": script_version,
                    "media_storyboard_version_id": None, "version_no": 2, "duration_seconds": 30,
                    "policy_snapshot_id": policy, "template_version": "media-subtitle-v1", "status": "edited",
                    "tracks_json": json.dumps(tracks), "track_count": 1, "accessibility_json": json.dumps(accessibility),
                    "revision_reason": "x", "supersedes_version_id": None, "source_script_snapshot_hash": "5" * 64,
                    "source_storyboard_snapshot_hash": None, "snapshot_hash": "b" * 64, "created_by": actor, "created_at": STAMP,
                })
        with pytest.raises(sa.exc.IntegrityError, match="append-only"):
            with connection.begin_nested():
                connection.execute(sa.text("UPDATE media_subtitle_cues SET text='changed' WHERE subtitle_version_id=:id"), {"id": version})
        with pytest.raises(sa.exc.IntegrityError, match="append-only"):
            with connection.begin_nested():
                connection.execute(sa.text("DELETE FROM media_subtitle_tracks WHERE subtitle_version_id=:id"), {"id": version})
        with pytest.raises(sa.exc.IntegrityError, match="cue validation failed"):
            with connection.begin_nested():
                _insert(connection, "media_subtitle_cues", {
                    "org_id": org, "subtitle_version_id": version, "locale": "en-US", "sequence": 2,
                    "source_segment_sequence": 1, "start_ms": 3900, "end_ms": 4500, "text": "Crosses segment",
                    "speaker_label": None, "sound_description": None, "is_forced": False, "line": 90,
                    "position": 50, "align": "center", "created_at": STAMP,
                })
        with pytest.raises(sa.exc.IntegrityError, match="identity is immutable"):
            with connection.begin_nested():
                connection.execute(sa.text("UPDATE media_subtitles SET duration_seconds=60 WHERE id=:id"), {"id": subtitle})
    command.downgrade(config, "20260920_media_002")
    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        for table in ("media_subtitles", "media_subtitle_versions", "media_subtitle_tracks", "media_subtitle_cues", "media_subtitle_commands"):
            assert not inspector.has_table(table)
        assert inspector.has_table("media_storyboards")
        assert inspector.has_table("media_script_versions")
    engine.dispose()
