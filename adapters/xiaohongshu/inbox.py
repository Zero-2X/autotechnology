"""Fail-safe browser operations for creator-center comments and messages."""
from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import urlsplit


class InboxAutomationError(RuntimeError):
    pass


class XiaohongshuInboxOperator:
    """Use visible, unique controls only; never call private platform endpoints."""

    _ROW_SELECTORS = (
        '[data-testid*="message"]', '[data-testid*="comment"]',
        '[data-id].message-item', '[data-id].comment-item',
        '.message-item', '.comment-item', '[class*="message-item"]', '[class*="comment-item"]',
    )
    _INPUT_SELECTORS = (
        'textarea[placeholder*="回复"]', 'textarea[placeholder*="输入"]',
        '[contenteditable="true"]', '[role="textbox"]',
    )
    _SEND_SELECTORS = (
        'button:has-text("发送")', 'button:has-text("回复")',
        '[role="button"]:has-text("发送")', '[role="button"]:has-text("回复")',
    )

    @staticmethod
    def _validate_page(page: Any) -> None:
        url = urlsplit(page.url)
        if url.scheme != "https" or url.hostname != "creator.xiaohongshu.com":
            raise InboxAutomationError("OPEN_CREATOR_INBOX")
        if "login" in url.path:
            raise InboxAutomationError("LOGIN_REQUIRED")

    async def _unique_visible(self, page: Any, selectors: tuple[str, ...]) -> Any | None:
        for selector in selectors:
            candidate = page.locator(selector)
            if await candidate.count() != 1:
                continue
            if hasattr(candidate, "is_visible") and not await candidate.is_visible():
                continue
            return candidate
        return None

    async def scan(self, *, page: Any) -> dict[str, Any]:
        self._validate_page(page)
        rows = None
        for selector in self._ROW_SELECTORS:
            candidate = page.locator(selector)
            if await candidate.count() > 0:
                rows = candidate
                break
        if rows is None:
            return {"status": "inbox_needs_operator", "messages": [],
                    "reason": "MESSAGE_ROW_SELECTOR_NOT_FOUND", "requires_operator": True}
        count = min(await rows.count(), 100)
        messages = []
        for index in range(count):
            row = rows.nth(index)
            text = (await row.inner_text()).strip()
            if not text:
                continue
            external_id = await row.get_attribute("data-id") if hasattr(row, "get_attribute") else None
            # A synthetic row index is not a stable platform identifier and must
            # never be used later to address a reply action.
            messages.append({"external_id": external_id, "text": text})
        return {"status": "inbox_scanned", "messages": messages,
                "requires_operator": False}

    async def reply(self, *, page: Any, external_id: str, text: str,
                    send: bool = False, risk: str = "unknown") -> dict[str, Any]:
        self._validate_page(page)
        if not external_id.strip() or not text.strip():
            raise ValueError("external_id and text are required")
        if send and risk != "low":
            raise InboxAutomationError("LOW_RISK_REQUIRED_FOR_SEND")
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,200}", external_id):
            raise ValueError("external_id contains unsupported characters")
        row = page.locator(f'[data-id="{external_id}"]')
        if await row.count() != 1:
            raise InboxAutomationError("MESSAGE_ROW_NOT_UNIQUE")
        input_box = await self._unique_visible(row, self._INPUT_SELECTORS)
        if input_box is None:
            input_box = await self._unique_visible(page, self._INPUT_SELECTORS)
        if input_box is None:
            raise InboxAutomationError("REPLY_INPUT_NOT_UNIQUE")
        await input_box.fill(text)
        if hasattr(input_box, "input_value"):
            value = await input_box.input_value()
        else:
            value = await input_box.inner_text()
        if value.strip() != text.strip():
            raise InboxAutomationError("REPLY_READBACK_MISMATCH")
        if not send:
            return {"status": "reply_ready", "external_id": external_id,
                    "reply": text, "sent": False, "requires_operator": True}
        button = await self._unique_visible(row, self._SEND_SELECTORS)
        if button is None:
            button = await self._unique_visible(page, self._SEND_SELECTORS)
        if button is None:
            raise InboxAutomationError("REPLY_SEND_BUTTON_NOT_UNIQUE")
        await button.click()
        await asyncio.sleep(1)
        return {"status": "reply_submitted", "external_id": external_id,
                "reply": text, "sent": False, "requires_requery": True}


__all__ = ["InboxAutomationError", "XiaohongshuInboxOperator"]
