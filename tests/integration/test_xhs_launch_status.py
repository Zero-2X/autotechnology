from unittest.mock import Mock

import pytest

from adapters.xiaohongshu import operator
from adapters.xiaohongshu.session import read_session_status, write_session_status


def test_busy_profile_does_not_claim_to_prepare_a_draft(monkeypatch, tmp_path):
    monkeypatch.setattr(operator, "_existing_profile_pid", lambda profile: 123)
    spawn = Mock()
    monkeypatch.setattr(operator.subprocess, "Popen", spawn)
    with pytest.raises(ValueError, match="尚未填稿"):
        operator.launch_operator_session(
            "account-1", target="publish",
            content={"title": "标题", "body": "正文"}, root=tmp_path,
        )
    spawn.assert_not_called()
    assert not (tmp_path / ".local" / "xhs-jobs").exists()


def test_existing_window_returns_reuse_status(monkeypatch, tmp_path):
    monkeypatch.setattr(operator, "_existing_profile_pid", lambda profile: 123)
    result = operator.launch_operator_session("account-1", target="home", root=tmp_path)
    assert result["reused_existing"] is True
    assert result["publishes_automatically"] is False
    assert operator.read_launch_status(result["job_id"], tmp_path) == result


def test_login_page_is_not_reported_as_connected(tmp_path):
    write_session_status("account-1", url="https://creator.xiaohongshu.com/login", root=tmp_path)
    assert read_session_status("account-1", tmp_path)["status"] == "login_required"
