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
    if await page.locator('input[type="file"]').count() == 1:
        return
    image_entries = page.get_by_text("上传图文", exact=True)
    if await image_entries.count():
        await image_entries.first.click()
        await asyncio.sleep(2)
    tabs = page.locator(".creator-tab")
    if await tabs.count() > 1:
        await tabs.nth(1).click()
        await asyncio.sleep(1)


async def run(account_key: str, target: str, job_path: str | None) -> None:
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

        if "creator.xiaohongshu.com" in page.url and "login" not in page.url:
            write_session_status(account_key, url=page.url)

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
                Path(job_path).with_name("result.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except BrowserPreparationError as exc:
                Path(job_path).with_name("result.json").write_text(
                    json.dumps({"status": "operator_action_required", "error": str(exc), "url": page.url},
                               ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

        while context.pages:
            await asyncio.sleep(2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-key", required=True)
    parser.add_argument("--target", choices=tuple(URLS), required=True)
    parser.add_argument("--job")
    args = parser.parse_args()
    asyncio.run(run(args.account_key, args.target, args.job))
