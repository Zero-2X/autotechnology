from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
from xml.etree import ElementTree

import pytest
from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "apps" / "knowledge-site" / "scripts" / "site_render.py"
SPEC = importlib.util.spec_from_file_location("knowledge_site_site_render", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
site_render = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(site_render)

ORG = "11111111-1111-4111-8111-111111111111"
OTHER_ORG = "22222222-2222-4222-8222-222222222222"
ACTOR = "33333333-3333-4333-8333-333333333333"
PAGE = "44444444-4444-4444-8444-444444444444"
REGION = "55555555-5555-4555-8555-555555555555"
STAMP = "2026-09-19T12:00:00Z"


def _page(*, locale: str = "en-US", path: str = "/guides/first-party", version_no: int = 1,
          status: str = "published", page_id: str = PAGE, org_id: str = ORG, title: str = "Guide & <One>") -> dict:
    return {
        "id": f"{version_no:08d}-0000-4000-8000-000000000001" if version_no != 1 else "66666666-6666-4666-8666-666666666666",
        "org_id": org_id,
        "site_page_id": page_id,
        "page_key": "guides/first-party",
        "version_no": version_no,
        "canonical_content_version_id": "77777777-7777-4777-8777-777777777777",
        "variant_version_id": None,
        "region_profile_version_id": REGION,
        "locale": locale,
        "url_path": path,
        "canonical_url": path,
        "render_mode": "ssr",
        "status": status,
        "title": title,
        "summary": "Summary & details",
        "author": {"id": "author-1", "name": "A <Author>", "url": None},
        "reviewer": None,
        "updated_at": STAMP,
        "methodology": {"summary": "Review", "steps": ["Read", "Check"], "version": "v1"},
        "evidence": [{"ref": "source-1", "type": "source_snapshot", "locator": None, "snapshot_hash": "a" * 64}],
        "limitations": ["Limited & documented"],
        "faq": [{"question": "Q & A?", "answer": "<Answer>", "evidence_refs": ["source-1"]}],
        "visible_content": {"blocks": [{"key": "intro", "type": "paragraph", "text": "Body <unsafe> & text"}]},
        "source_snapshot_refs": [],
        "snapshot_hash": "b" * 64,
        "created_by": ACTOR,
        "created_at": STAMP,
    }


def _service() -> site_render.SiteRenderService:
    return site_render.SiteRenderService(clock=lambda: datetime(2026, 9, 19, 12, tzinfo=timezone.utc))


def test_render_page_is_escaped_and_contract_valid() -> None:
    result = _service().render_page(
        page_version=_page(), base_origin="HTTPS://Example.COM/", actor_id=ACTOR,
        trace_id="trace-site-002", idempotency_key="render-1",
    )
    assert result["base_origin"] == "https://example.com"
    assert "<unsafe>" not in result["html"]
    assert "&lt;unsafe&gt;" in result["html"]
    assert '<link rel="canonical" href="https://example.com/guides/first-party">' in result["html"]
    assert 'hreflang="x-default"' in result["html"]
    assert "https://example.com/guides/first-party" in result["sitemap_xml"]
    assert "&lt;Answer&gt;" in result["html"]
    assert "<script" not in result["html"].lower()
    schema = json.loads((ROOT / "packages/contracts/jsonschema/site-publication.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(result["manifest"]["publications"][0])
    ElementTree.fromstring(result["sitemap_xml"])
    ElementTree.fromstring(result["rss_xml"])
    ElementTree.fromstring(result["atom_xml"])


def test_locale_variants_emit_sorted_hreflang_and_x_default() -> None:
    primary = _page(locale="en-US")
    variant = _page(locale="fr-FR", path="/fr/guides/first-party", page_id=PAGE)
    result = _service().render_page(
        page_version=primary, locale_variants={"fr-FR": variant},
        base_origin="https://example.com", x_default_locale="fr-FR",
    )
    html = result["html"]
    assert html.index('hreflang="en-US"') < html.index('hreflang="fr-FR"') < html.index('hreflang="x-default"')
    assert 'hreflang="x-default" href="https://example.com/fr/guides/first-party"' in html
    publication = result["manifest"]["publications"][0]
    assert {item["locale"] for item in publication["hreflang"]} == {"en-US", "fr-FR", "x-default"}


def test_historical_and_non_public_versions_are_filtered_before_route_selection() -> None:
    old = _page(version_no=1, status="superseded")
    current = _page(version_no=2, status="published", title="Current")
    # Distinct IDs are required for the two immutable versions.
    current["id"] = "88888888-8888-4888-8888-888888888888"
    result = _service().render_site(page_versions=[old, current], base_origin="https://example.com")
    assert "Current" in result["html"]
    assert "superseded" not in result["sitemap_xml"]
    assert result["manifest"]["page_version_ids"] == [current["id"]]

    draft = _page(status="draft")
    empty = _service().render_site(page_versions=[draft], base_origin="https://example.com")
    assert empty["html"] == ""
    assert "<url>" not in empty["sitemap_xml"]
    assert "Sitemap: https://example.com/sitemap.xml" in empty["robots_txt"]


def test_conflicting_public_route_tenant_and_origin_errors() -> None:
    first = _page(version_no=2, title="A")
    second = _page(version_no=2, title="B")
    second["id"] = "99999999-9999-4999-8999-999999999999"
    with pytest.raises(site_render.SiteRenderError) as duplicate:
        _service().render_site(page_versions=[first, second], base_origin="https://example.com")
    assert duplicate.value.code == "DUPLICATE_PUBLIC_ROUTE"

    with pytest.raises(site_render.SiteRenderError) as foreign:
        _service().render_page(page_version=_page(org_id=OTHER_ORG), org_id=ORG, base_origin="https://example.com")
    assert foreign.value.code == "TENANT_SCOPE_VIOLATION"

    for origin in ("https://example.com/path", "https://user:pass@example.com", "ftp://example.com", "https://example.com/?q=1"):
        with pytest.raises(site_render.SiteRenderError) as invalid:
            _service().render_page(page_version=_page(), base_origin=origin)
        assert invalid.value.code == "INVALID_ORIGIN"


def test_idempotent_replay_is_byte_stable_and_payload_conflict_is_rejected() -> None:
    service = _service()
    kwargs = {"page_version": _page(), "base_origin": "https://example.com", "idempotency_key": "same-key"}
    first = service.render_page(**kwargs)
    replay = service.render_page(**kwargs)
    assert replay == first
    replay["html"] = "tampered"
    assert service.render_page(**kwargs)["html"] == first["html"]
    with pytest.raises(site_render.SiteRenderError) as reused:
        service.render_page(**{**kwargs, "site_title": "Changed"})
    assert reused.value.code == "IDEMPOTENCY_KEY_REUSED"
    assert len(service.audit_for(org_id=ORG)) == 1


class _RegionEligibilityPort:
    """Small GEO_REGION-002 port fixture; the renderer only sees decisions."""

    def check_page(self, page: dict, **_: object) -> dict:
        allowed = page["locale"] != "fr-FR" and not page.get("region_disabled", False)
        return {
            "decision": "eligible" if allowed else "deny",
            "status": "eligible" if allowed else "blocked",
            "decision_hash": ("a" if allowed else "b") * 64,
        }


def test_region_filter_removes_blocked_page_from_every_public_artifact() -> None:
    primary = _page(locale="en-US")
    blocked = _page(locale="fr-FR", path="/fr/guides/first-party")
    blocked["id"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    result = site_render.SiteRenderService(
        clock=lambda: datetime(2026, 9, 19, 12, tzinfo=timezone.utc),
        eligibility_port=_RegionEligibilityPort(),
    ).render_site(
        page_versions=[blocked, primary],
        base_origin="https://example.com",
        x_default_locale="fr-FR",
    )
    for artifact in (result["html"], result["sitemap_xml"], result["rss_xml"], result["atom_xml"]):
        assert "/fr/guides/first-party" not in artifact
    assert 'hreflang="fr-FR"' not in result["html"]
    assert 'hreflang="x-default" href="https://example.com/guides/first-party"' in result["html"]
    assert result["manifest"]["page_version_ids"] == [primary["id"]]


def test_region_filter_blocks_primary_and_is_order_deterministic() -> None:
    blocked = _page(locale="fr-FR", path="/fr/guides/first-party")
    with pytest.raises(site_render.SiteRenderError) as error:
        site_render.SiteRenderService(
            clock=lambda: datetime(2026, 9, 19, 12, tzinfo=timezone.utc),
            region_filter=_RegionEligibilityPort(),
        ).render_page(page_version=blocked, base_origin="https://example.com")
    assert error.value.code == "PAGE_NOT_RENDERABLE"

    first = _page(locale="en-US")
    second = _page(locale="de-DE", path="/de/guides/first-party")
    second["id"] = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    kwargs = {
        "base_origin": "https://example.com",
        "eligibility_port": _RegionEligibilityPort(),
    }
    left = _service().render_site(page_versions=[first, second], actor_id=ACTOR, trace_id="one", **kwargs)
    right = _service().render_site(page_versions=[second, first], actor_id=OTHER_ORG, trace_id="two", **kwargs)
    assert left["artifacts"] == right["artifacts"]
    assert left["hashes"] == right["hashes"]
    assert left["manifest"]["request_hash"] == right["manifest"]["request_hash"]
