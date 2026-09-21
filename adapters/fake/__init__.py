"""Account-free deterministic adapter implementations."""

from .official_server import FakePlatformError, FakeOfficialServer

__all__ = ["FakeOfficialServer", "FakePlatformError"]
