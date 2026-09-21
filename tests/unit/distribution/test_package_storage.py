from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import pytest

from modules.distribution import DistributionError, ExportPackageStorage, ManualAdapter


ORG = "00000000-0000-4000-8000-000000000001"
OTHER_ORG = "00000000-0000-4000-8000-000000000009"
ACTOR = "00000000-0000-4000-8000-000000000002"
VARIANT = "00000000-0000-4000-8000-000000000003"
INTENT = "00000000-0000-4000-8000-000000000005"
STAMP = "2026-09-19T00:00:00Z"


def _export() -> dict:
    return ManualAdapter().export(
        org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="manual", generated_at=STAMP,
        publication_intent={"id": INTENT, "org_id": ORG, "variant_version_id": VARIANT, "asset_version_ids": [],
                            "payload_snapshot": {"title": "Title", "body": {}, "tags": [], "disclosure": None}},
    )


def test_register_private_package_issue_and_verify_short_lived_url() -> None:
    exported = _export()
    storage = ExportPackageStorage(signing_key="test-key", signed_url_ttl_seconds=60)
    registered = storage.register_package(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="register",
                                          export_package=exported["export_package"], files=exported["files"], registered_at=STAMP)
    assert registered["export_package"]["storage_object_ref"].startswith("private://")
    issued = storage.issue_download_url(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="download",
                                        package_id=exported["export_package"]["id"], issued_at=STAMP)
    replay = storage.issue_download_url(org_id=ORG, actor_id=ACTOR, trace_id="replay", idempotency_key="download",
                                        package_id=exported["export_package"]["id"], issued_at=STAMP)
    assert issued == replay
    assert urlsplit(issued["url"]).scheme == "private"
    assert "http" not in issued["url"]
    verified = storage.verify_download_url(org_id=ORG, url=issued["url"], at="2026-09-19T00:00:30Z")
    assert verified["package_hash"] == exported["export_package"]["package_hash"]
    assert storage.read_file(org_id=ORG, package_id=exported["export_package"]["id"], name="manifest.json", at=STAMP).startswith(b"{")
    assert storage.packages[(ORG, exported["export_package"]["id"])]["download_count"] == 1
    assert storage.events[-1]["event_type"] == "export_package.downloaded"


def test_tampered_cross_tenant_and_expired_urls_are_rejected() -> None:
    exported = _export()
    storage = ExportPackageStorage(signing_key="test-key", signed_url_ttl_seconds=60)
    storage.register_package(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="register",
                             export_package=exported["export_package"], files=exported["files"], registered_at=STAMP)
    issued = storage.issue_download_url(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="download",
                                        package_id=exported["export_package"]["id"], issued_at=STAMP)
    query = parse_qs(urlsplit(issued["url"]).query)
    query["sig"] = ["0" * 64]
    parts = urlsplit(issued["url"])
    tampered = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), parts.fragment))
    with pytest.raises(DistributionError) as error:
        storage.verify_download_url(org_id=ORG, url=tampered, at=STAMP)
    assert error.value.code == "INVALID_SIGNED_URL"
    with pytest.raises(DistributionError) as error:
        storage.verify_download_url(org_id=OTHER_ORG, url=issued["url"], at=STAMP)
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    storage.expire_package(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="expire",
                           package_id=exported["export_package"]["id"], at="2026-09-26T00:00:00Z")
    with pytest.raises(DistributionError) as error:
        storage.issue_download_url(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="late",
                                    package_id=exported["export_package"]["id"], issued_at="2026-09-26T00:00:01Z")
    assert error.value.code == "PACKAGE_EXPIRED"


def test_revoke_requires_package_hash_and_blocks_reads() -> None:
    exported = _export()
    storage = ExportPackageStorage(signing_key="test-key")
    storage.register_package(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="register",
                             export_package=exported["export_package"], files=exported["files"], registered_at=STAMP)
    with pytest.raises(DistributionError) as error:
        storage.revoke_package(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="bad",
                               package_id=exported["export_package"]["id"], expected_package_hash="0" * 64, revoked_at=STAMP)
    assert error.value.code == "STALE_PACKAGE_VERSION"
    revoked = storage.revoke_package(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="revoke",
                                     package_id=exported["export_package"]["id"], expected_package_hash=exported["export_package"]["package_hash"], revoked_at=STAMP)
    assert revoked["status"] == "revoked"
    with pytest.raises(DistributionError) as error:
        storage.read_file(org_id=ORG, package_id=exported["export_package"]["id"], name="manifest.json", at=STAMP)
    assert error.value.code == "PACKAGE_REVOKED"
