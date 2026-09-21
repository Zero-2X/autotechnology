from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "apps" / "knowledge-site" / "scripts" / "site_quality.py"
SPEC = importlib.util.spec_from_file_location("knowledge_site_quality", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
site_quality = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(site_quality)

ORG = "11111111-1111-4111-8111-111111111111"
OTHER_ORG = "22222222-2222-4222-8222-222222222222"
ACTOR = "33333333-3333-4333-8333-333333333333"
PAGE = "44444444-4444-4444-8444-444444444444"
NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
CANONICAL = "https://example.com/guide"


def _page(**overrides: object) -> dict:
    value = {
        "id": PAGE,
        "org_id": ORG,
        "page_key": "guides/site-quality",
        "canonical_url": CANONICAL,
        "url_path": "/guide",
        "status": "published",
        "snapshot_hash": "a" * 64,
        "render_mode": "ssr",
    }
    value.update(overrides)
    return value


def _html(*, alt: str = "Architecture diagram", captions: bool = True, about: str = "/about") -> str:
    track = '<track kind="captions" src="/captions.vtt" srclang="en">' if captions else ""
    return f"""<!doctype html><html><head>
<title>Guide</title><link rel="canonical" href="{CANONICAL}"></head><body>
<main id="content"><h1>Site quality guide</h1><p>Useful visible content for crawlers.</p>
<a href="{about}">About</a><a href="#content">Content</a>
<img src="/diagram.png" alt="{alt}">
<video src="/demo.mp4">{track}</video></main></body></html>"""


def _observations(*, about_status: int = 200) -> dict:
    return {
        "https://example.com/about": {"status_code": about_status},
        "https://example.com/diagram.png": {"status_code": 200},
        "https://example.com/demo.mp4": {"status_code": 200},
        "https://example.com/captions.vtt": {"status_code": 200},
    }


def _metrics(**overrides: object) -> dict:
    value = {"lcp_ms": 1800, "cls": 0.05, "inp_ms": 120, "ttfb_ms": 400, "total_bytes": 500_000}
    value.update(overrides)
    return value


def _service(**kwargs: object):
    return site_quality.SiteQualityService(clock=lambda: NOW, **kwargs)


def test_quality_report_passes_and_validates_closed_contract() -> None:
    report = _service().audit(
        _page(), rendered_html=_html(), page_status_code=200,
        link_observations=_observations(), performance_metrics=_metrics(),
        actor_id=ACTOR, trace_id="trace-site-004", idempotency_key="quality-pass",
    )
    value = report.as_contract()
    assert value["status"] == "passed"
    assert value["summary"]["failed"] == 0
    assert value["summary"]["review"] == 0
    assert "rendered_html" not in json.dumps(value).lower()
    schema = json.loads((ROOT / "packages/contracts/jsonschema/site-quality-report.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    assert _service().audit(
        _page(), rendered_html=_html(), page_status_code=200,
        link_observations=dict(reversed(list(_observations().items()))),
        performance_metrics=_metrics(), actor_id=OTHER_ORG, trace_id="other",
        idempotency_key="quality-order",
    )["report_hash"] == value["report_hash"]


def test_broken_link_performance_alt_captions_and_dynamic_mismatch_block() -> None:
    dynamic = f'<html><head><link rel="canonical" href="{CANONICAL}"></head><body><main><h1>Changed</h1>Only shell</main></body></html>'
    report = _service().audit(
        _page(), rendered_html=_html(alt="", captions=False), dynamic_html=dynamic,
        page_status_code=200, link_observations=_observations(about_status=404),
        performance_metrics=_metrics(lcp_ms=3000), idempotency_key="quality-blocked",
    )
    assert report["status"] == "blocked"
    codes = {item["code"] for item in report["findings"]}
    assert {"BROKEN_LINK", "PERFORMANCE_BUDGET_EXCEEDED", "IMAGE_ALT_MISSING", "CAPTIONS_MISSING", "DYNAMIC_RENDER_MISMATCH"} <= codes


def test_missing_observations_metrics_and_required_dynamic_snapshot_review() -> None:
    report = _service().audit(
        _page(dynamic_required=True), rendered_html=_html(), page_status_code=200,
        link_observations=None, performance_metrics=None, idempotency_key="quality-review",
    )
    assert report["status"] == "manual_review"
    codes = {item["code"] for item in report["findings"]}
    assert "LINK_STATUS_UNKNOWN" in codes
    assert "PERFORMANCE_METRIC_MISSING" in codes
    assert "DYNAMIC_RENDER_UNKNOWN" in codes


def test_redirect_chain_fragment_and_decorative_alt_rules() -> None:
    html = f"""<html><head><title>Guide</title><link rel="canonical" href="{CANONICAL}"></head>
<body><main id="main"><h1>Guide</h1><a href="/old">Old</a><a href="#main">Main</a>
<img src="/decorative.svg" alt="" aria-hidden="true"></main></body></html>"""
    observations = {
        "https://example.com/old": {
            "status_code": 301, "final_url": "https://example.com/new",
            "redirect_chain": ["https://example.com/old", "https://example.com/new"],
        },
        "https://example.com/decorative.svg": {"status_code": 200},
    }
    report = _service().audit(
        _page(), rendered_html=html, page_status_code=200,
        link_observations=observations, performance_metrics=_metrics(),
        idempotency_key="quality-redirect",
    )
    assert report["status"] == "passed"
    assert {"REDIRECT_VALID", "DECORATIVE_IMAGE_ALT_OK", "FRAGMENTS_VALID"} <= {item["code"] for item in report["checks"]}

    observations["https://example.com/old"]["redirect_chain"] = [
        "https://example.com/old", "https://example.com/new", "https://example.com/old"
    ]
    looped = _service().audit(
        _page(), rendered_html=html, page_status_code=200,
        link_observations=observations, performance_metrics=_metrics(),
        idempotency_key="quality-loop",
    )
    assert looped["status"] == "blocked"
    assert "REDIRECT_LOOP" in {item["code"] for item in looped["findings"]}


def test_tenant_idempotency_and_probe_error_are_fail_closed_and_redacted() -> None:
    with pytest.raises(site_quality.SiteQualityError) as foreign:
        _service().audit(
            _page(org_id=OTHER_ORG), org_id=ORG, rendered_html=_html(),
            page_status_code=200, link_observations=_observations(),
            performance_metrics=_metrics(), idempotency_key="quality-foreign",
        )
    assert foreign.value.code == "TENANT_SCOPE_VIOLATION"

    service = _service()
    kwargs = {
        "page_version": _page(), "rendered_html": _html(), "page_status_code": 200,
        "link_observations": _observations(), "performance_metrics": _metrics(),
        "idempotency_key": "quality-same",
    }
    first = service.audit(**kwargs)
    assert service.audit(**kwargs).as_contract() == first.as_contract()
    with pytest.raises(site_quality.SiteQualityError) as reused:
        service.audit(**{**kwargs, "performance_metrics": _metrics(cls=0.08)})
    assert reused.value.code == "IDEMPOTENCY_KEY_REUSED"

    class FailingProbe:
        def probe(self, **_: object) -> object:
            raise RuntimeError("authorization=Bearer-secret token=do-not-store")

    probe_service = _service(link_probe_port=FailingProbe())
    failed = probe_service.audit(
        _page(), rendered_html=_html(), page_status_code=200,
        performance_metrics=_metrics(), idempotency_key="quality-probe-error",
    )
    serialized = json.dumps(failed.as_contract()) + json.dumps(probe_service.audit_log)
    assert failed["status"] == "manual_review"
    assert "Bearer-secret" not in serialized and "do-not-store" not in serialized
    assert "LINK_PROBE_ERROR" in {item["code"] for item in failed["findings"]}


def test_page_and_predecessor_hashes_are_bound_to_the_command() -> None:
    service = _service()
    kwargs = {
        "page_version": _page(), "rendered_html": _html(), "page_status_code": 200,
        "link_observations": _observations(), "performance_metrics": _metrics(),
        "idempotency_key": "quality-page-binding",
    }
    service.audit(**kwargs)
    with pytest.raises(site_quality.SiteQualityError) as reused:
        service.audit(**{**kwargs, "page_version": _page(snapshot_hash="b" * 64)})
    assert reused.value.code == "IDEMPOTENCY_KEY_REUSED"

    with pytest.raises(site_quality.SiteQualityError) as mismatch:
        _service().audit(
            _page(), rendered_html=_html(), page_status_code=200,
            link_observations=_observations(), performance_metrics=_metrics(),
            predecessor_artifacts={"org_id": ORG, "hashes": {"html": "f" * 64}},
            idempotency_key="quality-predecessor-mismatch",
        )
    assert mismatch.value.code == "ARTIFACT_HASH_MISMATCH"
