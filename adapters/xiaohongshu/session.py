"""Local, non-secret status for an operator-managed Xiaohongshu session."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def session_dir(account_key: str, root: Path | None = None) -> Path:
    if not account_key or any(ch in account_key for ch in '\\/:*?"<>|'):
        raise ValueError('invalid account_key')
    base = root or Path(__file__).resolve().parents[2] / '.local' / 'browser-accounts'
    return base / account_key


def write_session_status(account_key: str, *, url: str, root: Path | None = None) -> dict[str, Any]:
    payload = {
        'account_key': account_key,
        'url': url,
        'connected_at': datetime.now(timezone.utc).isoformat(),
        'publish_performed': False,
    }
    directory = session_dir(account_key, root)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'session.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload


def read_session_status(account_key: str, root: Path | None = None) -> dict[str, Any]:
    path = session_dir(account_key, root) / 'session.json'
    if not path.exists():
        return {'account_key': account_key, 'status': 'pending', 'publish_performed': False}
    payload = json.loads(path.read_text(encoding='utf-8'))
    url = str(payload.get('url', ''))
    status = 'login_required' if '/login' in url else 'connected'
    return {'status': status, **payload}


def diagnose_session(account_key: str, root: Path | None = None) -> dict[str, Any]:
    """Return safe, operator-facing diagnostics without exposing cookies."""
    directory = session_dir(account_key, root)
    session_file = directory / 'session.json'
    status = read_session_status(account_key, root)
    profile_exists = directory.exists()
    session_exists = session_file.exists()
    checks = {
        'profile_directory': {'ok': profile_exists, 'label': '账号浏览器目录'},
        'session_file': {'ok': session_exists, 'label': '登录会话记录'},
        'login_state': {'ok': status.get('status') == 'connected', 'label': '小红书登录状态'},
    }
    if not profile_exists:
        next_step = '先点击“打开账号”，在弹出的创作者中心完成登录。'
    elif status.get('status') == 'login_required':
        next_step = '登录已失效，请在小红书窗口重新扫码或登录后再重试。'
    elif status.get('status') == 'connected':
        next_step = '会话可用；如果发布仍失败，请关闭同账号的其他浏览器窗口后重试。'
    else:
        next_step = '先打开账号会话，等待后台记录登录状态。'
    return {
        'account_key': account_key,
        'status': status.get('status', 'pending'),
        'profile_directory': str(directory.resolve()),
        'session_file_exists': session_exists,
        'connected_at': status.get('connected_at'),
        'url': status.get('url'),
        'checks': checks,
        'next_step': next_step,
    }
