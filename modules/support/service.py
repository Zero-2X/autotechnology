"""Fake/manual inbox, dedupe, intent classification and safe drafts."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from threading import RLock
from typing import Any, Mapping
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker

_ROOT = Path(__file__).resolve().parents[2]
_THREAD_SCHEMA = json.loads((_ROOT / "packages/contracts/jsonschema/support-thread.schema.json").read_text(encoding="utf-8"))
_MESSAGE_SCHEMA = json.loads((_ROOT / "packages/contracts/jsonschema/support-message.schema.json").read_text(encoding="utf-8"))
_THREAD_VALIDATOR = Draft202012Validator(_THREAD_SCHEMA, format_checker=FormatChecker())
_MESSAGE_VALIDATOR = Draft202012Validator(_MESSAGE_SCHEMA, format_checker=FormatChecker())
_HIGH_RISK = {"refund": ("退款", "refund", "退费"), "contract": ("合同", "contract", "agreement"), "medical": ("医疗", "medical", "medicine"), "legal": ("法律", "legal", "律师"), "financial": ("金融", "financial", "投资", "bank"), "kyc": ("kyc", "身份验证", "实名"), "appeal": ("申诉", "appeal", "投诉"), "copyright": ("版权", "copyright", "侵权"), "privacy": ("隐私", "privacy", "个人信息"), "security": ("安全漏洞", "security", "vulnerability", "泄露")}
_SENSITIVE_WORDS = ("refund", "guarantee", "退款", "保证", "法律意见", "medical advice", "医疗建议")


class SupportError(ValueError):
    def __init__(self, code: str, message: str) -> None: super().__init__(message); self.code = code


def _uuid(value: Any, field: str) -> str:
    try: return str(value if isinstance(value, UUID) else UUID(str(value)))
    except (TypeError, ValueError) as exc: raise SupportError("INVALID_SUPPORT_INPUT", f"{field} must be a UUID") from exc


def _text(value: Any, field: str, limit: int = 512) -> str:
    if not isinstance(value, str) or not value.strip(): raise SupportError("INVALID_SUPPORT_INPUT", f"{field} is required")
    value = value.strip()
    if len(value) > limit: raise SupportError("INVALID_SUPPORT_INPUT", f"{field} is too long")
    return value


def _stamp(value: Any) -> str:
    if not isinstance(value, datetime):
        try: value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc: raise SupportError("INVALID_SUPPORT_INPUT", "timestamp is invalid") from exc
    if value.tzinfo is None or value.utcoffset() is None: raise SupportError("INVALID_SUPPORT_INPUT", "timestamp needs timezone")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _hash(value: Any) -> str: return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class SupportInboxService:
    task_id = "SUP-001"

    def __init__(self, *, clock: Any | None = None) -> None:
        self.clock = clock or (lambda: datetime.now(timezone.utc)); self.threads: dict[tuple[str, str], dict[str, Any]] = {}; self.messages: dict[tuple[str, str], dict[str, Any]] = {}; self.drafts: dict[tuple[str, str], dict[str, Any]] = {}; self.commands: dict[tuple[str, str], dict[str, Any]] = {}; self.audit: list[dict[str, Any]] = []; self.outbox: list[dict[str, Any]] = []; self._lock = RLock()

    def _ctx(self, context: Mapping[str, Any]) -> tuple[str, str, str]: return _uuid(context.get("org_id"), "org_id"), _uuid(context.get("actor_id", "00000000-0000-4000-8000-000000000001"), "actor_id"), _text(context.get("trace_id", self.task_id), "trace_id", 256)

    def _classify(self, body: str) -> tuple[str, str, str | None]:
        lower = body.lower()
        for intent, terms in _HIGH_RISK.items():
            if any(term.lower() in lower for term in terms): return intent, "high", f"HIGH_RISK_{intent.upper()}"
        if any(term in lower for term in ("how", "what", "怎么", "如何", "吗", "?", "？")): return "question", "low", None
        if any(term in lower for term in ("bug", "error", "错误", "失败", "报错")): return "bug", "medium", None
        if any(term in lower for term in ("status", "进度", "状态")): return "status", "low", None
        if any(term in lower for term in ("feedback", "建议", "意见")): return "feedback", "low", None
        return "unknown", "medium", None

    def ingest(self, *, external_thread_id: Any, external_message_id: Any, body: Any, channel: str, source: str, context: Mapping[str, Any], idempotency_key: Any) -> dict[str, Any]:
        tenant, actor, trace = self._ctx(context); thread_ref, message_ref, text = _text(external_thread_id, "external_thread_id", 256), _text(external_message_id, "external_message_id", 256), _text(body, "body", 20000); key = _text(idempotency_key, "idempotency_key", 200)
        if channel not in {"comment", "message"} or source not in {"fake", "manual"}: raise SupportError("SOURCE_NOT_ALLOWED", "SUP accepts only fake/manual comment or message input")
        intent, risk, escalation = self._classify(text); message_hash = _hash(text); command_hash = _hash({"thread": thread_ref, "message": message_ref, "hash": message_hash, "channel": channel, "source": source})
        with self._lock:
            prior = self.commands.get((tenant, key))
            if prior:
                if prior["request_hash"] != command_hash: raise SupportError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
                return deepcopy(prior["response"])
            existing_message = next((v for (org, _), v in self.messages.items() if org == tenant and v["external_message_id"] == message_ref), None)
            if existing_message is not None:
                existing_thread = next((v for (org, _), v in self.threads.items() if org == tenant and v["id"] == existing_message["thread_id"]), None)
                response = {"thread": deepcopy(existing_thread), "message": deepcopy(existing_message), "draft": None, "send_blocked": True}
                self.commands[(tenant, key)] = {"request_hash": command_hash, "response": deepcopy(response)}; return response
            thread = self.threads.get((tenant, thread_ref)); now = _stamp(self.clock())
            if thread is None:
                thread = {"id": str(uuid4()), "org_id": tenant, "platform_id": None, "external_thread_id": thread_ref, "status": "escalated" if risk == "high" else "open", "created_at": now, "intent": intent, "risk_level": risk, "version": 1, "message_count": 0, "last_message_hash": None, "send_blocked": True, "escalation_reason": escalation}
            else:
                thread = deepcopy(thread); thread["version"] += 1; thread["status"] = "escalated" if risk == "high" else thread["status"]; thread["risk_level"] = "high" if risk == "high" else thread["risk_level"]; thread["escalation_reason"] = escalation or thread.get("escalation_reason")
            thread["message_count"] += 1; thread["last_message_hash"] = message_hash; _THREAD_VALIDATOR.validate(thread)
            message = {"id": str(uuid4()), "org_id": tenant, "thread_id": thread["id"], "channel": channel, "external_message_id": message_ref, "message_hash": message_hash, "source": source, "intent": intent, "risk_level": risk, "received_at": now}; _MESSAGE_VALIDATOR.validate(message)
            result = {"thread": deepcopy(thread), "message": deepcopy(message), "draft": None, "send_blocked": True}; self.threads[(tenant, thread_ref)] = deepcopy(thread); self.messages[(tenant, message["id"])] = deepcopy(message); self.commands[(tenant, key)] = {"request_hash": command_hash, "response": result}
            self.audit.append({"event_type": "support.message.ingested", "org_id": tenant, "actor_id": actor, "trace_id": trace, "thread_id": thread["id"], "message_id": message["id"], "message_hash": message_hash, "intent": intent, "risk_level": risk, "escalation_reason": escalation, "send_blocked": True, "created_at": now}); return deepcopy(result)

    ingest_message = ingest
    import_message = ingest

    def draft(self, *, thread_id: Any, text: Any = None, context: Mapping[str, Any], idempotency_key: Any) -> dict[str, Any]:
        tenant, actor, trace = self._ctx(context); identity = _uuid(thread_id, "thread_id"); key = _text(idempotency_key, "idempotency_key", 200)
        with self._lock:
            thread = next((v for (org, _), v in self.threads.items() if org == tenant and v["id"] == identity), None)
            if thread is None: raise SupportError("THREAD_NOT_FOUND", "support thread does not exist")
            if thread["risk_level"] == "high" or thread["status"] == "escalated": raise SupportError("HUMAN_REVIEW_REQUIRED", "high-risk thread cannot receive an automatic draft")
            body = _text(text if text is not None else ("Thanks for your question. We will review the details and follow up with the documented answer." if thread["intent"] == "question" else "Thanks for your feedback. We have recorded it for review."), "draft", 4000)
            if any(word in body.lower() for word in _SENSITIVE_WORDS): raise SupportError("DRAFT_CONTENT_BLOCKED", "draft contains a restricted commitment")
            result = {"id": str(uuid4()), "org_id": tenant, "thread_id": identity, "text": body, "status": "draft", "send_blocked": True, "created_at": _stamp(self.clock())}; digest = _hash({k: v for k, v in result.items() if k != "id"}); prior = self.commands.get((tenant, key))
            if prior:
                if prior["request_hash"] != digest: raise SupportError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
                return deepcopy(prior["response"])
            self.drafts[(tenant, result["id"])] = deepcopy(result); self.commands[(tenant, key)] = {"request_hash": digest, "response": deepcopy(result)}; self.audit.append({"event_type": "support.draft.created", "org_id": tenant, "actor_id": actor, "trace_id": trace, "thread_id": identity, "draft_hash": digest, "send_blocked": True, "created_at": result["created_at"]}); return deepcopy(result)

    create_draft = draft

    def send(self, *, draft_id: Any, context: Mapping[str, Any], idempotency_key: Any) -> dict[str, Any]: raise SupportError("SEND_DISABLED", "SUP has no send capability; route the draft to a human")

    def escalate(self, *, thread_id: Any, reason: Any, context: Mapping[str, Any], idempotency_key: Any) -> dict[str, Any]:
        tenant, actor, trace = self._ctx(context); identity = _uuid(thread_id, "thread_id"); reason = _text(reason, "reason", 1000); _text(idempotency_key, "idempotency_key", 200)
        with self._lock:
            found = next(((org, ref, value) for (org, ref), value in self.threads.items() if org == tenant and value["id"] == identity), None)
            if found is None: raise SupportError("THREAD_NOT_FOUND", "support thread does not exist")
            _, ref, thread = found; result = deepcopy(thread); result["status"] = "escalated"; result["risk_level"] = "high"; result["escalation_reason"] = reason; result["version"] += 1; self.threads[(tenant, ref)] = result; self.audit.append({"event_type": "support.thread.escalated", "org_id": tenant, "actor_id": actor, "trace_id": trace, "thread_id": identity, "reason": reason, "send_blocked": True, "created_at": _stamp(self.clock())}); return deepcopy(result)


FakeInboxService = SupportInboxService
SupportService = SupportInboxService

__all__ = ["SupportError", "SupportInboxService", "FakeInboxService", "SupportService"]
