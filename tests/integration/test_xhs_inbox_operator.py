import asyncio

from adapters.xiaohongshu.inbox import InboxAutomationError, XiaohongshuInboxOperator


class Locator:
    def __init__(self, *, count=0, text="", value="", children=None, clicked=False):
        self._count = count
        self._text = text
        self._value = value
        self.children = children or {}
        self.clicked = clicked

    async def count(self): return self._count
    async def is_visible(self): return True
    async def inner_text(self): return self._text
    async def get_attribute(self, name): return "msg-1" if name == "data-id" else None
    async def fill(self, value): self._value = value
    async def input_value(self): return self._value
    async def click(self): self.clicked = True
    def locator(self, selector): return self.children.get(selector, Locator())
    def nth(self, _): return self


class Page:
    url = "https://creator.xiaohongshu.com/interaction"
    def __init__(self):
        self.reply_input = Locator(count=1)
        self.send_button = Locator(count=1)
        self.row = Locator(count=1, text="读者：请问怎么开始？", children={
            'textarea[placeholder*="回复"]': self.reply_input,
            'button:has-text("发送")': self.send_button,
        })
    def locator(self, selector):
        if selector == '.message-item': return Locator(count=1, text="读者：请问怎么开始？", children=self.row.children)
        if selector == '[data-id="msg-1"]': return self.row
        return Locator()


def test_scan_and_prepare_reply_without_sending():
    page = Page(); operator = XiaohongshuInboxOperator()
    scanned = asyncio.run(operator.scan(page=page))
    assert scanned["status"] == "inbox_scanned"
    assert scanned["messages"][0]["external_id"] == "msg-1"
    result = asyncio.run(operator.reply(page=page, external_id="msg-1", text="感谢提问", send=False))
    assert result["status"] == "reply_ready"
    assert result["sent"] is False


def test_reply_requires_explicit_unique_button():
    page = Page(); page.send_button._count = 0
    with __import__('pytest').raises(InboxAutomationError, match="REPLY_SEND_BUTTON_NOT_UNIQUE"):
        asyncio.run(XiaohongshuInboxOperator().reply(page=page, external_id="msg-1", text="回复", send=True))
