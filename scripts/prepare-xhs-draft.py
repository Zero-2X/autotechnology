"""Open the saved XHS session, fill one generated image-note draft, and stop for review."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import playwright
from playwright.async_api import async_playwright

from adapters.xiaohongshu.browser import BrowserPreparationError, ImageNote, XiaohongshuDraftPreparer
from modules.media.local_demo_generator import generate_demo_content


def _installed_chromium() -> str | None:
    roots = [Path(playwright.__file__).resolve().parents[4] / 'ms-playwright',
             Path.home() / 'AppData' / 'Local' / 'ms-playwright']
    candidates = []
    for root in roots:
        candidates.extend(root.glob('chromium-*/chrome-win*/chrome.exe'))
    return str(sorted(candidates, reverse=True)[0]) if candidates else None


async def main(account_key: str, manual_editor: bool = False) -> None:
    root = Path(__file__).resolve().parents[1]
    profile = root / '.local' / 'browser-accounts' / account_key
    cover = root / '.tmp' / 'generated-content' / 'cover.png'
    if not profile.exists():
        raise SystemExit('No saved session; run start-xhs-login.ps1 first.')
    if not cover.exists():
        raise SystemExit('Generated cover missing; run generate-demo-content.py first.')
    content = generate_demo_content('小红书账号矩阵的内容质量管理')
    note = ImageNote(account_key=account_key, title=content.title,
                     body=content.body + '\n\n' + ' '.join(content.hashtags), images=(cover,))
    async with async_playwright() as playwright:
        launch_kwargs = {'headless': False}
        executable = _installed_chromium()
        if executable:
            launch_kwargs['executable_path'] = executable
        context = await playwright.chromium.launch_persistent_context(str(profile), **launch_kwargs)
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto('https://creator.xiaohongshu.com/publish/publish', wait_until='domcontentloaded')
        # The creator center opens on a media-type tab; select the image-note tab
        # before handing control to the strict editor adapter.
        tabs = page.locator('.creator-tab')
        if await tabs.count() > 1:
            await tabs.nth(1).click()
        else:
            image_tab = page.get_by_text('图文', exact=True)
            if await image_tab.count() == 1:
                await image_tab.click()
        await page.wait_for_timeout(1500)
        if manual_editor and await page.locator('input[type="file"]').count() != 1:
            print('请在已打开的小红书窗口中手动进入“图文”编辑器，完成后回到此终端按 Enter。')
            await asyncio.to_thread(input)
        try:
            result = await XiaohongshuDraftPreparer().prepare(page=page, note=note, bound_account_key=account_key)
        except BrowserPreparationError as exc:
            print({'error': str(exc), 'url': page.url, 'title': await page.title()})
            print((await page.locator('body').inner_text())[:2000])
            await page.screenshot(path=str(root / '.tmp' / 'xhs-editor-diagnostic.png'), full_page=True)
            raise
        output = root / '.tmp' / 'xhs-draft-result.json'
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False))
        print('草稿已填入浏览器。请人工检查图片、标题和正文；本脚本不会点击发布。检查后按 Enter 关闭窗口。')
        await asyncio.to_thread(input)
        await context.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--account-key', default='xhs-9653254890')
    parser.add_argument('--manual-editor', action='store_true', help='允许运营人员先手动打开图文编辑器')
    args = parser.parse_args()
    asyncio.run(main(args.account_key, args.manual_editor))
