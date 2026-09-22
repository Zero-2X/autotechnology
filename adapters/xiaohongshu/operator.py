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

try:
    import psutil
except ImportError:  # pragma: no cover - optional on minimal installs
    psutil = None

from adapters.xiaohongshu.session import session_dir
from modules.media.local_demo_generator import DemoContent, generate_cover_png
from adapters.platforms.routing import profile_for, resolve_delivery_route


TARGETS = {"home", "inbox", "publish"}


def _existing_profile_pid(profile: Path) -> int | None:
    """Find an already running Playwright browser using this profile."""
    if psutil is None:
        return None
    marker = str(profile.resolve()).lower().replace("/", "\\")
    try:
        for process in psutil.process_iter(["pid", "name", "cmdline"]):
            cmdline = " ".join(process.info.get("cmdline") or []).lower().replace("/", "\\")
            if "chrome" in str(process.info.get("name", "")).lower() and "--type=" not in cmdline and f"--user-data-dir={marker}" in cmdline:
                return int(process.info["pid"])
    except (OSError, psutil.Error):
        return None
    return None


def launch_status_path(job_id: str, root: Path | None = None) -> Path:
    if not job_id or any(ch in job_id for ch in '\\/:*?"<>|'):
        raise ValueError("invalid launch job id")
    project_root = root or Path(__file__).resolve().parents[2]
    return project_root / ".local" / "xhs-launches" / f"{job_id}.json"


def read_launch_status(job_id: str, root: Path | None = None) -> dict[str, Any]:
    path = launch_status_path(job_id, root)
    if not path.exists():
        raise FileNotFoundError("launch job not found")
    return json.loads(path.read_text(encoding="utf-8"))


def launch_operator_session(
    account_key: str,
    *,
    target: str,
    content: dict[str, Any] | None = None,
    auto_publish: bool = False,
    root: Path | None = None,
) -> dict[str, Any]:
    """Start a headed browser without returning credentials or waiting for it."""
    project_root = root or Path(__file__).resolve().parents[2]
    profile = session_dir(account_key, project_root / ".local" / "browser-accounts")
    if target not in TARGETS:
        raise ValueError("target must be home, inbox, or publish")
    if auto_publish and target != "publish":
        raise ValueError("auto_publish is only valid for publish target")
    if target == "publish" and not content:
        raise ValueError("publish preview requires title and body")

    existing_pid = _existing_profile_pid(profile)
    if existing_pid and target == "publish":
        raise ValueError("该账号的小红书窗口已打开。请先保存未完成的内容并关闭该窗口，再准备新草稿；本次尚未填稿或发布。")
    if existing_pid and target == "inbox" and content and content.get("reply"):
        raise ValueError("该账号的小红书窗口已打开。请先关闭该窗口，再执行受控客服回复；本次尚未发送。")

    job_id = f"xhs-{uuid4().hex[:12]}"
    job_path: Path | None = None
    if target in {"publish", "inbox"} and content:
        payload = content or {}
        queue_dir = project_root / ".local" / "xhs-jobs" / job_id
        queue_dir.mkdir(parents=True, exist_ok=True)
        job_path = queue_dir / "job.json"
        if target == "publish":
            title = str(payload.get("title", "")).strip()
            body = str(payload.get("body", "")).strip()
            hashtags = tuple(str(item).strip() for item in payload.get("hashtags", []) if str(item).strip())
            if not title or not body:
                raise ValueError("publish preview requires title and body")
            cover_path = generate_cover_png(DemoContent(title, body, hashtags), queue_dir / "cover.png")
            payload = {"job_id": job_id, "account_key": account_key, "title": title,
                       "body": body, "hashtags": list(hashtags), "cover_path": str(cover_path.resolve())}
        else:
            message_id = str(payload.get("message_id", "")).strip()
            reply = str(payload.get("reply", "")).strip()
            if bool(message_id) != bool(reply):
                raise ValueError("inbox reply requires message_id and reply together")
            payload = {"job_id": job_id, "account_key": account_key, "message_id": message_id,
                       "reply": reply, "send": bool(payload.get("send", False))}
        job_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    command = [sys.executable, str(project_root / "scripts" / "open-xhs-session.py"),
               "--account-key", account_key, "--target", target, "--job-id", job_id]
    if auto_publish:
        command.append("--auto-publish")
    if job_path is not None:
        command.extend(["--job", str(job_path.resolve())])
    creation_flags = 0
    if os.name == "nt":
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    process = None
    if existing_pid is None:
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
        "status": "browser_running" if existing_pid else "browser_starting",
        "pid": existing_pid or process.pid,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "publishes_automatically": False,
        "auto_publish_requested": bool(auto_publish),
        "reused_existing": bool(existing_pid),
    }
    if target in {"publish", "inbox"}:
        route = resolve_delivery_route(
            profile=profile_for("小红书"), action=target,
            browser_session_ready=True, prefer_api=False,
        )
        result["delivery_mode"] = route.mode
        result["delivery_reason"] = route.reason
    launch_dir = project_root / ".local" / "xhs-launches"
    launch_dir.mkdir(parents=True, exist_ok=True)
    launch_status_path(job_id, project_root).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result
