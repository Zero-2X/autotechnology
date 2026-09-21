"""Tenant-scoped OAuth state machines with a safe fake provider.

This module implements the account-free part of the stage-8 boundary.  It
never calls a network provider and never puts a raw token in a contract,
audit record, event, or ordinary in-memory projection.  A real provider can
implement :class:`OAuthProvider` and reuse the same validation and lease
services after the external account dependency is satisfied.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import json
import secrets
from threading import RLock
from typing import Any, Mapping, Protocol, Sequence
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker

from modules.distribution.service import DistributionError, _EVENT_VALIDATOR, _hash, _stamp, _text, _time, _uuid


_ROOT = __import__("pathlib").Path(__file__).resolve().parents[3]
_SESSION_SCHEMA = json.loads(
    (_ROOT / "packages/contracts/jsonschema/oauth-authorization-session.schema.json").read_text(encoding="utf-8")
)
_EVIDENCE_SCHEMA = json.loads(
    (_ROOT / "packages/contracts/jsonschema/authorization-evidence.schema.json").read_text(encoding="utf-8")
)
_LEASE_SCHEMA = json.loads(
    (_ROOT / "packages/contracts/jsonschema/token-lease.schema.json").read_text(encoding="utf-8")
)
_SESSION_VALIDATOR = Draft202012Validator(_SESSION_SCHEMA, format_checker=FormatChecker())
_EVIDENCE_VALIDATOR = Draft202012Validator(_EVIDENCE_SCHEMA, format_checker=FormatChecker())
_LEASE_VALIDATOR = Draft202012Validator(_LEASE_SCHEMA, format_checker=FormatChecker())


class OAuthError(DistributionError):
    """Stable, deterministic OAuth boundary errors."""


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def pkce_challenge(verifier: str) -> str:
    """Return the RFC 7636 S256 challenge for a verifier."""

    if not isinstance(verifier, str) or not 43 <= len(verifier) <= 128:
        raise OAuthError("INVALID_PKCE_VERIFIER", "PKCE verifier must contain 43-128 characters")
    return _b64(hashlib.sha256(verifier.encode("ascii", "strict")).digest())


@dataclass(frozen=True)
class OAuthAuthorizationSession:
    id: UUID
    org_id: UUID
    provider: str
    state_hash: str
    pkce_challenge: str
    redirect_uri: str
    status: str
    expires_at: datetime
    created_at: datetime
    version: int = 1

    def as_contract(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "org_id": str(self.org_id),
            "provider": self.provider,
            "state_hash": self.state_hash,
            "pkce_challenge": self.pkce_challenge,
            "redirect_uri": self.redirect_uri,
            "status": self.status,
            "expires_at": _stamp(self.expires_at),
            "created_at": _stamp(self.created_at),
        }


@dataclass(frozen=True)
class OAuthGrant:
    """Provider exchange result kept local until it is sealed in a secret store."""

    external_account_id: str
    scopes: tuple[str, ...]
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None


class OAuthProvider(Protocol):
    """The minimal provider port required by the state machine."""

    name: str
    allowed_scopes: frozenset[str]

    def authorization_url(self, *, redirect_uri: str, state: str, pkce_challenge: str,
                          scopes: Sequence[str]) -> str: ...

    def exchange_code(self, *, code: str, redirect_uri: str, pkce_verifier: str,
                      expected_scopes: Sequence[str]) -> OAuthGrant: ...

    def revoke(self, *, external_account_id: str, secret_reference: str) -> None: ...


class FakeOAuthProvider:
    """Deterministic provider used by tests and local development only."""

    name = "fake"

    def __init__(self, *, allowed_scopes: Sequence[str] = ("profile", "content.read", "content.draft")) -> None:
        self.allowed_scopes = frozenset(str(scope) for scope in allowed_scopes)
        self._codes: dict[str, dict[str, Any]] = {}
        self.revocations: list[dict[str, str]] = []

    def authorization_url(self, *, redirect_uri: str, state: str, pkce_challenge: str,
                          scopes: Sequence[str]) -> str:
        if not scopes or not set(scopes).issubset(self.allowed_scopes):
            raise OAuthError("SCOPE_NOT_ALLOWED", "requested scope is not in provider allowlist")
        return (
            f"https://fake.oauth/authorize?provider={self.name}&redirect_uri={redirect_uri}"
            f"&state={state}&code_challenge={pkce_challenge}&scope={','.join(scopes)}"
        )

    def issue_code(self, *, state: str, redirect_uri: str, pkce_challenge: str,
                   external_account_id: str = "fake-account", scopes: Sequence[str] = ("profile",),
                   access_token: str = "fake-access-token", refresh_token: str | None = "fake-refresh-token",
                   expires_at: datetime | None = None) -> str:
        """Create a fixture callback code without contacting a platform."""

        if not set(scopes).issubset(self.allowed_scopes):
            raise OAuthError("SCOPE_NOT_ALLOWED", "fixture scope is not in provider allowlist")
        code = "fake-code-" + secrets.token_urlsafe(12)
        self._codes[code] = {
            "state": state,
            "redirect_uri": redirect_uri,
            "pkce_challenge": pkce_challenge,
            "external_account_id": external_account_id,
            "scopes": tuple(sorted(set(scopes))),
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
        }
        return code

    def exchange_code(self, *, code: str, redirect_uri: str, pkce_verifier: str,
                      expected_scopes: Sequence[str]) -> OAuthGrant:
        fixture = self._codes.pop(code, None)
        if fixture is None:
            raise OAuthError("OAUTH_CODE_INVALID", "authorization code is invalid or already used")
        if fixture["redirect_uri"] != redirect_uri:
            raise OAuthError("REDIRECT_URI_MISMATCH", "redirect URI does not match the authorization session")
        try:
            challenge = pkce_challenge(pkce_verifier)
        except UnicodeEncodeError as exc:
            raise OAuthError("INVALID_PKCE_VERIFIER", "PKCE verifier is not ASCII") from exc
        if not hmac.compare_digest(challenge, fixture["pkce_challenge"]):
            raise OAuthError("PKCE_MISMATCH", "PKCE verifier does not match the authorization request")
        if tuple(sorted(set(expected_scopes))) != fixture["scopes"]:
            raise OAuthError("SCOPE_MISMATCH", "provider scopes differ from the requested allowlist")
        return OAuthGrant(
            external_account_id=fixture["external_account_id"],
            scopes=fixture["scopes"],
            access_token=fixture["access_token"],
            refresh_token=fixture["refresh_token"],
            expires_at=fixture["expires_at"],
        )

    def revoke(self, *, external_account_id: str, secret_reference: str) -> None:
        self.revocations.append({"external_account_id": external_account_id, "secret_reference": secret_reference})


class InMemorySecretManager:
    """A test-only Secret Manager port.

    Raw values live in a private dictionary and are only returned by ``read``
    to an adapter boundary.  ``as_contract`` and ``audit`` expose references,
    never values.
    """

    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self._versions: dict[str, int] = {}

    def put(self, *, org_id: UUID | str, connection_id: UUID | str, access_token: str,
            refresh_token: str | None = None) -> dict[str, Any]:
        tenant, connection = _uuid(org_id, "org_id"), _uuid(connection_id, "connection_id")
        if not isinstance(access_token, str) or not access_token:
            raise OAuthError("TOKEN_REQUIRED", "access token is required")
        if refresh_token is not None and (not isinstance(refresh_token, str) or not refresh_token):
            raise OAuthError("INVALID_REFRESH_TOKEN", "refresh token must be a non-empty string")
        reference = f"secret://oauth/{tenant}/{connection}"
        version = self._versions.get(reference, 0) + 1
        self._values[reference] = json.dumps({"access": access_token, "refresh": refresh_token}, separators=(",", ":"))
        self._versions[reference] = version
        return {"secret_reference": reference, "secret_version": version}

    def read(self, *, secret_reference: str) -> dict[str, str | None]:
        value = self._values.get(secret_reference)
        if value is None:
            raise OAuthError("SECRET_NOT_FOUND", "secret reference is not available")
        return json.loads(value)

    def delete(self, *, secret_reference: str) -> None:
        self._values.pop(secret_reference, None)


class OAuthService:
    """State machine for authorization sessions and scope evidence."""

    def __init__(self, *, providers: Mapping[str, OAuthProvider] | None = None,
                 secret_manager: InMemorySecretManager | None = None) -> None:
        self.providers = dict(providers or {"fake": FakeOAuthProvider()})
        self.secret_manager = secret_manager or InMemorySecretManager()
        self.sessions: dict[tuple[str, str], OAuthAuthorizationSession] = {}
        self.evidence: dict[tuple[str, str], dict[str, Any]] = {}
        self.connections: dict[tuple[str, str], dict[str, Any]] = {}
        self._session_scopes: dict[tuple[str, str], tuple[str, ...]] = {}
        self.audit: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self._commands: dict[tuple[str, str], tuple[str, Any]] = {}
        self._lock = RLock()

    def create_session(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        provider: str, redirect_uri: str, pkce_challenge_value: str, requested_scopes: Sequence[str],
        ttl_seconds: int = 600, now: datetime | str | None = None,
    ) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        provider_obj = self.providers.get(provider)
        if provider_obj is None:
            raise OAuthError("PROVIDER_NOT_FOUND", "OAuth provider is not registered")
        redirect = _text(redirect_uri, "redirect_uri", 2048)
        challenge = _text(pkce_challenge_value, "pkce_challenge", 512)
        if len(challenge) < 43 or len(challenge) > 128 or any(ch.isspace() for ch in challenge):
            raise OAuthError("INVALID_PKCE_CHALLENGE", "PKCE challenge must contain 43-128 non-space characters")
        scopes = tuple(sorted({self._scope(scope) for scope in requested_scopes}))
        if not scopes or not set(scopes).issubset(provider_obj.allowed_scopes):
            raise OAuthError("SCOPE_NOT_ALLOWED", "requested scope is not in provider allowlist")
        if type(ttl_seconds) is not int or not 60 <= ttl_seconds <= 1800:
            raise OAuthError("INVALID_SESSION_TTL", "session TTL must be between 60 and 1800 seconds")
        at = _time(now, "now") or datetime.now(timezone.utc)
        state = _b64(secrets.token_bytes(32))
        digest = _hash({"operation": "create_session", "provider": provider, "redirect_uri": redirect,
                        "pkce_challenge": challenge, "scopes": scopes, "ttl_seconds": ttl_seconds})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            session = OAuthAuthorizationSession(
                id=uuid4(), org_id=UUID(tenant), provider=provider,
                state_hash=hashlib.sha256(state.encode("ascii")).hexdigest(),
                pkce_challenge=challenge, redirect_uri=redirect, status="created",
                expires_at=at + timedelta(seconds=ttl_seconds), created_at=at,
            )
            contract = session.as_contract()
            errors = sorted(_SESSION_VALIDATOR.iter_errors(contract), key=lambda error: list(error.path))
            if errors:
                raise OAuthError("INVALID_OAUTH_SESSION", errors[0].message)
            self.sessions[(tenant, str(session.id))] = session
            self._session_scopes[(tenant, str(session.id))] = scopes
            url = provider_obj.authorization_url(redirect_uri=redirect, state=state,
                                                  pkce_challenge=challenge, scopes=scopes)
            result = {"session": deepcopy(contract), "authorization_url": url, "state": state,
                      "requested_scopes": list(scopes), "side_effect_triggered": False}
            self._commands[(tenant, key)] = (digest, deepcopy(result))
            self._audit("oauth.session.created", tenant, actor, trace, key, digest, contract)
            self._event("oauth.authorization.started", tenant, actor, trace, key, contract, at)
            return deepcopy(result)

    def handle_callback(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        session_id: UUID | str, state: str, code: str, pkce_verifier: str,
        redirect_uri: str, now: datetime | str | None = None,
    ) -> dict[str, Any]:
        tenant, actor, identity = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id"), _uuid(session_id, "session_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        state_value, auth_code = _text(state, "state", 512), _text(code, "code", 512)
        redirect = _text(redirect_uri, "redirect_uri", 2048)
        at = _time(now, "now") or datetime.now(timezone.utc)
        session = self.sessions.get((tenant, identity))
        if session is None:
            raise OAuthError("OAUTH_SESSION_NOT_FOUND", "authorization session is not available")
        digest = _hash({"operation": "callback", "session_id": identity, "state_hash": hashlib.sha256(state_value.encode()).hexdigest(),
                        "code": auth_code, "pkce_verifier_hash": hashlib.sha256(pkce_verifier.encode()).hexdigest(),
                        "redirect_uri": redirect})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            if session.status != "created":
                raise OAuthError("OAUTH_SESSION_STATE_INVALID", "authorization session cannot receive another callback")
            if at >= session.expires_at:
                self._replace_session(session, "expired")
                raise OAuthError("OAUTH_SESSION_EXPIRED", "authorization session has expired")
            if not hmac.compare_digest(hashlib.sha256(state_value.encode("ascii")).hexdigest(), session.state_hash):
                raise OAuthError("CSRF_STATE_MISMATCH", "OAuth state does not match the authorization session")
            if redirect != session.redirect_uri:
                raise OAuthError("REDIRECT_URI_MISMATCH", "redirect URI does not match the authorization session")
            provider = self.providers[session.provider]
            # The provider sees only the one-time verifier and returns a local grant.
            requested_scopes = self._session_scopes[(tenant, identity)]
            grant = provider.exchange_code(code=auth_code, redirect_uri=redirect,
                                          pkce_verifier=pkce_verifier, expected_scopes=requested_scopes)
            if tuple(sorted(set(grant.scopes))) != requested_scopes:
                raise OAuthError("SCOPE_MISMATCH", "provider scopes differ from the authorization request")
            secret = self.secret_manager.put(org_id=tenant, connection_id=identity,
                                             access_token=grant.access_token, refresh_token=grant.refresh_token)
            updated_session = self._replace_session(session, "verified")
            evidence = {
                "id": str(uuid4()), "org_id": tenant, "account_connection_id": identity,
                "evidence_type": "oauth_consent", "external_reference": grant.external_account_id,
                "scope_snapshot": {"scopes": list(grant.scopes), "provider": session.provider},
                "captured_at": _stamp(at), "valid_until": _stamp(grant.expires_at) if grant.expires_at else None,
                "status": "verified",
            }
            errors = sorted(_EVIDENCE_VALIDATOR.iter_errors(evidence), key=lambda error: list(error.path))
            if errors:
                raise OAuthError("INVALID_AUTHORIZATION_EVIDENCE", errors[0].message)
            self.evidence[(tenant, evidence["id"])] = deepcopy(evidence)
            connection = {
                "id": identity, "org_id": tenant, "provider": session.provider,
                "external_account_id": grant.external_account_id, "secret_reference": secret["secret_reference"],
                "secret_version": secret["secret_version"], "scopes": list(grant.scopes),
                "authorization_status": "authorized", "connection_status": "pending",
            }
            self.connections[(tenant, identity)] = deepcopy(connection)
            result = {"session": updated_session.as_contract(), "authorization_evidence": deepcopy(evidence),
                      "connection": deepcopy(connection), "secret_reference": secret["secret_reference"],
                      "side_effect_triggered": False}
            self._commands[(tenant, key)] = (digest, deepcopy(result))
            self._audit("oauth.session.verified", tenant, actor, trace, key, digest,
                        {"session_id": identity, "evidence_id": evidence["id"], "secret_reference": secret["secret_reference"]})
            self._event("oauth.authorization.verified", tenant, actor, trace, key, updated_session.as_contract(), at)
            return deepcopy(result)

    def revoke(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        connection_id: UUID | str, reason: str, now: datetime | str | None = None,
    ) -> dict[str, Any]:
        tenant, actor, identity = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id"), _uuid(connection_id, "connection_id")
        trace, key, why = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200), _text(reason, "reason", 512)
        at = _time(now, "now") or datetime.now(timezone.utc)
        connection = self.connections.get((tenant, identity))
        if connection is None:
            raise OAuthError("CONNECTION_NOT_FOUND", "OAuth connection is not available")
        digest = _hash({"operation": "revoke", "connection_id": identity, "reason": why})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            provider = self.providers[connection["provider"]]
            provider.revoke(external_account_id=connection["external_account_id"],
                            secret_reference=connection["secret_reference"])
            self.secret_manager.delete(secret_reference=connection["secret_reference"])
            connection["authorization_status"] = "revoked"
            connection["connection_status"] = "revoked"
            connection["revoked_at"] = _stamp(at)
            connection["revocation_reason"] = why
            result = deepcopy(connection)
            self._commands[(tenant, key)] = (digest, deepcopy(result))
            self._audit("oauth.authorization.revoked", tenant, actor, trace, key, digest,
                        {"connection_id": identity, "reason": why, "secret_reference": connection["secret_reference"]})
            self._event("oauth.authorization.revoked", tenant, actor, trace, key,
                        {"id": identity, "version": 1}, at)
            return result

    @staticmethod
    def _scope(value: Any) -> str:
        if not isinstance(value, str) or not value or len(value) > 128 or any(ch.isspace() for ch in value):
            raise OAuthError("INVALID_SCOPE", "scope must be a non-empty token")
        return value

    def _replace_session(self, current: OAuthAuthorizationSession, status: str) -> OAuthAuthorizationSession:
        updated = OAuthAuthorizationSession(**{**current.__dict__, "status": status, "version": current.version + 1})
        self.sessions[(str(current.org_id), str(current.id))] = updated
        return updated

    def _prior(self, tenant: str, key: str, digest: str) -> Any | None:
        prior = self._commands.get((tenant, key))
        if prior is None:
            return None
        if prior[0] != digest:
            raise OAuthError("IDEMPOTENCY_KEY_REUSED", "OAuth command differs from the prior request")
        return deepcopy(prior[1])

    def _audit(self, event_type: str, tenant: str, actor: str, trace: str, key: str,
               digest: str, output: Mapping[str, Any]) -> None:
        self.audit.append({"event_type": event_type, "org_id": tenant, "actor_id": actor,
                           "trace_id": trace, "idempotency_key": key, "input_hash": digest,
                           "output_hash": _hash(output)})

    def _event(self, event_type: str, tenant: str, actor: str, trace: str, key: str,
               aggregate: Mapping[str, Any], occurred_at: datetime) -> None:
        aggregate_id = _uuid(aggregate.get("id"), "aggregate.id")
        payload = {"aggregate_id": aggregate_id, "aggregate_version": int(aggregate.get("version", 1)),
                   "from_state": None, "to_state": aggregate.get("status"), "command": event_type,
                   "snapshot_hash": _hash(aggregate), "reason": None}
        event = {"event_id": str(uuid4()), "event_type": event_type, "event_schema_version": 1,
                 "occurred_at": _stamp(occurred_at), "org_id": tenant, "trace_id": trace,
                 "aggregate_type": "OAuthAuthorizationSession", "aggregate_id": aggregate_id,
                 "aggregate_version": payload["aggregate_version"], "actor_type": "service", "actor_id": actor,
                 "idempotency_key": key, "payload": payload, "payload_hash": _hash(payload)}
        errors = sorted(_EVENT_VALIDATOR.iter_errors(event), key=lambda error: list(error.path))
        if errors:
            raise OAuthError("INVALID_OAUTH_EVENT", errors[0].message)
        self.events.append(deepcopy(event))


class TokenLeaseService:
    """Single-active-lease lifecycle backed by a Secret Manager reference."""

    def __init__(self, *, secret_manager: InMemorySecretManager | None = None) -> None:
        self.secret_manager = secret_manager or InMemorySecretManager()
        self.leases: dict[tuple[str, str, int], dict[str, Any]] = {}
        self.active: dict[tuple[str, str], str] = {}
        self.audit: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self._commands: dict[tuple[str, str], tuple[str, Any]] = {}
        self._lock = RLock()

    def issue(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
              connection_id: UUID | str, secret_reference: str, expires_at: datetime | str,
              now: datetime | str | None = None) -> dict[str, Any]:
        return self._transition(org_id=org_id, actor_id=actor_id, trace_id=trace_id,
                                idempotency_key=idempotency_key, connection_id=connection_id,
                                secret_reference=secret_reference, expires_at=expires_at,
                                action="issue", now=now)

    def rotate(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
               connection_id: UUID | str, secret_reference: str, expires_at: datetime | str,
               now: datetime | str | None = None) -> dict[str, Any]:
        return self._transition(org_id=org_id, actor_id=actor_id, trace_id=trace_id,
                                idempotency_key=idempotency_key, connection_id=connection_id,
                                secret_reference=secret_reference, expires_at=expires_at,
                                action="rotate", now=now)

    def expire(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
               connection_id: UUID | str, now: datetime | str | None = None) -> dict[str, Any]:
        return self._close(org_id=org_id, actor_id=actor_id, trace_id=trace_id,
                           idempotency_key=idempotency_key, connection_id=connection_id,
                           status="expired", now=now)

    def revoke(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
               connection_id: UUID | str, now: datetime | str | None = None) -> dict[str, Any]:
        return self._close(org_id=org_id, actor_id=actor_id, trace_id=trace_id,
                           idempotency_key=idempotency_key, connection_id=connection_id,
                           status="revoked", now=now)

    def get_active(self, *, org_id: UUID | str, connection_id: UUID | str) -> dict[str, Any] | None:
        tenant, connection = _uuid(org_id, "org_id"), _uuid(connection_id, "connection_id")
        identity = self.active.get((tenant, connection))
        return deepcopy(self._find(tenant, identity)) if identity else None

    def _transition(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
                    connection_id: UUID | str, secret_reference: str, expires_at: datetime | str,
                    action: str, now: datetime | str | None) -> dict[str, Any]:
        tenant, actor, connection = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id"), _uuid(connection_id, "connection_id")
        trace, key, reference = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200), _text(secret_reference, "secret_reference", 512)
        expiry, at = _time(expires_at, "expires_at", required=True), _time(now, "now") or datetime.now(timezone.utc)
        if expiry <= at:
            raise OAuthError("LEASE_EXPIRED", "token lease expiry must be in the future")
        if not reference.startswith("secret://"):
            raise OAuthError("INVALID_SECRET_REFERENCE", "token lease must point to Secret Manager")
        digest = _hash({"operation": action, "connection_id": connection, "secret_reference": reference, "expires_at": _stamp(expiry)})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            current_id = self.active.get((tenant, connection))
            if current_id:
                current = self._find(tenant, current_id)
                current["status"] = "expired" if current["expires_at"] <= _stamp(at) else "revoked"
            version = max((item["lease_version"] for (t, c, _), item in self.leases.items() if t == tenant and c == connection), default=0) + 1
            lease = {"id": str(uuid4()), "org_id": tenant, "account_connection_id": connection,
                     "secret_reference": reference, "lease_version": version, "status": "active",
                     "expires_at": _stamp(expiry), "created_at": _stamp(at)}
            errors = sorted(_LEASE_VALIDATOR.iter_errors(lease), key=lambda error: list(error.path))
            if errors:
                raise OAuthError("INVALID_TOKEN_LEASE", errors[0].message)
            self.leases[(tenant, connection, version)] = lease
            self.active[(tenant, connection)] = lease["id"]
            self._commands[(tenant, key)] = (digest, deepcopy(lease))
            self._audit(f"oauth.lease.{action}", tenant, actor, trace, key, digest, lease)
            self._event(f"oauth.token_lease.{action}", tenant, actor, trace, key, lease, at)
            return deepcopy(lease)

    def _close(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
               connection_id: UUID | str, status: str, now: datetime | str | None) -> dict[str, Any]:
        tenant, actor, connection = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id"), _uuid(connection_id, "connection_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        at = _time(now, "now") or datetime.now(timezone.utc)
        current_id = self.active.get((tenant, connection))
        current = self._find(tenant, current_id) if current_id else None
        if current is None:
            raise OAuthError("ACTIVE_LEASE_NOT_FOUND", "connection has no active token lease")
        digest = _hash({"operation": status, "connection_id": connection, "lease_id": current["id"]})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            current["status"] = status
            self.active.pop((tenant, connection), None)
            self._commands[(tenant, key)] = (digest, deepcopy(current))
            self._audit(f"oauth.lease.{status}", tenant, actor, trace, key, digest, current)
            self._event(f"oauth.token_lease.{status}", tenant, actor, trace, key, current, at)
            return deepcopy(current)

    def _find(self, tenant: str, lease_id: str | None) -> dict[str, Any] | None:
        if lease_id is None:
            return None
        for (scope, _, _), lease in self.leases.items():
            if scope == tenant and lease["id"] == lease_id:
                return lease
        return None

    def _prior(self, tenant: str, key: str, digest: str) -> Any | None:
        prior = self._commands.get((tenant, key))
        if prior is None:
            return None
        if prior[0] != digest:
            raise OAuthError("IDEMPOTENCY_KEY_REUSED", "token lease command differs from the prior request")
        return deepcopy(prior[1])

    def _audit(self, event_type: str, tenant: str, actor: str, trace: str, key: str,
               digest: str, output: Mapping[str, Any]) -> None:
        self.audit.append({"event_type": event_type, "org_id": tenant, "actor_id": actor,
                           "trace_id": trace, "idempotency_key": key, "input_hash": digest,
                           "output_hash": _hash(output), "secret_reference": output.get("secret_reference")})

    def _event(self, event_type: str, tenant: str, actor: str, trace: str, key: str,
               lease: Mapping[str, Any], occurred_at: datetime) -> None:
        payload = {"aggregate_id": lease["id"], "aggregate_version": lease["lease_version"],
                   "from_state": None, "to_state": lease["status"], "command": event_type,
                   "snapshot_hash": _hash(lease), "reason": None}
        event = {"event_id": str(uuid4()), "event_type": event_type, "event_schema_version": 1,
                 "occurred_at": _stamp(occurred_at), "org_id": tenant, "trace_id": trace,
                 "aggregate_type": "TokenLease", "aggregate_id": lease["id"],
                 "aggregate_version": lease["lease_version"], "actor_type": "service", "actor_id": actor,
                 "idempotency_key": key, "payload": payload, "payload_hash": _hash(payload)}
        errors = sorted(_EVENT_VALIDATOR.iter_errors(event), key=lambda error: list(error.path))
        if errors:
            raise OAuthError("INVALID_TOKEN_LEASE_EVENT", errors[0].message)
        self.events.append(deepcopy(event))


__all__ = [
    "FakeOAuthProvider", "InMemorySecretManager", "OAuthAuthorizationSession", "OAuthError",
    "OAuthGrant", "OAuthProvider", "OAuthService", "TokenLeaseService", "pkce_challenge",
]
