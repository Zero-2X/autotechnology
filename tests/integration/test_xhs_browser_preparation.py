import asyncio
from pathlib import Path

import pytest

from adapters.xiaohongshu.browser import BrowserPreparationError, ImageNote, XiaohongshuDraftPreparer


class Control:
    def __init__(self):
        self.value = ''
        self.files = []
    async def count(self): return 1
    async def wait_for(self, **kwargs): pass
    async def fill(self, value): self.value = value
    async def input_value(self): return self.value
    async def inner_text(self): return self.value
    async def set_input_files(self, paths): self.files = paths


class Page:
    url = 'https://creator.xiaohongshu.com/publish/publish'
    def __init__(self): self.controls = {}
    def locator(self, selector):
        return self.controls.setdefault(selector, Control())


def note(tmp_path):
    image = tmp_path / 'test.png'
    image.write_bytes(b'fixture')
    return ImageNote('account-1', 'title', 'body', (image,))


def test_preparation_never_claims_published(tmp_path):
    page = Page()
    result = asyncio.run(XiaohongshuDraftPreparer().prepare(
        page=page, note=note(tmp_path), bound_account_key='account-1'))
    assert result['status'] == 'awaiting_operator_review'
    assert result['published'] is False and result['platform_post_id'] is None
    assert page.controls['input[placeholder*="标题"]'].value == 'title'
    assert len(page.controls['input[type="file"]'].files) == 1


@pytest.mark.parametrize('url', ['https://creator.xiaohongshu.com/login',
    'https://creator.xiaohongshu.com.evil.example/publish',
    'http://creator.xiaohongshu.com/publish', 'https://creator.xiaohongshu.com/'])
def test_invalid_context_never_uploads(tmp_path, url):
    page = Page()
    page.url = url
    with pytest.raises(BrowserPreparationError):
        asyncio.run(XiaohongshuDraftPreparer().prepare(
            page=page, note=note(tmp_path), bound_account_key='account-1'))
    assert page.controls == {}


def test_wrong_account_never_uploads(tmp_path):
    page = Page()
    with pytest.raises(BrowserPreparationError, match='ACCOUNT_BINDING'):
        asyncio.run(XiaohongshuDraftPreparer().prepare(
            page=page, note=note(tmp_path), bound_account_key='account-2'))
    assert page.controls == {}


def test_fingerprint_tracks_image_bytes(tmp_path):
    item = note(tmp_path)
    before = item.fingerprint()
    item.images[0].write_bytes(b'changed')
    assert before != item.fingerprint()
