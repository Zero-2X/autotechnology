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
from modules.platforms.routing import profile_for, resolve_delivery_route


TARGETS = {"home", "inbox", "publish"}


def command_queue_path(account_key: str, root: Path | None = None) -> Path:
    project_root = root or Path(__file__).resolve().parents[2]
    return project_root / ".local" / "xhs-commands" / f"{account_key}.jsonl"


def enqueue_command(account_key: str, command: dict[str, Any], root: Path | None = None) -> None:
    path = command_queue_path(account_key, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(command, ensure_ascii=False) + "\n")


def _existing_profile_pid(profile: Path) -> int | None:
    """Find an already running Playwright browser using this profile."""
    if psutil is None:
        return None
    marker = str(profile.resolve()).lower().replace("/", "\\")
    try:
        for process in psutil.process_iter(["pid", "name"]):
            try:
                name = str(process.info.get("name", "")).lower()
                if "chrome" not in name:
                    continue
                cmdline = " ".join(process.cmdline()).lower().replace("/", "\\")
            except (OSError, psutil.Error):
                continue
            if "--type=" not in cmdline and f"--user-data-dir={marker}" in cmdline:
                return int(process.info["pid"])
    except (OSError, psutil.Error):
        return None
    return None


def _session_runner_is_current(pid: int, script_path: Path) -> bool:
    """Avoid queuing browser work to a session worker that loaded older code."""
    if psutil is None:
        return False
    try:
        marker = str(script_path.resolve()).lower().replace("/", "\\")
        modified_at = script_path.stat().st_mtime
        process = psutil.Process(pid)
        for candidate in [process, *process.parents()]:
            try:
                command = " ".join(candidate.cmdline()).lower().replace("/", "\\")
                if marker in command:
                    return candidate.create_time() > modified_at
            except (OSError, psutil.Error):
                continue
    except (OSError, psutil.Error):
        pass
    return False


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
    script_path = project_root / "scripts" / "open-xhs-session.py"
    if existing_pid and target in {"publish", "inbox"} and not _session_runner_is_current(existing_pid, script_path):
        raise ValueError("该账号窗口仍运行旧版小红书流程。请先保存未完成内容、关闭该窗口后再点“打开账号”更新会话；本次操作尚未执行。")

    job_id = f"xhs-{uuid4().hex[:12]}"
    job_path: Path | None = None
    if target in {"publish", "inbox"} and content:
        payload = content or {}
        queue_dir = project_root / ".local" / "xhs-jobs" / job_id
        if target == "publish":
            title = str(payload.get("title", "")).strip()
            body = str(payload.get("body", "")).strip()
            hashtags = tuple(str(item).strip() for item in payload.get("hashtags", []) if str(item).strip())
            if not title or not body:
                raise ValueError("publish preview requires title and body")
            queue_dir.mkdir(parents=True, exist_ok=True)
            cover_path = generate_cover_png(DemoContent(title, body, hashtags), queue_dir / "cover.png")
            payload = {"job_id": job_id, "account_key": account_key, "title": title,
                       "body": body, "hashtags": list(hashtags), "cover_path": str(cover_path.resolve())}
        else:
            message_id = str(payload.get("message_id", "")).strip()
            reply = str(payload.get("reply", "")).strip()
            if bool(message_id) != bool(reply):
                raise ValueError("inbox reply requires message_id and reply together")
            risk = str(payload.get("risk", "unknown")).strip()
            send_requested = payload.get("send", False)
            if not isinstance(send_requested, bool):
                raise ValueError("inbox reply send flag must be a boolean")
            if send_requested and risk != "low":
                raise ValueError("only low-risk inbox replies may be sent through the browser")
            payload = {"job_id": job_id, "account_key": account_key, "message_id": message_id,
                       "reply": reply, "risk": risk, "send": send_requested}
            queue_dir.mkdir(parents=True, exist_ok=True)
        job_path = queue_dir / "job.json"
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
    command_queued = existing_pid is not None
    result = {
        "job_id": job_id,
        "account_key": account_key,
        "target": target,
        "status": "command_queued" if command_queued else "browser_starting",
        "pid": existing_pid,
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
    if existing_pid is None:
        process = subprocess.Popen(
            command,
            cwd=project_root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
        result["pid"] = process.pid
    else:
        enqueue_command(account_key, {
            "job_id": job_id, "target": target,
            "job_path": str(job_path.resolve()) if job_path is not None else None,
            "auto_publish": bool(auto_publish),
        }, project_root)
    return result
