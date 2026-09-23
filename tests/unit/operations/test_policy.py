from __future__ import annotations

from datetime import datetime, timezone

import pytest

from modules.operations import OperationsPolicyError, OperationsPolicyStore


NOW = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)


def test_policy_defaults_are_conservative_and_persist(tmp_path):
    store = OperationsPolicyStore(tmp_path / "operations-policy.json")
    policy = store.get()
    assert policy["emergency_stop"] is False
    assert policy["default_limits"] == {"daily_publish": 3, "weekly_publish": 15}
    saved = store.replace({**policy, "default_limits": {"daily_publish": 2, "weekly_publish": 8}})
    assert saved["updated_at"]
    reloaded = OperationsPolicyStore(tmp_path / "operations-policy.json")
    assert reloaded.get()["default_limits"] == {"daily_publish": 2, "weekly_publish": 8}


def test_guard_resolves_console_account_name_and_blocks_limit(tmp_path):
    store = OperationsPolicyStore(tmp_path / "operations-policy.json")
    store.replace({
        "default_limits": {"daily_publish": 1, "weekly_publish": 4},
        "accounts": {"acct-1": {"enabled": True, "limits": {"daily_publish": 1, "weekly_publish": 4}}},
    })
    state = {
        "accounts": [{"id": "acct-1", "name": "试点账号"}],
        "contents": [{"status": "published", "account": "试点账号", "publishedAt": "2026-09-24T08:00:00Z"}],
    }
    result = store.guard(action="prepare_publish", account_key="acct-1", state=state, now=NOW)
    assert result["allowed"] is False
    assert result["counts"]["today"] == 1
    assert "今日发布上限" in result["reasons"][0]


def test_emergency_stop_blocks_reply_and_invalid_policy_is_rejected(tmp_path):
    store = OperationsPolicyStore(tmp_path / "operations-policy.json")
    store.update_stop(paused=True, reason="人工排查")
    result = store.guard(action="reply", account_key="acct-1", now=NOW)
    assert result["allowed"] is False
    assert result["emergency_stop"] is True
    with pytest.raises(OperationsPolicyError):
        store.replace({"default_limits": {"daily_publish": 5, "weekly_publish": 2}})


def test_browser_side_effects_are_disabled_even_when_stop_is_off(tmp_path):
    store = OperationsPolicyStore(tmp_path / "operations-policy.json")
    assert store.guard(action="publish", account_key="acct-1", now=NOW)["allowed"] is False
    assert store.guard(action="reply", account_key="acct-1", now=NOW)["allowed"] is False
    assert store.guard(action="prepare_publish", account_key="acct-1", now=NOW)["allowed"] is True
