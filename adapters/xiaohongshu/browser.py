"""Prepare an image note in an operator-owned, isolated browser context.

Selectors are informed by the supplied xhs_auto repository and need live
validation. No guessed fallback clicks, cookie rewriting, or publish success
inferred from clicking a button. This adapter intentionally stops at preview.
"""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
import json
import asyncio


class BrowserPreparationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ImageNote:
    account_key: str
    title: str
    body: str
    images: tuple[Path, ...]

    def validate(self) -> None:
        if not self.account_key.strip() or not self.title.strip() or not self.body.strip():
            raise ValueError('Account, title and body are required')
        if not self.images:
            raise ValueError('An image note requires local images')
        for path in self.images:
            if not path.is_file() or path.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
                raise ValueError('Each image must be an existing supported local image')

    def fingerprint(self) -> str:
        self.validate()
        value = {'account': self.account_key, 'title': self.title, 'body': self.body,
                 'images': [sha256(p.read_bytes()).hexdigest() for p in self.images]}
        return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class XiaohongshuDraftPreparer:
    """Caller supplies the page for its account; no platform permissions invented."""
    async def prepare(self, *, page: Any, note: ImageNote, bound_account_key: str) -> dict:
        note.validate()
        if bound_account_key != note.account_key:
            raise BrowserPreparationError('ACCOUNT_BINDING_MISMATCH')
        url = urlsplit(page.url)
        if url.hostname != 'creator.xiaohongshu.com' or url.scheme != 'https':
            raise BrowserPreparationError('OPEN_CREATOR_PUBLISH_PAGE')
        if 'login' in url.path:
            raise BrowserPreparationError('LOGIN_REQUIRED')
        if 'publish' not in url.path:
            raise BrowserPreparationError('OPEN_CREATOR_PUBLISH_PAGE')
        # The operator opens the image-note editor. Never guess which tab to click.
        upload = page.locator('input[type="file"]')
        if await upload.count() != 1:
            raise BrowserPreparationError('IMAGE_UPLOAD_CONTROL_AMBIGUOUS')
        fingerprint = note.fingerprint()
        await upload.set_input_files([str(p.resolve()) for p in note.images])
        # The creator center renders title/body controls asynchronously after image decoding.
        await asyncio.sleep(3)
        title = None
        body = None
        for _ in range(8):
            for selector in (
                'input[placeholder*="标题"]',
                'input[placeholder="填写标题会有更多赞哦～"]',
                'input.d-text', 'input.title',
                '[data-placeholder="标题"]', '.note-editor-wrapper input', '.edit-wrapper input',
            ):
                candidate = page.locator(selector)
                visible = await candidate.is_visible() if hasattr(candidate, 'is_visible') else True
                if await candidate.count() == 1 and visible:
                    title = candidate
                    break
            for selector in ('.ql-editor', '[data-placeholder="添加正文"]', '#post-textarea',
                             '.post-content', 'div[contenteditable="true"]', '[role="textbox"]'):
                candidate = page.locator(selector)
                visible = await candidate.is_visible() if hasattr(candidate, 'is_visible') else True
                if await candidate.count() == 1 and visible:
                    body = candidate
                    break
            if title is not None and body is not None:
                break
            await asyncio.sleep(1)
        if title is None or body is None:
            raise BrowserPreparationError('EDITOR_CONTROL_AMBIGUOUS')
        await title.fill(note.title)
        await body.fill(note.body)
        if await title.input_value() != note.title or (await body.inner_text()).strip() != note.body.strip():
            raise BrowserPreparationError('EDITOR_READBACK_MISMATCH')
        return {'status': 'awaiting_operator_review', 'account_key': note.account_key,
                'content_hash': fingerprint, 'platform_post_id': None,
                'published': False, 'images_require_visual_check': True,
                'account_identity_requires_visual_check': True}
