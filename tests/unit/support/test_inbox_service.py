from uuid import uuid4

import pytest

from modules.support import SupportError, SupportInboxService


ORG, ACTOR = str(uuid4()), str(uuid4())
CTX = {"org_id": ORG, "actor_id": ACTOR, "trace_id": "support"}


def test_dedupes_messages_classifies_low_risk_and_blocks_send():
    service = SupportInboxService()
    first = service.ingest(external_thread_id="thread-1", external_message_id="message-1", body="How do I use this?", channel="comment", source="manual", context=CTX, idempotency_key="ingest-1")
    assert first["thread"]["risk_level"] == "low"
    duplicate = service.ingest(external_thread_id="thread-1", external_message_id="message-1", body="How do I use this?", channel="comment", source="manual", context=CTX, idempotency_key="ingest-2")
    assert duplicate["message"] == first["message"] and duplicate["thread"]["id"] == first["thread"]["id"]
    draft = service.draft(thread_id=first["thread"]["id"], context=CTX, idempotency_key="draft-1")
    assert draft["send_blocked"] is True
    with pytest.raises(SupportError) as error:
        service.send(draft_id=draft["id"], context=CTX, idempotency_key="send")
    assert error.value.code == "SEND_DISABLED"


def test_high_risk_is_escalated_and_draft_rejected():
    service = SupportInboxService()
    result = service.ingest(external_thread_id="thread-2", external_message_id="message-2", body="I need a refund and legal advice", channel="message", source="fake", context=CTX, idempotency_key="ingest-2")
    assert result["thread"]["status"] == "escalated" and result["message"]["intent"] == "refund"
    with pytest.raises(SupportError) as error:
        service.draft(thread_id=result["thread"]["id"], context=CTX, idempotency_key="draft-2")
    assert error.value.code == "HUMAN_REVIEW_REQUIRED"


def test_cross_source_and_tenant_rejected():
    service = SupportInboxService()
    with pytest.raises(SupportError) as error:
        service.ingest(external_thread_id="t", external_message_id="m", body="hello", channel="comment", source="platform", context=CTX, idempotency_key="bad")
    assert error.value.code == "SOURCE_NOT_ALLOWED"
    other = service.ingest(external_thread_id="t", external_message_id="m", body="hello", channel="comment", source="manual", context={"org_id": str(uuid4()), "actor_id": ACTOR}, idempotency_key="bad2")
    assert other["thread"]["org_id"] != ORG
