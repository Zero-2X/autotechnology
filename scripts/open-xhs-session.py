"""Open a persistent Xiaohongshu operator session launched by the local dashboard."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import playwright
from playwright.async_api import async_playwright

from adapters.xiaohongshu.browser import BrowserPreparationError, ImageNote, XiaohongshuDraftPreparer
from adapters.xiaohongshu.inbox import InboxAutomationError, XiaohongshuInboxOperator
from adapters.xiaohongshu.session import write_session_status


URLS = {
    "home": "https://creator.xiaohongshu.com/",
    "inbox": "https://creator.xiaohongshu.com/",
    "publish": "https://creator.xiaohongshu.com/publish/publish",
}


def browser_action_enabled(name: str) -> bool:
    """Require an explicit local opt-in for browser side effects."""
    env_name = {
        "publish": "XHS_ALLOW_EXPERIMENTAL_SUBMIT",
        "reply": "XHS_ALLOW_EXPERIMENTAL_REPLY",
    }.get(name)
    return bool(env_name and os.getenv(env_name, "").strip().lower() in {"1", "true", "yes"})


def command_queue_path(root: Path, account_key: str) -> Path:
    return root / ".local" / "xhs-commands" / f"{account_key}.jsonl"


def take_commands(root: Path, account_key: str) -> list[dict]:
    path = command_queue_path(root, account_key)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text("", encoding="utf-8")
    except OSError:
        return []
    commands = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            commands.append(value)
    return commands


def installed_chromium() -> str | None:
    roots = [Path(playwright.__file__).resolve().parents[4] / "ms-playwright",
             Path.home() / "AppData" / "Local" / "ms-playwright"]
    candidates: list[Path] = []
    for root in roots:
        candidates.extend(root.glob("chromium-*/chrome-win*/chrome.exe"))
    return str(sorted(candidates, reverse=True)[0]) if candidates else None


async def select_image_note(page) -> None:
    for upload_selector in ('input[type="file"]', '.upload-input', '.upload-button'):
        if await page.locator(upload_selector).count() == 1:
            return
    for selector in ('.publish-video .btn', "button:has-text('发布笔记')", ".btn:text('发布笔记')"):
        candidate = page.locator(selector)
        if await candidate.count() == 1:
            try:
                if hasattr(candidate, 'is_visible') and not await candidate.is_visible():
                    continue
                await candidate.click()
                await asyncio.sleep(2)
                break
            except Exception:
                continue
    image_entries = page.get_by_text("上传图文", exact=True)
    if await image_entries.count():
        await image_entries.first.click()
        await asyncio.sleep(2)
    tabs = page.locator(".creator-tab")
    if await tabs.count() > 1:
        await tabs.nth(1).click()
        await asyncio.sleep(1)


async def select_inbox(page) -> dict[str, str]:
    """Open the creator-center interaction area without guessing a URL."""
    if "/login" in page.url:
        return {"status": "login_required", "url": page.url}
    for selector in ('input[placeholder*="手机号"]', 'input[placeholder*="验证码"]',
                     'text=扫码登录', 'text=登录小红书'):
        try:
            candidate = page.locator(selector)
            if await candidate.count() and await candidate.first.is_visible():
                return {"status": "login_required", "url": "https://creator.xiaohongshu.com/login"}
        except Exception:
            continue
    selectors = (
        'a[href*="message"]', 'a[href*="comment"]', 'a[href*="interaction"]',
        'button:has-text("消息")', 'button:has-text("互动")',
        'a:has-text("消息")', 'a:has-text("互动")', 'a:has-text("评论")',
    )
    for selector in selectors:
        candidate = page.locator(selector)
        count = await candidate.count()
        if count != 1:
            continue
        if hasattr(candidate, 'is_visible') and not await candidate.is_visible():
            continue
        try:
            await candidate.click()
            await asyncio.sleep(2)
            current = await session_url(page)
            if "/login" in current:
                return {"status": "login_required", "url": current}
            return {"status": "inbox_ready", "url": page.url}
        except Exception:
            continue
    return {"status": "inbox_needs_operator", "url": page.url}


async def handle_inbox(page, root: Path, account_key: str, job_path: str | None,
                       job_id: str | None, current_page: bool = False) -> str:
    if current_page:
        current = await session_url(page)
        if "/login" in current:
            inbox_state = {"status": "login_required", "url": current}
        else:
            inbox_state = {"status": "inbox_ready", "url": page.url}
    else:
        inbox_state = await select_inbox(page)
    if inbox_state["status"] == "login_required":
        write_session_status(account_key, url="https://creator.xiaohongshu.com/login",
                             root=root / ".local" / "browser-accounts")
    update_job(root, job_id, **inbox_state,
               error=None if inbox_state["status"] == "inbox_ready" else (
                   "小红书会话已失效，请先在窗口登录" if inbox_state["status"] == "login_required"
                   else "未找到消息/互动入口，请在小红书窗口手动进入消息页"))
    if inbox_state["status"] != "inbox_ready":
        return inbox_state["status"]
    inbox_job = json.loads(Path(job_path).read_text(encoding="utf-8")) if job_path else {}
    try:
        scan = await XiaohongshuInboxOperator().scan(page=page)
    except InboxAutomationError as exc:
        if str(exc) == "LOGIN_REQUIRED":
            login_url = "https://creator.xiaohongshu.com/login"
            write_session_status(account_key, url=login_url,
                                 root=root / ".local" / "browser-accounts")
            update_job(root, job_id, status="login_required", url=login_url,
                       error="小红书消息区要求重新登录，请在账号窗口扫码后重试")
            if job_path:
                Path(job_path).with_name("result.json").write_text(
                    json.dumps({"status": "login_required", "url": login_url}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            return "login_required"
        update_job(root, job_id, status="inbox_needs_operator", error=str(exc))
        return "inbox_needs_operator"
    update_job(root, job_id, **scan, error=None if scan["status"] == "inbox_scanned" else scan.get("reason"))
    if inbox_job.get("message_id") and inbox_job.get("reply"):
        if inbox_job.get("send") and not browser_action_enabled("reply"):
            result = {
                "status": "reply_ready",
                "sent": False,
                "requires_operator": True,
                "send_blocked_reason": "默认关闭网页自动回复；请在官方页面人工发送，或由管理员按账号风险策略显式启用。",
            }
            Path(job_path).with_name("result.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            update_job(root, job_id, **result, error=None)
            return "reply_ready"
        try:
            result = await XiaohongshuInboxOperator().reply(
                page=page, external_id=str(inbox_job["message_id"]),
                text=str(inbox_job["reply"]), send=bool(inbox_job.get("send", False)),
                risk=str(inbox_job.get("risk", "unknown")),
            )
            Path(job_path).with_name("result.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            update_job(root, job_id, **result, error=None)
        except (InboxAutomationError, ValueError) as exc:
            update_job(root, job_id, status="inbox_needs_operator", error=str(exc))
    return scan["status"]


async def has_unsaved_publish_content(page) -> bool:
    """Do not navigate away from text or images already in the creator editor."""
    if "publish" not in page.url.lower():
        return False
    selectors = (
        'input[placeholder*="标题"]', 'input.title', 'input.d-text',
        '.ql-editor', '[data-placeholder="添加正文"]', '#post-textarea',
        '.post-content', 'div[contenteditable="true"]', '[role="textbox"]',
    )
    for selector in selectors:
        locator = page.locator(selector)
        count = await locator.count()
        for index in range(count):
            candidate = locator.nth(index) if count > 1 else locator
            try:
                if not await candidate.is_visible():
                    continue
                value = await candidate.input_value() if selector.startswith("input") else await candidate.inner_text()
                if value.strip():
                    return True
            except Exception:
                continue
    uploads = page.locator('input[type="file"]')
    for index in range(await uploads.count()):
        candidate = uploads.nth(index) if await uploads.count() > 1 else uploads
        try:
            if await candidate.evaluate("node => Boolean(node.files && node.files.length)"):
                return True
        except Exception:
            continue
    return False


async def prepare_publish(page, root: Path, account_key: str, job_path: str,
                          job_id: str | None, auto_publish: bool) -> str:
    """Fill one queued image note and report workflow status separately from page status."""
    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    if str(job.get("account_key", "")) != account_key:
        update_job(root, job_id, status="failed", error="ACCOUNT_BINDING_MISMATCH")
        return "failed"
    current = await session_url(page)
    if "/login" in current:
        write_session_status(account_key, url=current, root=root / ".local" / "browser-accounts")
        update_job(root, job_id, status="login_required", url=current,
                   error="请先在小红书窗口完成登录")
        return "login_required"
    update_job(root, job_id, status="preparing", url=page.url)
    try:
        await select_image_note(page)
        note = ImageNote(
            account_key=account_key,
            title=job["title"],
            body=job["body"] + ("\n\n" + " ".join(job["hashtags"]) if job["hashtags"] else ""),
            images=(Path(job["cover_path"]),),
        )
        result = await XiaohongshuDraftPreparer().prepare(
            page=page, note=note, bound_account_key=account_key
        )
        if auto_publish and browser_action_enabled("publish"):
            update_job(root, job_id, status="submitting_publish", url=page.url)
            result.update(await XiaohongshuDraftPreparer().submit_publish(page=page))
        elif auto_publish:
            result["auto_submit_blocked"] = True
            result["auto_submit_reason"] = "默认关闭网页自动点击发布；请在官方页面人工确认。"
        workflow_status = result.get("status", "awaiting_operator_review")
        if workflow_status == "awaiting_operator_review":
            workflow_status = "draft_prepared"
        result["workflow_status"] = workflow_status
        Path(job_path).with_name("result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        update_job(root, job_id, status=workflow_status,
                   preparation_status=result.get("status"),
                   publish_submitted=bool(auto_publish), error=None, url=page.url)
        return str(workflow_status)
    except BrowserPreparationError as exc:
        status = "login_required" if str(exc) == "LOGIN_REQUIRED" else "operator_action_required"
        if status == "login_required":
            write_session_status(account_key, url="https://creator.xiaohongshu.com/login",
                                 root=root / ".local" / "browser-accounts")
        update_job(root, job_id, status=status, error=str(exc), url=page.url)
        Path(job_path).with_name("result.json").write_text(
            json.dumps({"status": status, "error": str(exc), "url": page.url},
                       ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return status


async def handle_command(page, root: Path, account_key: str, command: dict) -> str | None:
    target = str(command.get("target", "home"))
    job_id = str(command.get("job_id", "")) or None
    job_path = command.get("job_path")
    if target not in URLS:
        update_job(root, job_id, status="failed", error="invalid queued target")
        return "failed"
    if target == "publish":
        if not job_path or not Path(str(job_path)).is_file():
            update_job(root, job_id, status="failed", error="publish job payload is missing")
            return "failed"
        job = json.loads(Path(str(job_path)).read_text(encoding="utf-8"))
        if str(job.get("account_key", "")) != account_key:
            update_job(root, job_id, status="failed", error="ACCOUNT_BINDING_MISMATCH")
            return "failed"
        current = await session_url(page)
        if "/login" in current:
            write_session_status(account_key, url=current, root=root / ".local" / "browser-accounts")
            update_job(root, job_id, status="login_required", url=current,
                       error="请先在小红书窗口完成登录")
            return "login_required"
        if await has_unsaved_publish_content(page):
            update_job(root, job_id, status="operator_action_required",
                       error="当前编辑器已有未保存内容，请先保存或清空后再准备新草稿。", url=page.url)
            return "operator_action_required"
        await page.goto(URLS[target], wait_until="domcontentloaded")
        return await prepare_publish(
            page, root, account_key, str(job_path), job_id,
            bool(command.get("auto_publish", False)),
        )
    if target == "inbox":
        if command.get("scan_current"):
            return await handle_inbox(page, root, account_key, job_path, job_id, current_page=True)
        await page.goto(URLS[target], wait_until="domcontentloaded")
        return await handle_inbox(page, root, account_key, job_path, job_id)
    else:
        await page.goto(URLS[target], wait_until="domcontentloaded")
        update_job(root, job_id, status="browser_running", url=page.url)
        return "browser_running"


async def session_url(page) -> str:
    """Return a conservative URL marker when creator center shows login UI."""
    current = page.url
    if "/login" in current:
        return "https://creator.xiaohongshu.com/login"
    for selector in ('input[placeholder*="手机号"]', 'input[placeholder*="验证码"]',
                     'text=扫码登录', 'text=登录小红书'):
        try:
            candidate = page.locator(selector)
            if await candidate.count() and await candidate.first.is_visible():
                return "https://creator.xiaohongshu.com/login"
        except Exception:
            continue
    return current


async def sync_session_status(page, account_key: str, root: Path | None = None) -> None:
    """Refresh the saved login marker from the visible creator-center page."""
    if "creator.xiaohongshu.com" in page.url:
        session_root = root / ".local" / "browser-accounts" if root else None
        write_session_status(account_key, url=await session_url(page), root=session_root)


async def run(account_key: str, target: str, job_path: str | None, job_id: str | None = None,
              auto_publish: bool = False) -> None:
    root = Path(__file__).resolve().parents[1]
    profile = root / ".local" / "browser-accounts" / account_key
    profile.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as runtime:
        launch = {"headless": False, "viewport": {"width": 1440, "height": 900}}
        executable = installed_chromium()
        if executable:
            launch["executable_path"] = executable
        context = await runtime.chromium.launch_persistent_context(str(profile), **launch)
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(URLS[target], wait_until="domcontentloaded")

        update_job(root, job_id, status="preparing" if target == "publish" else "browser_running")
        await sync_session_status(page, account_key, root)

        if target == "inbox":
            await handle_inbox(page, root, account_key, job_path, job_id)

        if target == "publish" and job_path:
            await prepare_publish(page, root, account_key, job_path, job_id, auto_publish)

        while context.pages:
            await sync_session_status(page, account_key, root)
            for command in take_commands(root, account_key):
                try:
                    await handle_command(page, root, account_key, command)
                except Exception as exc:
                    update_job(root, str(command.get("job_id", "")) or None,
                               status="failed", error=f"{type(exc).__name__}: {exc}")
            await asyncio.sleep(2)


def update_job(root: Path, job_id: str | None, **values: object) -> None:
    if not job_id:
        return
    path = root / ".local" / "xhs-launches" / f"{job_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    current = {}
    if path.exists():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            current = {}
    current.update(values)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")


async def run_with_status(account_key: str, target: str, job_path: str | None, job_id: str | None,
                          auto_publish: bool = False) -> None:
    root = Path(__file__).resolve().parents[1]
    update_job(root, job_id, status="browser_starting")
    try:
        await run(account_key, target, job_path, job_id, auto_publish)
        update_job(root, job_id, status="browser_closed")
    except Exception as exc:
        update_job(root, job_id, status="failed", error=f"{type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-key", required=True)
    parser.add_argument("--target", choices=tuple(URLS), required=True)
    parser.add_argument("--job")
    parser.add_argument("--job-id")
    parser.add_argument("--auto-publish", action="store_true")
    args = parser.parse_args()
    asyncio.run(run_with_status(args.account_key, args.target, args.job, args.job_id, args.auto_publish))
