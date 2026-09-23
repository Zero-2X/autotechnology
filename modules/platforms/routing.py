"""Choose an official API, browser session, or manual export per account.

The router does not infer permissions from a platform name. An API route is
selected only when the account has an explicit approved capability snapshot;
otherwise a platform-specific browser adapter may be used when the operator
has a logged-in session.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet


@dataclass(frozen=True)
class PlatformProfile:
    platform: str
    api_actions: FrozenSet[str] = frozenset()
    browser_actions: FrozenSet[str] = frozenset()
    api_requires_approval: bool = True


@dataclass(frozen=True)
class DeliveryRoute:
    platform: str
    action: str
    mode: str
    reason: str


def resolve_delivery_route(*, profile: PlatformProfile, action: str,
                           api_authorized: bool = False,
                           browser_session_ready: bool = False,
                           prefer_api: bool = True) -> DeliveryRoute:
    """Return an explicit route; never treat an unapproved API as available."""
    if prefer_api and api_authorized and action in profile.api_actions:
        return DeliveryRoute(profile.platform, action, "authorized_api", "approved account capability")
    if browser_session_ready and action in profile.browser_actions:
        reason = "official API approval is required" if action not in profile.api_actions else "API capability is not enabled for this account"
        return DeliveryRoute(profile.platform, action, "browser_automation", reason)
    if action not in profile.api_actions and action not in profile.browser_actions:
        reason = "platform action has no registered adapter"
    elif action in profile.api_actions and not api_authorized:
        reason = "API capability is not approved for this account"
    else:
        reason = "no logged-in browser session is available"
    return DeliveryRoute(profile.platform, action, "manual_export", reason)


XHS_PROFILE = PlatformProfile(
    platform="小红书",
    api_actions=frozenset(),
    # A creator-center login is not permission to publish, scan an inbox, or send replies.
    browser_actions=frozenset(),
)


def profile_for(platform: str) -> PlatformProfile:
    """Return only explicitly registered platform capabilities.

    An unknown platform must not inherit fictional API or browser support just
    because the account claims to be authorized or logged in.
    """
    if platform == "小红书":
        return XHS_PROFILE
    return PlatformProfile(platform=platform)


__all__ = ["DeliveryRoute", "PlatformProfile", "XHS_PROFILE", "profile_for", "resolve_delivery_route"]
