import sqlite3
from uuid import uuid4

import pytest

from modules.audit import AuditError, AuditLogService


def test_audit_facts_and_query_export_evidence_survive_restart(tmp_path) -> None:
    path = tmp_path / "audit.db"
    org_id = uuid4()
    other = uuid4()
    service = AuditLogService(path)
    original = service.record(org_id=org_id, trace_id="trace-persist", actor_type="user",
        actor_id=uuid4(), action="workflow.start", subject_type="workflow_run",
        subject_id=uuid4(), input_payload={"step": 1}, idempotency_key="write")
    service.record(org_id=other, trace_id="trace-other", actor_type="system", actor_id=None,
        action="other", subject_type="job", idempotency_key="other")
    service.close()

    reopened = AuditLogService(path)
    rows = reopened.query(org_id=org_id, trace_id="trace-query", action="workflow.start",
        idempotency_key="query")
    assert rows == (original,)
    package = reopened.export(org_id=org_id, trace_id="trace-export", action="workflow.start",
        evidence_refs={"test": "tests/integration/test_audit_persistence.py"}, idempotency_key="export")
    assert package.record_ids == (original.id,)
    assert all(entry.org_id == org_id for entry in reopened.query(
        org_id=org_id, trace_id="trace-query", idempotency_key="all"))
    reopened.close()

    third = AuditLogService(path)
    assert third.query(org_id=org_id, trace_id="trace-query", action="workflow.start", idempotency_key="query") == rows
    assert third.export(org_id=org_id, trace_id="trace-export", action="workflow.start",
        evidence_refs={"test": "tests/integration/test_audit_persistence.py"}, idempotency_key="export") == package
    with pytest.raises(AuditError) as reused:
        third.query(org_id=org_id, trace_id="trace-query", action="different", idempotency_key="query")
    assert reused.value.code == "IDEMPOTENCY_KEY_REUSED"
    third.close()

    raw = sqlite3.connect(path)
    for command in (
        ("UPDATE audit_logs SET action = ? WHERE id = ?", ("altered", str(original.id))),
        ("DELETE FROM audit_logs WHERE id = ?", (str(original.id),)),
        ("DELETE FROM audit_commands WHERE org_id = ?", (str(org_id),)),
    ):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            raw.execute(*command)
    raw.close()
