"""Choose an official API, browser session, or manual export per account.

The router does not infer permissions from a platform name.  An API route is
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
    return DeliveryRoute(profile.platform, action, "manual_export", "no approved API or logged-in browser capability")


XHS_PROFILE = PlatformProfile(
    platform="小红书",
    api_actions=frozenset(),
    browser_actions=frozenset({"publish", "inbox", "comment_reply", "message_reply"}),
)


def profile_for(platform: str) -> PlatformProfile:
    """Return a conservative profile for the first supported platform set."""
    if platform == "小红书":
        return XHS_PROFILE
    # Other platforms can opt into API actions only after their account has an
    # approved capability snapshot. Browser fallback remains explicit.
    return PlatformProfile(
        platform=platform,
        api_actions=frozenset({"publish", "inbox", "comment_reply", "message_reply"}),
        browser_actions=frozenset({"publish", "inbox", "comment_reply", "message_reply"}),
    )


__all__ = ["DeliveryRoute", "PlatformProfile", "XHS_PROFILE", "profile_for", "resolve_delivery_route"]
