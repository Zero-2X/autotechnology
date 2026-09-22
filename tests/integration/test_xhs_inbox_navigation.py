import asyncio
import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "open-xhs-session.py"
spec = importlib.util.spec_from_file_location("open_xhs_session", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class Locator:
    def __init__(self, *, count=0, visible=True, page=None):
        self._count = count
        self._visible = visible
        self.page = page

    async def count(self):
        return self._count

    async def is_visible(self):
        return self._visible

    async def click(self):
        self.page.url = "https://creator.xiaohongshu.com/interaction"


class Page:
    def __init__(self, active_selector=None):
        self.url = "https://creator.xiaohongshu.com/"
        self.active_selector = active_selector

    def locator(self, selector):
        return Locator(count=1 if selector == self.active_selector else 0, page=self)


def test_inbox_navigation_uses_visible_interaction_entry():
    page = Page('a:has-text("互动")')
    result = asyncio.run(module.select_inbox(page))
    assert result["status"] == "inbox_ready"
    assert result["url"].endswith("/interaction")


def test_inbox_navigation_reports_operator_action_when_entry_missing():
    result = asyncio.run(module.select_inbox(Page()))
    assert result["status"] == "inbox_needs_operator"
