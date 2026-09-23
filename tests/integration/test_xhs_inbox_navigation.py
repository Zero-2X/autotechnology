import asyncio
import importlib.util
import json
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


def test_prepared_draft_uses_dashboard_terminal_status(monkeypatch, tmp_path):
    image = tmp_path / "cover.png"
    image.write_bytes(b"cover")
    job_path = tmp_path / "job.json"
    job_path.write_text(json.dumps({
        "account_key": "account-1", "title": "标题", "body": "正文",
        "hashtags": ["话题"], "cover_path": str(image),
    }), encoding="utf-8")

    class Preparer:
        async def prepare(self, **kwargs):
            return {"status": "awaiting_operator_review", "published": False}

    async def no_op(_page):
        return None

    async def current_url(page):
        return page.url

    monkeypatch.setattr(module, "select_image_note", no_op)
    monkeypatch.setattr(module, "session_url", current_url)
    monkeypatch.setattr(module, "XiaohongshuDraftPreparer", Preparer)
    page = Page()

    status = asyncio.run(module.prepare_publish(
        page, tmp_path, "account-1", str(job_path), "xhs-test", False,
    ))

    assert status == "draft_prepared"
    launch = json.loads((tmp_path / ".local" / "xhs-launches" / "xhs-test.json").read_text(encoding="utf-8"))
    result = json.loads(job_path.with_name("result.json").read_text(encoding="utf-8"))
    assert launch["status"] == "draft_prepared"
    assert result["status"] == "awaiting_operator_review"
    assert result["workflow_status"] == "draft_prepared"
    assert result["published"] is False


def test_queued_publish_preserves_unsaved_creator_editor(monkeypatch, tmp_path):
    job_path = tmp_path / "job.json"
    job_path.write_text(json.dumps({"account_key": "account-1"}), encoding="utf-8")

    class EditorPage:
        url = "https://creator.xiaohongshu.com/publish/publish"
        navigated = False

        async def goto(self, *_args, **_kwargs):
            self.navigated = True

    async def current_url(page):
        return page.url

    async def has_unsaved(_page):
        return True

    monkeypatch.setattr(module, "session_url", current_url)
    monkeypatch.setattr(module, "has_unsaved_publish_content", has_unsaved)
    page = EditorPage()

    status = asyncio.run(module.handle_command(page, tmp_path, "account-1", {
        "job_id": "xhs-queued", "target": "publish", "job_path": str(job_path),
    }))

    launch = json.loads((tmp_path / ".local" / "xhs-launches" / "xhs-queued.json").read_text(encoding="utf-8"))
    assert status == "operator_action_required"
    assert page.navigated is False
    assert "未保存内容" in launch["error"]
