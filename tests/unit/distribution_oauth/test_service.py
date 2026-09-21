import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from modules.distribution.oauth import (
    FakeOAuthProvider,
    OAuthError,
    OAuthService,
    TokenLeaseService,
    pkce_challenge,
)


NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def _flow():
    provider = FakeOAuthProvider()
    service = OAuthService(providers={"fake": provider})
    org_id, actor_id = uuid4(), uuid4()
    verifier = "v" * 64
    created = service.create_session(
        org_id=org_id,
        actor_id=actor_id,
        trace_id="trace-create",
        idempotency_key="oauth-create-1",
        provider="fake",
        redirect_uri="https://app.test/oauth/callback",
        pkce_challenge_value=pkce_challenge(verifier),
        requested_scopes=["profile", "content.draft"],
        now=NOW,
    )
    session_id = created["session"]["id"]
    code = provider.issue_code(
        state=created["state"],
        redirect_uri="https://app.test/oauth/callback",
        pkce_challenge=created["session"]["pkce_challenge"],
        external_account_id="fake-account-1",
        scopes=["profile", "content.draft"],
        access_token="access-secret-fixture",
        refresh_token="refresh-secret-fixture",
        expires_at=NOW + timedelta(hours=1),
    )
    return service, provider, org_id, actor_id, verifier, created, code, session_id


def test_fake_oauth_flow_binds_state_pkce_redirect_scope_and_secret_boundary():
    service, provider, org_id, actor_id, verifier, created, code, session_id = _flow()
    result = service.handle_callback(
        org_id=org_id,
        actor_id=actor_id,
        trace_id="trace-callback",
        idempotency_key="oauth-callback-1",
        session_id=session_id,
        state=created["state"],
        code=code,
        pkce_verifier=verifier,
        redirect_uri="https://app.test/oauth/callback",
        now=NOW + timedelta(minutes=1),
    )
    assert result["session"]["status"] == "verified"
    assert result["connection"]["authorization_status"] == "authorized"
    assert result["authorization_evidence"]["scope_snapshot"] == {
        "provider": "fake",
        "scopes": ["content.draft", "profile"],
    }
    assert service.secret_manager.read(secret_reference=result["secret_reference"])["access"] == "access-secret-fixture"
    serialized = json.dumps({"audit": service.audit, "events": service.events,
                             "connections": list(service.connections.values())})
    assert "access-secret-fixture" not in serialized
    assert "refresh-secret-fixture" not in serialized
    assert provider.revocations == []

    replay = service.handle_callback(
        org_id=org_id,
        actor_id=actor_id,
        trace_id="trace-callback-replay",
        idempotency_key="oauth-callback-1",
        session_id=session_id,
        state=created["state"],
        code=code,
        pkce_verifier=verifier,
        redirect_uri="https://app.test/oauth/callback",
        now=NOW + timedelta(minutes=1),
    )
    assert replay == result


@pytest.mark.parametrize(
    "change,code",
    [
        ("state", "CSRF_STATE_MISMATCH"),
        ("redirect_uri", "REDIRECT_URI_MISMATCH"),
        ("pkce_verifier", "PKCE_MISMATCH"),
    ],
)
def test_callback_rejects_security_mismatch(change, code):
    service, provider, org_id, actor_id, verifier, created, auth_code, session_id = _flow()
    kwargs = {
        "org_id": org_id,
        "actor_id": actor_id,
        "trace_id": "trace-bad-callback",
        "idempotency_key": f"oauth-bad-{change}",
        "session_id": session_id,
        "state": created["state"],
        "code": auth_code,
        "pkce_verifier": verifier,
        "redirect_uri": "https://app.test/oauth/callback",
        "now": NOW + timedelta(minutes=1),
    }
    if change == "state":
        kwargs["state"] = "wrong-state"
    elif change == "redirect_uri":
        kwargs["redirect_uri"] = "https://attacker.test/callback"
    else:
        kwargs["pkce_verifier"] = "x" * 64
    with pytest.raises(OAuthError) as error:
        service.handle_callback(**kwargs)
    assert error.value.code == code


