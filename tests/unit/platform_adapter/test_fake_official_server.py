from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from adapters.fake import FakeOfficialServer, FakePlatformError


NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def test_fake_server_draft_publish_unknown_result_and_requery():
    org_id = uuid4()
    server = FakeOfficialServer(quota=10, clock=lambda: NOW)
    handle = server.issue_connection_handle(org_id=org_id, external_account_id="sandbox-1")
    capability = server.capability(created_at=NOW)
    assert capability["platform_id"] == server.platform_id
    draft = server.create_draft(
        org_id=org_id, connection_handle=handle, idempotency_key="draft-1",
        title="Synthetic draft", body="No network", now=NOW,
    )
    with pytest.raises(FakePlatformError) as error:
        server.publish(
            org_id=org_id, connection_handle=handle, draft_id=draft["id"],
            idempotency_key="publish-1", unknown_result=True, now=NOW,
        )
    assert error.value.code == "UNKNOWN_RESULT"
    object_id = next(iter(server.records.values()))["external_object_id"]
    result = server.requery(
        org_id=org_id, connection_handle=handle, external_object_id=object_id,
        idempotency_key="requery-1",
    )
    assert result["status"] == "published"
    assert result["external_url"].startswith("private://")
    replay = server.publish(
        org_id=org_id, connection_handle=handle, draft_id=draft["id"],
        idempotency_key="publish-1", unknown_result=True, now=NOW,
    )
    assert replay["external_object_id"] == object_id


def test_fake_server_enforces_tenant_permissions_and_quota():
    org_id, other_org = uuid4(), uuid4()
    server = FakeOfficialServer(quota=1, window_seconds=60, clock=lambda: NOW)
    handle = server.issue_connection_handle(org_id=org_id, external_account_id="sandbox-1")
    with pytest.raises(FakePlatformError) as error:
        server.create_draft(org_id=other_org, connection_handle=handle, idempotency_key="cross",
                            title="x", body="y", now=NOW)
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    first = server.create_draft(org_id=org_id, connection_handle=handle, idempotency_key="one",
                                title="x", body="y", now=NOW)
    with pytest.raises(FakePlatformError) as error:
        server.create_draft(org_id=org_id, connection_handle=handle, idempotency_key="two",
                            title="x", body="y", now=NOW)
    assert error.value.code == "QUOTA_EXCEEDED"
    server.set_permissions(org_id=org_id, connection_handle=handle, permissions=["requery"])
    with pytest.raises(FakePlatformError) as error:
        server.publish(org_id=org_id, connection_handle=handle, draft_id=first["id"],
                       idempotency_key="publish", now=NOW + timedelta(seconds=61))
    assert error.value.code == "PERMISSION_REVOKED"
    server.revoke_handle(org_id=org_id, connection_handle=handle)
    with pytest.raises(FakePlatformError) as error:
        server.requery(org_id=org_id, connection_handle=handle, external_object_id="missing",
                       idempotency_key="requery")
    assert error.value.code == "PERMISSION_REVOKED"


def test_fake_server_never_accepts_raw_token_like_handle():
    server = FakeOfficialServer()
    with pytest.raises(FakePlatformError) as error:
        server.create_draft(org_id=uuid4(), connection_handle="access-token-value",
                            idempotency_key="bad", title="x", body="y")
    assert error.value.code == "INVALID_CONNECTION_HANDLE"


def test_draft_only_scope_cannot_publish():
    server, org_id = FakeOfficialServer(), uuid4()
    handle = server.issue_connection_handle(org_id=org_id, external_account_id="draft-only", scopes=["content.draft"])
    draft = server.create_draft(org_id=org_id, connection_handle=handle, idempotency_key="d", title="x", body="y")
    with pytest.raises(FakePlatformError) as error:
        server.publish(org_id=org_id, connection_handle=handle, draft_id=draft["id"], idempotency_key="p")
    assert error.value.code == "SCOPE_REQUIRED"
    assert not server.records


def test_accounts_in_same_tenant_cannot_access_each_others_objects():
    server, org_id = FakeOfficialServer(), uuid4()
    owner = server.issue_connection_handle(org_id=org_id, external_account_id="owner")
    other = server.issue_connection_handle(org_id=org_id, external_account_id="other")
    draft = server.create_draft(org_id=org_id, connection_handle=owner, idempotency_key="d", title="x", body="y")
    with pytest.raises(FakePlatformError) as error:
        server.publish(org_id=org_id, connection_handle=other, draft_id=draft["id"], idempotency_key="wrong-p")
    assert error.value.code == "ACCOUNT_SCOPE_VIOLATION"
    published = server.publish(org_id=org_id, connection_handle=owner, draft_id=draft["id"], idempotency_key="p")
    for operation in (server.requery, server.metrics):
        with pytest.raises(FakePlatformError) as error:
            operation(org_id=org_id, connection_handle=other, external_object_id=published["external_object_id"], idempotency_key="wrong-read")
        assert error.value.code == "ACCOUNT_SCOPE_VIOLATION"


def test_lost_acknowledgement_keeps_single_publication_even_with_new_key():
    server, org_id = FakeOfficialServer(), uuid4()
    handle = server.issue_connection_handle(org_id=org_id, external_account_id="owner")
    draft = server.create_draft(org_id=org_id, connection_handle=handle, idempotency_key="d", title="x", body="y")
    args = dict(org_id=org_id, connection_handle=handle, draft_id=draft["id"])
    with pytest.raises(FakePlatformError, match="acknowledgement"):
        server.publish(**args, idempotency_key="p", unknown_result=True)
    replay = server.publish(**args, idempotency_key="p")
    with pytest.raises(FakePlatformError) as error:
        server.publish(**args, idempotency_key="new-p")
    assert error.value.code == "ALREADY_PUBLISHED"
    assert len(server.records) == 1
    assert len([row for row in server.audit if row["event_type"] == "fake.platform.publish"]) == 1
    assert server.drafts[(str(org_id), draft["id"])]["status"] == "published"
    assert next(iter(server.records.values())) == replay
