"""Deterministic customer-support draft replies used without a model provider."""
from __future__ import annotations


def generate_local_reply(message: str, *, intent: str = "question", risk: str = "low") -> dict[str, object]:
    text = " ".join(message.strip().split())
    if not text:
        raise ValueError("message is required")
    if risk == "high":
        return {"reply": None, "requires_human": True, "source": "local-policy"}
    if intent == "feedback":
        reply = "感谢你的建议，我们会把这条反馈加入后续内容和产品迭代记录。"
    elif intent == "copyright":
        reply = "感谢提醒。我们会先核对来源、授权和发布记录，并由人工跟进处理。"
    else:
        reply = "感谢你的提问。可以先从一个主题、一个账号和人工审核流程开始，再逐步扩大范围。"
    return {"reply": reply, "requires_human": False, "source": "local-template"}
