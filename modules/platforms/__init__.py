"""Platform capability and delivery routing domain helpers."""

from .routing import (
    DeliveryRoute,
    PlatformProfile,
    PLATFORM_CATALOG,
    XHS_PROFILE,
    platform_catalog,
    profile_for,
    resolve_delivery_route,
)

__all__ = [
    "DeliveryRoute", "PlatformProfile", "PLATFORM_CATALOG", "XHS_PROFILE",
    "platform_catalog", "profile_for", "resolve_delivery_route",
]
