from modules.platforms.routing import XHS_PROFILE, profile_for, resolve_delivery_route


def test_xhs_uses_browser_when_api_is_not_available():
    route = resolve_delivery_route(profile=XHS_PROFILE, action="publish", browser_session_ready=True)
    assert route.mode == "browser_automation"
    assert "API" in route.reason


def test_unregistered_platform_does_not_claim_api_support():
    route = resolve_delivery_route(profile=profile_for("YouTube"), action="publish",
                                   api_authorized=True, browser_session_ready=True)
    assert route.mode == "manual_export"
    assert route.reason == "platform action has no registered adapter"


def test_registered_api_capability_uses_approved_api_first():
    from modules.platforms.routing import PlatformProfile

    profile = PlatformProfile(platform="Example", api_actions=frozenset({"publish"}))
    route = resolve_delivery_route(profile=profile, action="publish", api_authorized=True)
    assert route.mode == "authorized_api"


def test_unregistered_platform_does_not_claim_browser_support():
    route = resolve_delivery_route(profile=profile_for("Instagram"), action="message_reply",
                                   browser_session_ready=True)
    assert route.mode == "manual_export"
    assert route.reason == "platform action has no registered adapter"


def test_missing_capabilities_go_to_manual_export():
    route = resolve_delivery_route(profile=XHS_PROFILE, action="message_reply")
    assert route.mode == "manual_export"
