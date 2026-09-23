from __future__ import annotations

from datetime import datetime, timedelta, timezone
from jsonschema import Draft202012Validator, FormatChecker
import json
from pathlib import Path

import pytest

from modules.operations import PilotRunError, PilotRunStore


def _payload() -> dict:
    now = datetime.now(timezone.utc)
    return {
        "name": "单账号安全试点",
        "start_at": now.isoformat(),
        "end_at": (now + timedelta(days=14)).isoformat(),
        "owner": "运营负责人",
        "backup": "审核负责人",
        "account_keys": ["acct-1"],
        "publish_limits": {"daily_publish": 2, "weekly_publish": 8},
        "stop_conditions": ["出现版权投诉", "平台提示异常登录"],
    }


def test_pilot_run_persists_contract_and_schedule(tmp_path):
    store = PilotRunStore(tmp_path / "pilot-runs.json")
    created = store.create(_payload())
    assert created["status"] == "planned"
    assert created["publish_limits"] == {"daily_publish": 2, "weekly_publish": 8}
    started = store.transition(created["id"], "running")
    assert started["status"] == "running"
    item = store.add_item(created["id"], {
        "title": "首篇内容",
        "account_key": "acct-1",
        "scheduled_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
    })
    assert len(item["items"]) == 1
    reloaded = PilotRunStore(tmp_path / "pilot-runs.json")
    assert reloaded.get(created["id"])["items"][0]["title"] == "首篇内容"


def test_pilot_requires_stop_condition_and_reason(tmp_path):
    store = PilotRunStore(tmp_path / "pilot-runs.json")
    payload = _payload()
    payload["stop_conditions"] = []
    with pytest.raises(PilotRunError) as error:
        store.create(payload)
    assert error.value.code == "INVALID_PILOT_RUN"
    created = store.create(_payload())
    with pytest.raises(PilotRunError) as error:
        store.transition(created["id"], "stopped")
    assert error.value.code == "STOP_REASON_REQUIRED"


def test_pilot_contract_matches_schema(tmp_path):
    store = PilotRunStore(tmp_path / "pilot-runs.json")
    created = store.create(_payload())
    schema = json.loads((Path(__file__).resolve().parents[3] / "packages/contracts/jsonschema/pilot-run.schema.json").read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(store.summary(created["id"])["contract"]))
    assert errors == []