def test_scope_allowlist_and_revocation_are_fail_closed():
    provider = FakeOAuthProvider(allowed_scopes=["profile"])
    service = OAuthService(providers={"fake": provider})
    with pytest.raises(OAuthError) as error:
        service.create_session(
            org_id=uuid4(), actor_id=uuid4(), trace_id="trace", idempotency_key="scope-bad",
            provider="fake", redirect_uri="https://app.test/callback",
            pkce_challenge_value="c" * 64, requested_scopes=["content.write"], now=NOW,
        )
    assert error.value.code == "SCOPE_NOT_ALLOWED"

    service, provider, org_id, actor_id, verifier, created, code, session_id = _flow()
    connected = service.handle_callback(
        org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key="callback",
        session_id=session_id, state=created["state"], code=code, pkce_verifier=verifier,
        redirect_uri="https://app.test/oauth/callback", now=NOW + timedelta(minutes=1),
    )
    revoked = service.revoke(
        org_id=org_id, actor_id=actor_id, trace_id="trace-revoke", idempotency_key="revoke",
        connection_id=session_id, reason="owner requested", now=NOW + timedelta(minutes=2),
    )
    assert revoked["authorization_status"] == "revoked"
    assert revoked["connection_status"] == "revoked"
    with pytest.raises(OAuthError):
        service.secret_manager.read(secret_reference=connected["secret_reference"])
    assert provider.revocations[0]["secret_reference"] == connected["secret_reference"]


def test_expired_session_is_terminal_and_does_not_exchange_code():
    provider = FakeOAuthProvider()
    service = OAuthService(providers={"fake": provider})
    org_id, actor_id = uuid4(), uuid4()
    verifier = "v" * 64
    created = service.create_session(
        org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key="expired-create",
        provider="fake", redirect_uri="https://app.test/callback", pkce_challenge_value=pkce_challenge(verifier),
        requested_scopes=["profile"], ttl_seconds=60, now=NOW,
    )
    code = provider.issue_code(state=created["state"], redirect_uri="https://app.test/callback",
                               pkce_challenge=created["session"]["pkce_challenge"], scopes=["profile"])
    with pytest.raises(OAuthError) as error:
        service.handle_callback(
            org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key="expired-callback",
            session_id=created["session"]["id"], state=created["state"], code=code,
            pkce_verifier=verifier, redirect_uri="https://app.test/callback", now=NOW + timedelta(minutes=2),
        )
    assert error.value.code == "OAUTH_SESSION_EXPIRED"
    assert service.sessions[(str(org_id), created["session"]["id"])].status == "expired"


def test_token_lease_has_one_active_version_and_append_only_transitions():
    lease_service = TokenLeaseService()
    org_id, actor_id, connection_id = uuid4(), uuid4(), uuid4()
    first = lease_service.issue(
        org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key="lease-1",
        connection_id=connection_id, secret_reference="secret://oauth/test/one",
        expires_at=NOW + timedelta(hours=1), now=NOW,
    )
    second = lease_service.rotate(
        org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key="lease-2",
        connection_id=connection_id, secret_reference="secret://oauth/test/two",
        expires_at=NOW + timedelta(hours=2), now=NOW + timedelta(minutes=1),
    )
    assert first["status"] == "active"  # returned contracts are immutable snapshots
    assert second["status"] == "active"
    assert {lease["status"] for lease in lease_service.leases.values()} == {"revoked", "active"}
    assert lease_service.get_active(org_id=org_id, connection_id=connection_id)["id"] == second["id"]
    expired = lease_service.expire(
        org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key="lease-3",
        connection_id=connection_id, now=NOW + timedelta(minutes=2),
    )
    assert expired["status"] == "expired"
    assert lease_service.get_active(org_id=org_id, connection_id=connection_id) is None
    assert len(lease_service.events) == 3
