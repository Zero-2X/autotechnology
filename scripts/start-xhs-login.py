"""Open one isolated Xiaohongshu creator login session for operator handoff."""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import playwright
from playwright.async_api import async_playwright
from adapters.xiaohongshu.session import write_session_status


def _installed_chromium() -> str | None:
    """Find a locally installed Playwright Chromium when package/browser versions differ."""
    # Windows Store Python keeps the browser cache beside its package cache.
    package_root = Path(playwright.__file__).resolve().parents[4]
    roots = [package_root / 'ms-playwright', Path.home() / 'AppData' / 'Local' / 'ms-playwright']
    candidates = []
    for root in roots:
        candidates.extend(root.glob('chromium-*/chrome-win*/chrome.exe'))
    candidates = sorted(candidates, reverse=True)
    return str(candidates[0]) if candidates else None


async def main(account_key: str) -> None:
    if not account_key or any(ch in account_key for ch in '\\/:*?"<>|'):
        raise SystemExit('account_key must be a simple local identifier')
    state_dir = Path(__file__).resolve().parents[1] / '.local' / 'browser-accounts' / account_key
    state_dir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        launch_kwargs = {'headless': False, 'viewport': {'width': 1440, 'height': 900}}
        executable = _installed_chromium()
        if executable:
            launch_kwargs['executable_path'] = executable
        context = await playwright.chromium.launch_persistent_context(str(state_dir), **launch_kwargs)
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto('https://creator.xiaohongshu.com/', wait_until='domcontentloaded')
        print('浏览器已打开。请由账号持有人完成登录、扫码或验证码；不要把验证码发给程序。')
        print('登录完成后返回此终端按 Enter，程序只保存该账号的浏览器会话目录。')
        await asyncio.to_thread(input)
        payload = write_session_status(account_key, url=page.url)
        print({**payload, 'session_dir': str(state_dir)})
        await context.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--account-key', required=True)
    asyncio.run(main(parser.parse_args().account_key))
