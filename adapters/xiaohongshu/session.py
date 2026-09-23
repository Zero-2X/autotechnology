"""Local, non-secret status for an operator-managed Xiaohongshu session."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import psutil
except ImportError:  # pragma: no cover - optional on minimal installs
    psutil = None


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


def _browser_process_running(account_key: str, root: Path) -> bool:
    """Detect the dedicated Chromium process without reading cookies or tokens."""
    if psutil is None:
        return False
    marker = str(session_dir(account_key, root)).lower().replace('/', '\\')
    try:
        for process in psutil.process_iter(['name']):
            try:
                name = str(process.info.get('name') or '').lower()
                if 'chrome' not in name:
                    continue
                command = ' '.join(process.cmdline()).lower().replace('/', '\\')
            except (OSError, psutil.Error):
                # Windows commonly denies command-line inspection for unrelated
                # protected processes. Keep checking instead of returning a false
                # "browser closed" result for the account we are looking for.
                continue
            if 'chrome' in name and '--type=' not in command and f'--user-data-dir={marker}' in command:
                return True
    except (OSError, psutil.Error):
        return False
    return False


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
    browser_running = _browser_process_running(account_key, directory.parent)
    checks['browser_process'] = {'ok': browser_running, 'label': '独立浏览器进程'}
    if not profile_exists:
        next_step = '先点击“打开账号”，在弹出的创作者中心完成登录。'
    elif status.get('status') == 'login_required':
        next_step = '请在本工作流打开的小红书专用窗口重新扫码或登录；普通浏览器的登录状态不会共享。回到创作者中心后再重试。'
    elif status.get('status') == 'connected' and not browser_running:
        next_step = '登录记录仍在，但独立浏览器窗口已关闭；请点击“打开账号”重新启动会话。'
    elif status.get('status') == 'connected':
        next_step = '会话可用；如果发布仍失败，请关闭同账号的其他浏览器窗口后重试。'
    else:
        next_step = '先打开账号会话，等待后台记录登录状态。'
    return {
        'account_key': account_key,
        'status': status.get('status', 'pending'),
        'profile_directory': str(directory.resolve()),
        'session_file_exists': session_exists,
        'browser_running': browser_running,
        'connected_at': status.get('connected_at'),
        'url': status.get('url'),
        'checks': checks,
        'next_step': next_step,
    }
