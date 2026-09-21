from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest

from modules.geo_region import InMemoryRegionService, RegionEligibilityService


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "apps" / "knowledge-site" / "scripts" / "site_render.py"
SPEC = importlib.util.spec_from_file_location("geo_region_002_site_render", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
site_render = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(site_render)

NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


def _page(*, org_id, version_id, locale: str, path: str, disabled: bool = False) -> dict:
    return {
        "id": str(uuid4()),
        "org_id": str(org_id),
        "site_page_id": str(uuid4()),
        "page_key": "guides/region-aware",
        "version_no": 1,
        "region_profile_version_id": str(version_id),
        "locale": locale,
        "url_path": path,
        "canonical_url": path,
        "render_mode": "ssr",
        "status": "published",
        "title": f"Guide {locale}",
        "summary": "Regional guide",
        "updated_at": NOW.isoformat(),
        "disclosures": ["regional-disclosure"],
        "region_disabled": disabled,
        "visible_content": {"blocks": [{"type": "paragraph", "text": "Visible text"}]},
    }


def test_geo_region_002_filters_site_alternates_and_feeds_before_render() -> None:
    org_id = uuid4()
    service = InMemoryRegionService(clock=lambda: NOW)
    profile = service.create_profile(org_id=org_id, region_code="US", idempotency_key="site-region-profile")
    draft = service.create_draft(
        org_id=org_id,
        profile_id=profile.id,
        expected_current_version_id=None,
        idempotency_key="site-region-version",
        locales=["en-US", "fr-FR"],
        timezone="UTC",
        date_number_format="YYYY-MM-DD",
        units="imperial",
        currency="USD",
        terminology_version="terms-v1",
        disclosure_rules=[{"id": "regional-disclosure", "required": True}],
        restricted_topics=[],
        data_residency="US",
        retention_days=30,
        deletion_sla_hours=24,
        platform_eligibility=["web"],
        policy_snapshot_id=uuid4(),
        valid_from=NOW - timedelta(days=1),
        valid_to=NOW + timedelta(days=1),
    )
    version = service.activate_version(
        org_id=org_id,
        version_id=draft.id,
        expected_version=draft.version_no,
        idempotency_key="site-region-activate",
    )
    checker = RegionEligibilityService(region_service=service, clock=lambda: NOW)
    renderer = site_render.SiteRenderService(clock=lambda: NOW, eligibility_port=checker)
    allowed = _page(org_id=org_id, version_id=version.id, locale="en-US", path="/guide")
    blocked = _page(
        org_id=org_id,
        version_id=version.id,
        locale="fr-FR",
        path="/fr/guide",
        disabled=True,
    )

    result = renderer.render_site(
        page_versions=[blocked, allowed],
        org_id=str(org_id),
        base_origin="https://example.com",
        x_default_locale="fr-FR",
        eligibility_evaluated_at=NOW,
    )
    for artifact in (result["html"], result["sitemap_xml"], result["rss_xml"], result["atom_xml"]):
        assert "/fr/guide" not in artifact
    assert 'hreflang="x-default" href="https://example.com/guide"' in result["html"]

    with pytest.raises(site_render.SiteRenderError) as error:
        renderer.render_page(
            page_version=blocked,
            org_id=str(org_id),
            base_origin="https://example.com",
            eligibility_evaluated_at=NOW,
        )
    assert error.value.code == "PAGE_NOT_RENDERABLE"
