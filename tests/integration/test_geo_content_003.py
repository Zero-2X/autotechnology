from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_geo_content_003_migration_adds_only_append_only_geo_runs_and_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sa = pytest.importorskip("sqlalchemy")
    command = pytest.importorskip("alembic.command")
    config_module = pytest.importorskip("alembic.config")
    database_url = f"sqlite:///{(tmp_path / 'geo_content_003.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = config_module.Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "20260920_geo_content_003")

    engine = sa.create_engine(database_url)
    with engine.begin() as connection:
        inspector = sa.inspect(connection)
        assert inspector.has_table("geo_runs")
        assert inspector.has_table("geo_query_fixtures")
        columns = {item["name"] for item in inspector.get_columns("geo_runs")}
        assert {
            "id", "org_id", "page_version_id", "query_fixture_id", "sample_count",
            "parser_version", "mention_count", "citation_count", "position_values",
            "correctness_values", "confidence", "data_quality", "fixture_hash", "status",
            "created_at", "payload",
        }.issubset(columns)
        foreign_keys = {
            (tuple(item["constrained_columns"]), item["referred_table"], tuple(item["referred_columns"]))
            for item in inspector.get_foreign_keys("geo_runs")
        }
        assert (("org_id", "query_fixture_id"), "geo_query_fixtures", ("org_id", "id")) in foreign_keys
        assert (("org_id", "page_version_id"), "site_page_versions", ("org_id", "id")) in foreign_keys
        connection.exec_driver_sql(
            "INSERT INTO site_pages "
            "(id, org_id, page_key, locale, url_path, current_version_id, created_by, created_at, updated_at, payload) "
            "VALUES ('page', 'o', 'guide', 'en-US', '/guide', NULL, 'actor', "
            "'2026-09-20T00:00:00Z', '2026-09-20T00:00:00Z', '{}')"
        )
        connection.exec_driver_sql(
            "INSERT INTO site_page_versions "
            "(id, org_id, site_page_id, version_no, canonical_content_version_id, variant_version_id, "
            "region_profile_version_id, locale, url_path, render_mode, status, snapshot_hash, published_at, "
            "created_by, created_at, payload) VALUES "
            "('p', 'o', 'page', 1, 'canonical', NULL, 'region', 'en-US', '/guide', 'ssr', 'ready', "
            "'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', NULL, 'actor', "
            "'2026-09-20T00:00:00Z', '{}')"
        )
        connection.exec_driver_sql(
            "INSERT INTO geo_query_fixtures "
            "(id, org_id, query, locale, region, expected_entities, expected_claim_ids, status, version, "
            "fixture_hash, created_by, created_at, updated_by, updated_at, payload) VALUES "
            "('q', 'o', 'query', 'en-US', 'US', '[]', '[]', 'active', 2, "
            "'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', NULL, "
            "'2026-09-20T00:00:00Z', NULL, NULL, '{}')"
        )
        with pytest.raises(Exception, match="tenant reference invalid"):
            connection.exec_driver_sql(
                "INSERT INTO geo_runs "
                "(id, org_id, page_version_id, query_fixture_id, locale, region, sample_count, parser_version, "
                "mention_count, citation_count, position_values, correctness_values, confidence, data_quality, "
                "fixture_hash, status, created_at) VALUES "
                "('cross', 'other', 'p', 'q', 'en-US', 'US', 2, 'parser.v1', 0, 0, '[]', "
                "'[\"unknown\"]', 0, 'estimated', "
                "'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', "
                "'failed', '2026-09-20T00:00:00Z')"
            )
        connection.exec_driver_sql(
            "INSERT INTO geo_runs "
            "(id, org_id, page_version_id, query_fixture_id, locale, region, sample_count, parser_version, "
            "mention_count, citation_count, position_values, correctness_values, confidence, data_quality, "
            "fixture_hash, status, created_at) VALUES "
            "('r', 'o', 'p', 'q', 'en-US', 'US', 2, 'parser.v1', 1, 1, '[1]', '[\"correct\"]', "
            "0.8, 'estimated', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', "
            "'succeeded', '2026-09-20T00:00:00Z')"
        )
        connection.exec_driver_sql(
            "INSERT INTO site_page_versions "
            "(id, org_id, site_page_id, version_no, canonical_content_version_id, variant_version_id, "
            "region_profile_version_id, locale, url_path, render_mode, status, snapshot_hash, published_at, "
            "created_by, created_at, payload) VALUES "
            "('p-draft', 'o', 'page', 2, 'canonical', NULL, 'region', 'en-US', '/guide', 'ssr', 'draft', "
            "'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', NULL, 'actor', "
            "'2026-09-20T00:00:00Z', '{}')"
        )
        with pytest.raises(Exception, match="page version tenant reference invalid"):
            connection.exec_driver_sql(
                "INSERT INTO geo_runs "
                "(id, org_id, page_version_id, query_fixture_id, locale, region, sample_count, parser_version, "
                "mention_count, citation_count, position_values, correctness_values, confidence, data_quality, "
                "fixture_hash, status, created_at) VALUES "
                "('not-ready-page', 'o', 'p-draft', 'q', 'en-US', 'US', 2, 'parser.v1', 0, 0, '[]', "
                "'[\"unknown\"]', 0, 'estimated', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', "
                "'failed', '2026-09-20T00:00:00Z')"
            )
        with pytest.raises(Exception, match="JSON projection invalid"):
            connection.exec_driver_sql(
                "INSERT INTO geo_runs "
                "(id, org_id, page_version_id, query_fixture_id, locale, region, sample_count, parser_version, "
                "mention_count, citation_count, position_values, correctness_values, confidence, data_quality, "
                "fixture_hash, status, created_at) VALUES "
                "('descending', 'o', 'p', 'q', 'en-US', 'US', 2, 'parser.v1', 0, 0, '[2,1]', "
                "'[\"unknown\"]', 0, 'estimated', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', "
                "'failed', '2026-09-20T00:00:00Z')"
            )
        with pytest.raises(Exception):
            connection.exec_driver_sql(
                "INSERT INTO geo_runs "
                "(id, org_id, page_version_id, query_fixture_id, locale, region, sample_count, parser_version, "
                "mention_count, citation_count, position_values, correctness_values, confidence, data_quality, "
                "fixture_hash, status, created_at) VALUES "
                "('validated-quality', 'o', 'p', 'q', 'en-US', 'US', 2, 'parser.v1', 0, 0, '[]', "
                "'[\"unknown\"]', 0, 'validated', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', "
                "'failed', '2026-09-20T00:00:00Z')"
            )
        with pytest.raises(Exception):
            connection.exec_driver_sql(
                "INSERT INTO geo_runs "
                "(id, org_id, page_version_id, query_fixture_id, locale, region, sample_count, parser_version, "
                "mention_count, citation_count, position_values, correctness_values, confidence, data_quality, "
                "fixture_hash, status, created_at, payload) VALUES "
                "('raw-payload', 'o', 'p', 'q', 'en-US', 'US', 2, 'parser.v1', 0, 0, '[]', "
                "'[\"unknown\"]', 0, 'estimated', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', "
                "'failed', '2026-09-20T00:00:00Z', '{\"answer\":\"secret\"}')"
            )
        with pytest.raises(Exception, match="append-only"):
            connection.exec_driver_sql(
                "INSERT OR REPLACE INTO geo_runs "
                "(id, org_id, page_version_id, query_fixture_id, locale, region, sample_count, parser_version, "
                "mention_count, citation_count, position_values, correctness_values, confidence, data_quality, "
                "fixture_hash, status, created_at) SELECT id, org_id, page_version_id, query_fixture_id, locale, "
                "region, sample_count, parser_version, mention_count, citation_count, position_values, "
                "correctness_values, 0, data_quality, fixture_hash, 'failed', created_at FROM geo_runs WHERE id='r'"
            )
        with pytest.raises(Exception, match="query fixture tenant reference invalid"):
            connection.exec_driver_sql(
                "INSERT INTO geo_runs "
                "(id, org_id, page_version_id, query_fixture_id, locale, region, sample_count, parser_version, "
                "mention_count, citation_count, position_values, correctness_values, confidence, data_quality, "
                "fixture_hash, status, created_at) VALUES "
                "('bad-hash', 'o', 'p', 'q', 'en-US', 'US', 2, 'parser.v1', 0, 0, '[]', "
                "'[\"unknown\"]', 0, 'estimated', "
                "'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff', "
                "'failed', '2026-09-20T00:00:00Z')"
            )
        with pytest.raises(Exception, match="JSON projection invalid"):
            connection.exec_driver_sql(
                "INSERT INTO geo_runs "
                "(id, org_id, page_version_id, query_fixture_id, locale, region, sample_count, parser_version, "
                "mention_count, citation_count, position_values, correctness_values, confidence, data_quality, "
                "fixture_hash, status, created_at) VALUES "
                "('bad-json', 'o', 'p', 'q', 'en-US', 'US', 2, 'parser.v1', 0, 0, '[0]', "
                "'[\"unknown\"]', 0, 'estimated', "
                "'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', "
                "'failed', '2026-09-20T00:00:00Z')"
            )
        with pytest.raises(Exception, match="append-only"):
            connection.exec_driver_sql("UPDATE geo_runs SET confidence=0 WHERE id='r'")
        with pytest.raises(Exception, match="append-only"):
            connection.exec_driver_sql("DELETE FROM geo_runs WHERE id='r'")

    command.downgrade(config, "20260919_geo_content_002")
    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        assert not inspector.has_table("geo_runs")
        assert inspector.has_table("geo_query_fixtures")
    engine.dispose()
