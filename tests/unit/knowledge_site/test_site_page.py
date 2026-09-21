from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "apps" / "knowledge-site" / "scripts" / "site_page.py"
SPEC = importlib.util.spec_from_file_location("knowledge_site_site_page", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
site_page = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(site_page)


ORG = "11111111-1111-4111-8111-111111111111"
OTHER_ORG = "22222222-2222-4222-8222-222222222222"
ACTOR = "33333333-3333-4333-8333-333333333333"
CANONICAL = "44444444-4444-4444-8444-444444444444"
REGION = "55555555-5555-4555-8555-555555555555"
VARIANT = "66666666-6666-4666-8666-666666666666"
STAMP = "2026-09-19T12:00:00Z"


def _service(*, canonical_port=None, variant_port=None, region_port=None):
    return site_page.SitePageService(
        clock=lambda: datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc),
        canonical_version_port=canonical_port,
        variant_version_port=variant_port,
        region_version_port=region_port,
    )


def _kwargs(**overrides):
    value = {
        "org_id": ORG,
        "actor_id": ACTOR,
        "trace_id": "trace-site-001",
        "idempotency_key": "site-command-1",
        "page_key": "guides/first-party",
        "version_no": 1,
        "expected_previous_version": 0,
        "canonical_content_version_id": CANONICAL,
        "region_profile_version_id": REGION,
        "locale": "en-us",
        "url_path": "/guides/first-party/",
        "title": "First party guide",
        "summary": "A concise guide.",
        "author": {"id": "author-1", "name": "A. Author", "url": "https://example.test/authors/a"},
        "reviewer": {"id": "reviewer-1", "name": "R. Reviewer", "url": None},
        "methodology": {"summary": "Reviewed against primary evidence.", "steps": ["Read source", "Check version"], "version": "method-v1"},
        "evidence": [{"ref": "source-snapshot-1", "type": "source_snapshot", "locator": "p. 2", "snapshot_hash": "a" * 64}],
        "limitations": ["Only the documented configuration is covered."],
        "faq": [{"question": "Is this current?", "answer": "It is tied to the stored version.", "evidence_refs": ["source-snapshot-1"]}],
        "visible_content": {"blocks": [{"key": "intro", "type": "paragraph", "text": "Visible text."}]},
        "source_snapshot_refs": [],
    }
    value.update(overrides)
    return value


def test_create_version_normalizes_metadata_and_matches_contract() -> None:
    service = _service()
    response = service.create_version(**_kwargs())
    version = response["version"]
    assert version["locale"] == "en-US"
    assert version["url_path"] == "/guides/first-party"
    assert version["canonical_url"] == version["url_path"]
    assert version["status"] == "draft"
    schema = json.loads((ROOT / "packages/contracts/jsonschema/site-page-version.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(version)
    assert len(service.audit_for(org_id=ORG)) == 1
    assert "answer" not in service.audit_for(org_id=ORG)[0]


def test_idempotent_replay_is_deep_copied_and_does_not_create_second_version() -> None:
    service = _service()
    first = service.create_version(**_kwargs())
    replay = service.create_version(**_kwargs())
    assert replay == first
    replay["version"]["title"] = "mutated"
    assert service.get_version(org_id=ORG, version_id=first["version"]["id"])["title"] == "First party guide"
    assert len(service.list_versions(org_id=ORG, site_page_id=first["page"]["id"])) == 1
    with pytest.raises(site_page.SitePageError) as exc:
        service.create_version(**_kwargs(summary="different"))
    assert exc.value.code == "IDEMPOTENCY_KEY_REUSED"


def test_version_sequence_is_append_only_and_stale_expected_version_is_rejected() -> None:
    service = _service()
    first = service.create_version(**_kwargs())
    second = service.create_version(**_kwargs(
        idempotency_key="site-command-2",
        version_no=2,
        expected_previous_version=1,
        title="First party guide v2",
    ))
    assert [item["version_no"] for item in service.list_versions(org_id=ORG, site_page_id=first["page"]["id"])] == [1, 2]
    assert second["version"]["snapshot_hash"] != first["version"]["snapshot_hash"]
    with pytest.raises(site_page.SitePageError) as exc:
        service.create_version(**_kwargs(
            idempotency_key="site-command-3",
            version_no=2,
            expected_previous_version=1,
        ))
    assert exc.value.code == "VERSION_CONFLICT"


@pytest.mark.parametrize(
    "field, value, code",
    [
        ("url_path", "/guides//bad", "INVALID_CANONICAL_URL"),
        ("url_path", "/guides/%2e%2e/private", "INVALID_CANONICAL_URL"),
        ("url_path", "/api/private", "INVALID_CANONICAL_URL"),
        ("locale", "not a locale", "INVALID_SITE_PAGE"),
        ("evidence", [], "EVIDENCE_REQUIRED"),
        ("methodology", {"summary": "x", "steps": []}, "INVALID_SITE_PAGE"),
        ("faq", [{"question": "Q", "answer": "A", "evidence_refs": ["missing"]}], "INVALID_SITE_PAGE"),
    ],
)
def test_deterministic_metadata_validation(field: str, value: object, code: str) -> None:
    service = _service()
    with pytest.raises(site_page.SitePageError) as exc:
        service.create_version(**_kwargs(**{field: value}))
    assert exc.value.code == code


class Port:
    def __init__(self, records):
        self.records = records

    def get_version(self, *, org_id: str, version_id: str):
        return self.records.get((org_id, version_id))


def test_source_ports_enforce_tenant_and_ready_status_without_leaking_ids() -> None:
    canonical = Port({(ORG, CANONICAL): {"id": CANONICAL, "org_id": ORG, "status": "approved"}})
    region = Port({(ORG, REGION): {"id": REGION, "org_id": ORG, "status": "active"}})
    variant = Port({(ORG, VARIANT): {"id": VARIANT, "org_id": ORG, "status": "approved"}})
    service = _service(canonical_port=canonical, region_port=region, variant_port=variant)
    created = service.create_version(**_kwargs(variant_version_id=VARIANT))
    assert created["version"]["variant_version_id"] == VARIANT

    foreign_canonical = Port({(OTHER_ORG, CANONICAL): {"id": CANONICAL, "org_id": OTHER_ORG, "status": "approved"}})
    blocked = _service(canonical_port=foreign_canonical, region_port=region)
    with pytest.raises(site_page.SitePageError) as exc:
        blocked.create_version(**_kwargs(idempotency_key="foreign-source"))
    assert exc.value.code == "TENANT_SCOPE_VIOLATION"


def test_cross_tenant_reads_are_rejected_and_same_page_key_isolated() -> None:
    service = _service()
    own = service.create_version(**_kwargs())
    with pytest.raises(site_page.SitePageError) as exc:
        service.get_version(org_id=OTHER_ORG, version_id=own["version"]["id"])
    assert exc.value.code == "TENANT_SCOPE_VIOLATION"
    other = service.create_version(**_kwargs(org_id=OTHER_ORG, idempotency_key="other-tenant"))
    assert other["version"]["site_page_id"] != own["version"]["site_page_id"]


def test_repository_returns_immutable_snapshots() -> None:
    repository = site_page.InMemorySitePageRepository()
    service = _service()
    service.repository = repository
    result = service.create_version(**_kwargs())
    page = repository.get_page(org_id=ORG, page_id=result["page"]["id"])
    assert page is not None
    page["page_key"] = "tampered"
    assert repository.get_page(org_id=ORG, page_id=result["page"]["id"])["page_key"] == "guides/first-party"
