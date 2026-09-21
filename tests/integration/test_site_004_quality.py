from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, filename: str):
    path = ROOT / "apps" / "knowledge-site" / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


site_render = _load("site_004_renderer", "site_render.py")
site_quality = _load("site_004_quality_service", "site_quality.py")

ORG = "11111111-1111-4111-8111-111111111111"
PAGE = "22222222-2222-4222-8222-222222222222"
VERSION = "33333333-3333-4333-8333-333333333333"
REGION = "44444444-4444-4444-8444-444444444444"
ACTOR = "55555555-5555-4555-8555-555555555555"
NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


def test_site_002_output_flows_into_site_004_without_raw_html_persistence() -> None:
    page = {
        "id": VERSION,
        "org_id": ORG,
        "site_page_id": PAGE,
        "page_key": "guides/quality",
        "version_no": 1,
        "canonical_content_version_id": "66666666-6666-4666-8666-666666666666",
        "variant_version_id": None,
        "region_profile_version_id": REGION,
        "locale": "en-US",
        "url_path": "/quality",
        "canonical_url": "/quality",
        "render_mode": "ssr",
        "status": "published",
        "title": "Quality guide",
        "summary": "A deterministic audit fixture",
        "author": {"id": "author", "name": "Author"},
        "reviewer": None,
        "updated_at": NOW.isoformat(),
        "visible_content": {"blocks": [{"type": "paragraph", "text": "Visible content for people and crawlers."}]},
        "methodology": {"steps": []},
        "evidence": [],
        "limitations": [],
        "faq": [],
        "snapshot_hash": "a" * 64,
        "created_by": ACTOR,
        "created_at": NOW.isoformat(),
    }
    rendered = site_render.SiteRenderService(clock=lambda: NOW).render_page(
        page_version=page,
        base_origin="https://example.com",
        actor_id=ACTOR,
        trace_id="trace-render",
        idempotency_key="render-site-004",
    )
    report = site_quality.SiteQualityService(clock=lambda: NOW).audit(
        page,
        rendered_html=rendered["html"],
        predecessor_artifacts=rendered,
        page_status_code=200,
        performance_metrics={
            "lcp_ms": 1200, "cls": 0.02, "inp_ms": 90,
            "ttfb_ms": 250, "total_bytes": len(rendered["html"].encode("utf-8")),
        },
        actor_id=ACTOR,
        trace_id="trace-quality",
        idempotency_key="audit-site-004",
    )
    assert report["status"] == "passed"
    assert report["source_html_hash"] == rendered["hashes"]["html"]
    serialized = json.dumps(report.as_contract()).lower()
    assert "<main" not in serialized and "visible content for people" not in serialized
