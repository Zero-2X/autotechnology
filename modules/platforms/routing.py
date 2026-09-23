"""Choose an official API, browser session, or manual export per account.

The router does not infer permissions from a platform name. An API route is
selected only when the account has an explicit approved capability snapshot;
otherwise a platform-specific browser adapter may be used when the operator
has a logged-in session.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, FrozenSet


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


# This catalog describes what a platform may offer officially.  It is kept
# separate from ``PlatformProfile.api_actions`` on purpose: an official API
# can exist while this workspace still has no approved credentials or adapter
# for a particular account.  The router therefore continues to choose
# ``manual_export`` until an account capability snapshot is supplied.
PLATFORM_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "platform": "小红书",
        "official_api_actions": (),
        "current_adapter_actions": (),
        "message_mode": "manual_import",
        "status": "browser_session_only",
        "summary": "当前只确认本机创作者中心会话；发布、评论读取和私信回复未获官方权限。",
        "docs": (
            ("权限说明", "https://openaccount.xiaohongshu.com/docs/scope"),
            ("API 参考", "https://openaccount.xiaohongshu.com/docs/api-reference"),
        ),
    },
    {
        "platform": "YouTube",
        "official_api_actions": ("publish", "inbox", "comment_reply"),
        "current_adapter_actions": (),
        "message_mode": "official_api_or_manual_import",
        "status": "official_api_possible",
        "summary": "官方接口支持上传视频、读取评论和回复；需要 Google OAuth、配额和项目审核条件。",
        "docs": (
            ("上传视频", "https://developers.google.com/youtube/v3/docs/videos/insert"),
            ("评论接口", "https://developers.google.com/youtube/v3/docs/commentThreads"),
        ),
    },
    {
        "platform": "TikTok",
        "official_api_actions": ("publish",),
        "current_adapter_actions": (),
        "message_mode": "manual_import",
        "status": "official_api_possible",
        "summary": "Content Posting API 需要 video.publish、账号授权和平台审核；评论/私信不在当前适配器中。",
        "docs": (
            ("接入条件", "https://developers.tiktok.com/docs/en/content-posting-api-get-started"),
            ("发布接口", "https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post"),
        ),
    },
    {
        "platform": "Instagram",
        "official_api_actions": ("publish", "comment_reply"),
        "current_adapter_actions": (),
        "message_mode": "official_api_or_manual_import",
        "status": "official_api_possible",
        "summary": "专业账号可以申请内容和评论能力；需要 Meta 应用、权限审核及账号授权。",
        "docs": (("Meta API 文档", "https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api"),),
    },
    {
        "platform": "LinkedIn",
        "official_api_actions": ("publish", "comment_reply"),
        "current_adapter_actions": (),
        "message_mode": "official_api_or_manual_import",
        "status": "official_api_possible",
        "summary": "组织内容和评论能力受组织管理员角色及开发者权限限制；当前尚未连接应用。",
        "docs": (("评论接口与权限", "https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/comments-api"),),
    },
    {
        "platform": "抖音",
        "official_api_actions": (),
        "current_adapter_actions": (),
        "message_mode": "manual_import",
        "status": "not_configured",
        "summary": "当前没有经过验证的官方适配器；使用官方页面人工发布和导入消息。",
        "docs": (),
    },
    {
        "platform": "微博",
        "official_api_actions": (),
        "current_adapter_actions": (),
        "message_mode": "manual_import",
        "status": "not_configured",
        "summary": "当前没有经过验证的官方适配器；使用官方页面人工发布和导入消息。",
        "docs": (),
    },
    {
        "platform": "Bilibili",
        "official_api_actions": (),
        "current_adapter_actions": (),
        "message_mode": "manual_import",
        "status": "not_configured",
        "summary": "当前没有经过验证的官方适配器；使用官方页面人工发布和导入消息。",
        "docs": (),
    },
    {
        "platform": "微信公众号",
        "official_api_actions": (),
        "current_adapter_actions": (),
        "message_mode": "manual_import",
        "status": "not_configured",
        "summary": "当前没有经过验证的官方适配器；使用官方页面人工发布和导入消息。",
        "docs": (),
    },
)


def platform_catalog() -> list[dict[str, Any]]:
    """Return JSON-safe copies for the console capability matrix."""
    return [
        {
            **item,
            "official_api_actions": list(item["official_api_actions"]),
            "current_adapter_actions": list(item["current_adapter_actions"]),
            "docs": [{"label": label, "url": url} for label, url in item["docs"]],
        }
        for item in PLATFORM_CATALOG
    ]


def profile_for(platform: str) -> PlatformProfile:
    """Return only explicitly registered platform capabilities.

    An unknown platform must not inherit fictional API or browser support just
    because the account claims to be authorized or logged in.
    """
    if platform == "小红书":
        return XHS_PROFILE
    return PlatformProfile(platform=platform)


__all__ = [
    "DeliveryRoute", "PlatformProfile", "XHS_PROFILE", "PLATFORM_CATALOG",
    "platform_catalog", "profile_for", "resolve_delivery_route",
]
