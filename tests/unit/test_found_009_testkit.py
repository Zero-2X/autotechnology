from datetime import datetime, timedelta, timezone

import pytest

from packages.testkit import FakeClock, FixtureIdentity, FixtureValidationError


START = datetime(2026, 9, 18, 9, 0, tzinfo=timezone.utc)


def test_fake_clock_is_callable_and_advances_without_wall_time() -> None:
    clock = FakeClock(START)
    assert clock() == START
    assert clock.advance(2.5) == START + timedelta(seconds=2.5)
    clock.sleep(7.5)
    assert clock.now() == START + timedelta(seconds=10)
    assert clock.as_contract() == "2026-09-18T09:00:10.000000Z"


def test_fake_clock_accepts_forward_set_and_rejects_invalid_or_backward_time() -> None:
    clock = FakeClock(START)
    assert clock.set(START + timedelta(days=1)) == START + timedelta(days=1)
    with pytest.raises(FixtureValidationError, match="backwards"):
        clock.set(START)
    for invalid in (-1, float("inf"), True):
        with pytest.raises(FixtureValidationError):
            clock.advance(invalid)
    with pytest.raises(FixtureValidationError, match="timezone-aware"):
        FakeClock(datetime(2026, 9, 18))


def test_fixture_identity_is_stable_complete_and_does_not_expose_seed() -> None:
    first = FixtureIdentity.from_seed("tenant-scenario-a")
    second = FixtureIdentity.from_seed("tenant-scenario-a")
    other = FixtureIdentity.from_seed("tenant-scenario-b")
    assert first == second
    assert first != other
    assert first.context.as_dict() == {
        "trace_id": first.trace_id,
        "request_id": first.request_id,
        "org_id": first.org_id,
        "actor_id": first.actor_id,
    }
    assert "tenant-scenario-a" not in str(first.as_contract())


@pytest.mark.parametrize("seed", ["", "   ", "x" * 257, None])
def test_fixture_identity_rejects_invalid_seed(seed) -> None:
    with pytest.raises(FixtureValidationError):
        FixtureIdentity.from_seed(seed)
