from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from apps.api.main import create_app
from modules.provenance import RightsGuardService, RightsService, SourceService


def test_rights_guard_api_returns_auditable_block_decision(tmp_path) -> None:
    source = SourceService(tmp_path / "guard-api.db")
    rights = RightsService(connection=source._connection)
    guard = RightsGuardService(rights_service=rights)
    client = TestClient(create_app(provenance_service=source, rights_service=rights, rights_guard_service=guard))
    org_id, actor_id = uuid4(), uuid4()
    captured = source.ingest(org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key="ga-s1",
                             source_type="url", canonical_url="https://guard-api.example", content="x")
    sid = captured["snapshot"]["id"]
    source.transition_snapshot(org_id=org_id, snapshot_id=sid, actor_id=actor_id, trace_id="trace", idempotency_key="ga-s2", action="quarantine", expected_version=0)
    source.transition_snapshot(org_id=org_id, snapshot_id=sid, actor_id=actor_id, trace_id="trace", idempotency_key="ga-s3", action="mark_usable", expected_version=1)
    record_id = uuid4()
    created = rights.create_version(org_id=org_id, rights_record_id=record_id, actor_id=actor_id, trace_id="trace", idempotency_key="ga-r1", source_snapshot_ids=[sid], license_ref="l", rights_holder="h", permitted_regions=["US"], permitted_locales=["en-US"], permitted_media=["text"], permitted_use="commercial", terms_snapshot_hash="a" * 64, policy_rule_version="p", valid_to=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat().replace("+00:00", "Z"))
    rights.verify_version(org_id=org_id, rights_record_id=record_id, version_id=created["version"]["id"], actor_id=actor_id, trace_id="trace", idempotency_key="ga-r2", expected_version=1, verification_reason="reviewed")
    response = client.post("/internal/rights-guard/check", headers={"X-Org-Id": str(org_id), "X-Actor-Id": str(actor_id), "Idempotency-Key": "ga-check"}, json={"rights_record_version_id": created["version"]["id"], "region": "DE", "locale": "de-DE", "media": "video", "use": "commercial"})
    assert response.status_code == 200
    assert response.json()["data"]["allowed"] is False
    source.close()
