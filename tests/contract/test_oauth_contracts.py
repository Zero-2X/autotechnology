import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from modules.distribution.oauth import FakeOAuthProvider, OAuthService, pkce_challenge


ROOT = Path(__file__).resolve().parents[2]


def _validator(name):
    schema = json.loads((ROOT / "packages/contracts/jsonschema" / name).read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def test_oauth_session_and_evidence_contracts_are_closed_and_valid():
    provider = FakeOAuthProvider()
    service = OAuthService(providers={"fake": provider})
    from datetime import datetime, timezone
    from uuid import uuid4

    now = datetime(2026, 9, 21, tzinfo=timezone.utc)
    verifier = "v" * 64
    created = service.create_session(
        org_id=uuid4(), actor_id=uuid4(), trace_id="trace", idempotency_key="contract-create",
        provider="fake", redirect_uri="https://app.test/callback",
        pkce_challenge_value=pkce_challenge(verifier), requested_scopes=["profile"], now=now,
    )
    _validator("oauth-authorization-session.schema.json").validate(created["session"])
    code = provider.issue_code(
        state=created["state"], redirect_uri="https://app.test/callback",
        pkce_challenge=created["session"]["pkce_challenge"], scopes=["profile"],
    )
    result = service.handle_callback(
        org_id=created["session"]["org_id"], actor_id=uuid4(), trace_id="trace", idempotency_key="contract-callback",
        session_id=created["session"]["id"], state=created["state"], code=code,
        pkce_verifier=verifier, redirect_uri="https://app.test/callback", now=now,
    )
    _validator("authorization-evidence.schema.json").validate(result["authorization_evidence"])
    assert not _validator("oauth-authorization-session.schema.json").is_valid({**created["session"], "unexpected": True})
