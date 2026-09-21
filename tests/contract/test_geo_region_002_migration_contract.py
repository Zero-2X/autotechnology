from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_geo_region_002_migration_is_chained_and_append_only() -> None:
    source = (ROOT / "packages/db/migrations/versions/20260920_geo_region_002.py").read_text(encoding="utf-8")
    assert 'revision = "20260920_geo_region_002"' in source
    assert 'down_revision = "20260920_geo_region_001"' in source
    assert "region_policy_decisions" in source
    for marker in (
        "region_profile_versions",
        "site_page_versions",
        "DECISION_REGION_FK",
        "DECISION_SITE_FK",
        "_sqlite_triggers",
        "_postgres_triggers",
        "no_replace",
        "no_update",
        "no_delete",
        "checks_json",
        "input_snapshot_hash",
        "decision_hash",
        "raw body",
        "def downgrade()",
    ):
        assert marker in source, marker


def test_geo_region_002_migration_has_no_raw_payload_column() -> None:
    source = (ROOT / "packages/db/migrations/versions/20260920_geo_region_002.py").read_text(encoding="utf-8")
    assert 'sa.Column("payload"' not in source
    assert 'sa.Column("answer"' not in source
    assert 'sa.Column("body"' not in source
