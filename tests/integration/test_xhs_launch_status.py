from unittest.mock import Mock

import pytest

from adapters.xiaohongshu import operator
from adapters.xiaohongshu.session import diagnose_session, read_session_status, write_session_status


def test_busy_profile_does_not_claim_to_prepare_a_draft(monkeypatch, tmp_path):
    monkeypatch.setattr(operator, "_existing_profile_pid", lambda profile: 123)
    monkeypatch.setattr(operator, "_session_runner_is_current", lambda pid, script_path: False)
    spawn = Mock()
    monkeypatch.setattr(operator.subprocess, "Popen", spawn)
    with pytest.raises(ValueError, match="旧版小红书流程"):
        operator.launch_operator_session(
            "account-1", target="publish",
            content={"title": "标题", "body": "正文"}, root=tmp_path,
        )
    spawn.assert_not_called()
    assert not (tmp_path / ".local" / "xhs-jobs").exists()


def test_current_busy_profile_queues_publish_job(monkeypatch, tmp_path):
    monkeypatch.setattr(operator, "_existing_profile_pid", lambda profile: 123)
    monkeypatch.setattr(operator, "_session_runner_is_current", lambda pid, script_path: True)
    result = operator.launch_operator_session(
        "account-1", target="publish",
        content={"title": "标题", "body": "正文"}, root=tmp_path,
    )
    assert result["status"] == "command_queued"
    assert result["reused_existing"] is True
    assert operator.read_launch_status(result["job_id"], tmp_path) == result
    queue = (tmp_path / ".local" / "xhs-commands" / "account-1.jsonl").read_text(encoding="utf-8")
    assert '"target": "publish"' in queue
    assert result["job_id"] in queue


def test_busy_profile_queues_reply_command(monkeypatch, tmp_path):
    monkeypatch.setattr(operator, "_existing_profile_pid", lambda profile: 123)
    monkeypatch.setattr(operator, "_session_runner_is_current", lambda pid, script_path: True)
    result = operator.launch_operator_session(
        "account-1", target="inbox",
        content={"message_id": "msg-1", "reply": "回复", "risk": "low", "send": True}, root=tmp_path,
    )
    assert result["status"] == "command_queued"


def test_high_risk_reply_is_rejected_before_browser_work(monkeypatch, tmp_path):
    monkeypatch.setattr(operator, "_existing_profile_pid", lambda profile: None)
    spawn = Mock()
    monkeypatch.setattr(operator.subprocess, "Popen", spawn)
    with pytest.raises(ValueError, match="only low-risk"):
        operator.launch_operator_session(
            "account-1", target="inbox",
            content={"message_id": "msg-1", "reply": "转人工", "risk": "high", "send": True},
            root=tmp_path,
        )
    spawn.assert_not_called()
    assert not (tmp_path / ".local" / "xhs-jobs").exists()


def test_reply_send_flag_requires_json_boolean(monkeypatch, tmp_path):
    monkeypatch.setattr(operator, "_existing_profile_pid", lambda profile: None)
    spawn = Mock()
    monkeypatch.setattr(operator.subprocess, "Popen", spawn)
    with pytest.raises(ValueError, match="must be a boolean"):
        operator.launch_operator_session(
            "account-1", target="inbox",
            content={"message_id": "msg-1", "reply": "回复", "risk": "low", "send": "false"},
            root=tmp_path,
        )
    spawn.assert_not_called()
    assert not (tmp_path / ".local" / "xhs-jobs").exists()


def test_existing_window_returns_reuse_status(monkeypatch, tmp_path):
    monkeypatch.setattr(operator, "_existing_profile_pid", lambda profile: 123)
    result = operator.launch_operator_session("account-1", target="home", root=tmp_path)
    assert result["reused_existing"] is True
    assert result["publishes_automatically"] is False
    assert operator.read_launch_status(result["job_id"], tmp_path) == result


def test_publish_route_stays_manual_until_capability_is_verified(monkeypatch, tmp_path):
    monkeypatch.setattr(operator, "_existing_profile_pid", lambda profile: None)
    monkeypatch.setattr(operator.subprocess, "Popen", lambda *args, **kwargs: Mock(pid=123))
    result = operator.launch_operator_session(
        "account-1", target="publish", content={"title": "标题", "body": "正文"}, root=tmp_path,
    )
    assert result["delivery_mode"] == "manual_export"
    assert "registered adapter" in result["delivery_reason"]


def test_existing_window_queues_inbox_command(monkeypatch, tmp_path):
    monkeypatch.setattr(operator, "_existing_profile_pid", lambda profile: 123)
    monkeypatch.setattr(operator, "_session_runner_is_current", lambda pid, script_path: True)
    result = operator.launch_operator_session("account-1", target="inbox", root=tmp_path)
    assert result["status"] == "command_queued"
    queue = (tmp_path / ".local" / "xhs-commands" / "account-1.jsonl").read_text(encoding="utf-8")
    assert '"target": "inbox"' in queue


def test_old_inbox_worker_is_rejected_before_job_creation(monkeypatch, tmp_path):
    monkeypatch.setattr(operator, "_existing_profile_pid", lambda profile: 123)
    monkeypatch.setattr(operator, "_session_runner_is_current", lambda pid, script_path: False)
    with pytest.raises(ValueError, match="旧版小红书流程"):
        operator.launch_operator_session("account-1", target="inbox", root=tmp_path)
    assert not (tmp_path / ".local" / "xhs-jobs").exists()


def test_login_page_is_not_reported_as_connected(tmp_path):
    write_session_status("account-1", url="https://creator.xiaohongshu.com/login", root=tmp_path)
    assert read_session_status("account-1", tmp_path)["status"] == "login_required"


def test_diagnostics_explain_missing_login_without_secrets(tmp_path):
    result = diagnose_session("account-1", tmp_path)
    assert result["status"] == "pending"
    assert result["checks"]["login_state"]["ok"] is False
    assert "登录" in result["next_step"]
    assert "cookie" not in result


def test_diagnostics_report_connected_session(tmp_path):
    write_session_status("account-1", url="https://creator.xiaohongshu.com/", root=tmp_path)
    result = diagnose_session("account-1", tmp_path)
    assert result["status"] == "connected"
    assert result["checks"]["login_state"]["ok"] is True
    assert result["session_file_exists"] is True
