from uuid import uuid4

import pytest

from infra.foundation.platform_contracts import Platform, PlatformContractError, PlatformRegistry


def platform(key="fake.official", **changes):
    values = {
        "id": str(uuid4()), "key": key, "display_name": "Synthetic Official",
        "kind": "fake", "status": "active", "policy_ref": "policy://synthetic/v1",
        "adapter_key": "fake.official",
    }
    return Platform(**{**values, **changes})


def test_registry_is_sorted_read_only_and_resolves_key_or_id():
    later = platform("fake.z")
    earlier = platform("fake.a")
    registry = PlatformRegistry([later, earlier])
    assert registry.get(earlier.id) == earlier
    assert registry.get("fake.z") == later
    assert registry.list() == (earlier, later)


def test_registry_rejects_duplicate_or_unknown_entries():
    item = platform()
    with pytest.raises(PlatformContractError, match="unique"):
        PlatformRegistry([item, Platform(**{**item.as_contract(), "key": "fake.other"})])
    with pytest.raises(PlatformContractError, match="not registered"):
        PlatformRegistry([item]).get("missing")


@pytest.mark.parametrize("changes", [
    {"key": "UPPER"}, {"kind": "fake", "adapter_key": None},
    {"kind": "unknown"}, {"status": "planned"}, {"display_name": " "},
])
def test_platform_rejects_invalid_registry_values(changes):
    with pytest.raises(PlatformContractError):
        platform(**changes)
