from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
import yaml


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "apps" / "knowledge-site" / "scripts" / "site_quality.py"
SPEC = importlib.util.spec_from_file_location("site_004_contract_service", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
site_quality = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(site_quality)

ORG = "11111111-1111-4111-8111-111111111111"
PAGE = "44444444-4444-4444-8444-444444444444"
NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
CANONICAL = "https://example.com/quality"


def test_site_004_schema_and_registry_references_are_closed() -> None:
    path = ROOT / "packages/contracts/jsonschema/site-quality-report.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    assert schema["x-source"] == "SITE-004"
    assert schema["x-append-only"] is True
    registry = yaml.safe_load((ROOT / "docs/task-registry.yaml").read_text(encoding="utf-8"))
    task = next(item for item in registry["tasks"] if item["id"] == "SITE-004")
    assert task["status"] == "done"
    assert "packages/contracts/jsonschema/site-quality-report.schema.json" in task["contract_refs"]
    assert task["migration_refs"] == ["packages/db/migrations/versions/20260920_site_004.py"]


def test_site_004_service_output_validates_and_contains_no_raw_html() -> None:
    html = f"""<html><head><title>Quality</title><link rel="canonical" href="{CANONICAL}"></head>
<body><main><h1>Quality report</h1><p>Visible and crawlable content.</p></main></body></html>"""
    page = {
        "id": PAGE, "org_id": ORG, "page_key": "quality", "canonical_url": CANONICAL,
        "status": "published", "snapshot_hash": "a" * 64,
    }
    report = site_quality.SiteQualityService(clock=lambda: NOW).audit(
        page, rendered_html=html, page_status_code=200,
        performance_metrics={"lcp_ms": 1000, "cls": 0.01, "inp_ms": 100, "ttfb_ms": 300, "total_bytes": 100000},
        idempotency_key="site-004-contract",
    ).as_contract()
    schema = json.loads((ROOT / "packages/contracts/jsonschema/site-quality-report.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(report)
    assert report["status"] == "passed"
    serialized = json.dumps(report).lower()
    assert "<html" not in serialized and "<main" not in serialized


def test_site_004_migration_is_chained_append_only_and_nondestructive() -> None:
    source = (ROOT / "packages/db/migrations/versions/20260920_site_004.py").read_text(encoding="utf-8")
    assert 'revision = "20260920_site_004"' in source
    assert 'down_revision = "20260920_geo_region_002"' in source
    for marker in (
        "site_quality_reports", "site_page_versions", "no_replace", "no_update", "no_delete",
        "input_snapshot_hash", "source_html_hash", "report_hash", "raw content or credentials",
        "def upgrade()", "def downgrade()",
    ):
        assert marker in source
    assert 'sa.Column("html"' not in source
    assert 'sa.Column("body"' not in source
    assert 'sa.Column("payload"' not in source
