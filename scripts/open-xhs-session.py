"""Open a persistent Xiaohongshu operator session launched by the local dashboard."""
from __future__ import annotations

import argparse
import asyncio
import json
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
            return {"status": "inbox_ready", "url": page.url}
        except Exception:
            continue
    return {"status": "inbox_needs_operator", "url": page.url}


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

        if "creator.xiaohongshu.com" in page.url:
            write_session_status(account_key, url=page.url)

        if target == "inbox":
            inbox_state = await select_inbox(page)
            update_job(root, job_id, **inbox_state,
                       error=None if inbox_state["status"] == "inbox_ready" else "未找到消息/互动入口，请在小红书窗口手动进入消息页")
            if job_path and inbox_state["status"] == "inbox_ready":
                inbox_job = json.loads(Path(job_path).read_text(encoding="utf-8"))
                scan = await XiaohongshuInboxOperator().scan(page=page)
                update_job(root, job_id, **scan, error=None if scan["status"] == "inbox_scanned" else scan.get("reason"))
                if inbox_job.get("message_id") and inbox_job.get("reply"):
                    try:
                        result = await XiaohongshuInboxOperator().reply(
                            page=page,
                            external_id=str(inbox_job["message_id"]),
                            text=str(inbox_job["reply"]),
                            send=bool(inbox_job.get("send", False)),
                        )
                        Path(job_path).with_name("result.json").write_text(
                            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                        )
                        update_job(root, job_id, **result, error=None)
                    except (InboxAutomationError, ValueError) as exc:
                        update_job(root, job_id, status="inbox_needs_operator", error=str(exc))
            elif target == "inbox" and not job_path and inbox_state["status"] == "inbox_ready":
                scan = await XiaohongshuInboxOperator().scan(page=page)
                update_job(root, job_id, **scan, error=None if scan["status"] == "inbox_scanned" else scan.get("reason"))

        if target == "publish" and job_path:
            job = json.loads(Path(job_path).read_text(encoding="utf-8"))
            await select_image_note(page)
            note = ImageNote(
                account_key=account_key,
                title=job["title"],
                body=job["body"] + ("\n\n" + " ".join(job["hashtags"]) if job["hashtags"] else ""),
                images=(Path(job["cover_path"]),),
            )
            try:
                result = await XiaohongshuDraftPreparer().prepare(
                    page=page, note=note, bound_account_key=account_key
                )
                if auto_publish:
                    result.update(await XiaohongshuDraftPreparer().submit_publish(page=page))
                Path(job_path).with_name("result.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                update_job(root, job_id, status=result.get("status", "draft_prepared"),
                           publish_submitted=bool(auto_publish))
            except BrowserPreparationError as exc:
                update_job(root, job_id, status="operator_action_required", error=str(exc))
                Path(job_path).with_name("result.json").write_text(
                    json.dumps({"status": "operator_action_required", "error": str(exc), "url": page.url},
                               ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

        while context.pages:
            current_url = page.url
            if "creator.xiaohongshu.com" in current_url:
                write_session_status(account_key, url=current_url)
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
