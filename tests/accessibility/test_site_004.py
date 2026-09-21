from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "apps" / "knowledge-site" / "scripts" / "site_quality.py"
SPEC = importlib.util.spec_from_file_location("site_004_accessibility", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
site_quality = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(site_quality)

ORG = "11111111-1111-4111-8111-111111111111"
PAGE = "44444444-4444-4444-8444-444444444444"
CANONICAL = "https://example.com/accessibility"
NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
METRICS = {"lcp_ms": 1000, "cls": 0.01, "inp_ms": 80, "ttfb_ms": 200, "total_bytes": 100_000}


def _page() -> dict:
    return {
        "id": PAGE, "org_id": ORG, "page_key": "guides/accessibility",
        "canonical_url": CANONICAL, "status": "published", "snapshot_hash": "a" * 64,
    }


def _audit(html: str, observations: dict, key: str):
    return site_quality.SiteQualityService(clock=lambda: NOW).audit(
        _page(), rendered_html=html, page_status_code=200,
        link_observations=observations, performance_metrics=METRICS,
        idempotency_key=key,
    )


def test_decorative_image_empty_alt_is_allowed() -> None:
    html = f"""<html><head><title>A11y</title><link rel="canonical" href="{CANONICAL}"></head>
<body><main><h1>Accessible page</h1><img src="/separator.svg" alt="" role="presentation"></main></body></html>"""
    report = _audit(html, {"https://example.com/separator.svg": {"status_code": 200}}, "a11y-decorative")
    assert report["status"] == "passed"
    assert "DECORATIVE_IMAGE_ALT_OK" in {item["code"] for item in report["checks"]}


def test_meaningful_images_and_each_media_item_require_accessibility_text() -> None:
    html = f"""<html><head><title>A11y</title><link rel="canonical" href="{CANONICAL}"></head>
<body><main><h1>Accessible page</h1><img src="/chart.png"><video src="/demo.mp4"></video>
<audio src="/narration.mp3"><track kind="captions" src="/captions.vtt"></audio></main></body></html>"""
    observations = {
        "https://example.com/chart.png": {"status_code": 200},
        "https://example.com/demo.mp4": {"status_code": 200},
        "https://example.com/narration.mp3": {"status_code": 200},
        "https://example.com/captions.vtt": {"status_code": 200},
    }
    report = _audit(html, observations, "a11y-missing")
    codes = [item["code"] for item in report["findings"]]
    assert report["status"] == "blocked"
    assert "IMAGE_ALT_MISSING" in codes
    assert codes.count("CAPTIONS_MISSING") == 2


def test_caption_track_requires_source_and_language() -> None:
    html = f"""<html><head><title>A11y</title><link rel="canonical" href="{CANONICAL}"></head>
<body><main><h1>Accessible page</h1><video src="/demo.mp4">
<track kind="captions" src="/captions.vtt" srclang="en"></video></main></body></html>"""
    report = _audit(
        html,
        {
            "https://example.com/demo.mp4": {"status_code": 200},
            "https://example.com/captions.vtt": {"status_code": 200},
        },
        "a11y-captioned",
    )
    assert report["status"] == "passed"
    assert "CAPTIONS_PRESENT" in {item["code"] for item in report["checks"]}
