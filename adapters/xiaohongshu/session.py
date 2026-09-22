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
