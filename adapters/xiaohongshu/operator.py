"""Launch operator-owned Xiaohongshu browser sessions from the local API."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
from uuid import uuid4

from adapters.xiaohongshu.session import session_dir
from modules.media.local_demo_generator import DemoContent, generate_cover_png


TARGETS = {"home", "inbox", "publish"}


def launch_operator_session(
    account_key: str,
    *,
    target: str,
    content: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Start a headed browser without returning credentials or waiting for it."""
    project_root = root or Path(__file__).resolve().parents[2]
    session_dir(account_key, project_root / ".local" / "browser-accounts")
    if target not in TARGETS:
        raise ValueError("target must be home, inbox, or publish")

    job_id = f"xhs-{uuid4().hex[:12]}"
    job_path: Path | None = None
    if target == "publish":
        payload = content or {}
        title = str(payload.get("title", "")).strip()
        body = str(payload.get("body", "")).strip()
        hashtags = tuple(str(item).strip() for item in payload.get("hashtags", []) if str(item).strip())
        if not title or not body:
            raise ValueError("publish preview requires title and body")
        queue_dir = project_root / ".local" / "xhs-jobs" / job_id
        queue_dir.mkdir(parents=True, exist_ok=True)
        cover_path = generate_cover_png(DemoContent(title, body, hashtags), queue_dir / "cover.png")
        job_path = queue_dir / "job.json"
        job_path.write_text(
            json.dumps(
                {"job_id": job_id, "account_key": account_key, "title": title,
                 "body": body, "hashtags": list(hashtags), "cover_path": str(cover_path.resolve())},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    command = [sys.executable, str(project_root / "scripts" / "open-xhs-session.py"),
               "--account-key", account_key, "--target", target]
    if job_path is not None:
        command.extend(["--job", str(job_path.resolve())])
    creation_flags = 0
    if os.name == "nt":
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    process = subprocess.Popen(
        command,
        cwd=project_root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )
    result = {
        "job_id": job_id,
        "account_key": account_key,
        "target": target,
        "status": "browser_starting",
        "pid": process.pid,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "publishes_automatically": False,
    }
    launch_dir = project_root / ".local" / "xhs-launches"
    launch_dir.mkdir(parents=True, exist_ok=True)
    (launch_dir / f"{job_id}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result
