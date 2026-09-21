"""Credential-free OAuth boundaries for Distribution.

The package deliberately exposes interfaces and deterministic fake services only.
Real providers can be plugged in later without changing the state machine or
the secret/lease contracts.
"""

from .service import (
    FakeOAuthProvider,
    InMemorySecretManager,
    OAuthAuthorizationSession,
    OAuthError,
    OAuthGrant,
    OAuthProvider,
    OAuthService,
    TokenLeaseService,
    pkce_challenge,
)

__all__ = [
    "FakeOAuthProvider",
    "InMemorySecretManager",
    "OAuthAuthorizationSession",
    "OAuthError",
    "OAuthGrant",
    "OAuthProvider",
    "OAuthService",
    "TokenLeaseService",
    "pkce_challenge",
]
