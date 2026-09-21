from datetime import datetime, timezone
from uuid import uuid4

import pytest

from modules.audit import AuditError, AuditLogService, validate_audit_log


def test_record_is_schema_valid_append_only_and_idempotent() -> None:
    service = AuditLogService()
    org_id = uuid4()
    actor_id = uuid4()
    first = service.record(
        org_id=org_id,
        trace_id="trace-a",
        actor_type="user",
        actor_id=actor_id,
        action="workflow.start",
        subject_type="workflow_run",
        subject_id=uuid4(),
        input_payload={"workflow": "demo"},
        idempotency_key="audit-1",
        created_at=datetime(2026, 9, 18, tzinfo=timezone.utc),
    )
    assert service.record(
        org_id=org_id,
        trace_id=first.trace_id,
        actor_type=first.actor_type,
        actor_id=actor_id,
        action=first.action,
        subject_type=first.subject_type,
        subject_id=first.subject_id,
        input_hash=first.input_hash,
        idempotency_key="audit-1",
    ) == first
    assert len(service.entries) == 1
    validate_audit_log(first.as_contract())
    with pytest.raises(AttributeError):
        service.entries.append(first)  # type: ignore[attr-defined]


def test_tenant_scope_and_payload_reuse_are_rejected() -> None:
    service = AuditLogService()
    org_id = uuid4()
    entry = service.record(
        org_id=org_id,
        trace_id="trace-b",
        actor_type="system",
        actor_id=None,
        action="policy.evaluate",
        subject_type="policy_decision",
        idempotency_key="audit-2",
    )
    with pytest.raises(AuditError) as error:
        service.get(org_id=uuid4(), entry_id=entry.id, trace_id="lookup", idempotency_key="lookup")
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    with pytest.raises(AuditError) as error:
        service.record(
            org_id=org_id,
            trace_id="trace-other",
            actor_type="system",
            actor_id=None,
            action="policy.changed",
            subject_type="policy_decision",
            idempotency_key="audit-2",
        )
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"


def test_query_and_export_create_audit_records_and_evidence_refs() -> None:
    service = AuditLogService()
    org_id = uuid4()
    service.record(
        org_id=org_id, trace_id="trace-c", actor_type="worker", actor_id=None,
        action="workflow.complete", subject_type="workflow_run", idempotency_key="audit-3",
    )
    rows = service.query(org_id=org_id, trace_id="trace-c", idempotency_key="query-1", action="workflow.complete")
    package = service.export(
        org_id=org_id, trace_id="trace-c", idempotency_key="export-1",
        action="workflow.complete", evidence_refs={"test": "evidence/obs-core-001.yaml"},
    )
    assert len(rows) == 1
    assert package.record_ids == (rows[0].id,)
    assert package.evidence_refs == (("test", "evidence/obs-core-001.yaml"),)
    assert [item.action for item in service.entries[-2:]] == ["audit.query", "audit.export"]
    assert service.metric("audit_queries_total") == 1
    assert service.metric("audit_exports_total") == 1


def test_query_and_export_idempotency_are_stable() -> None:
    service = AuditLogService()
    org_id = uuid4()
    service.record(
        org_id=org_id, trace_id="trace-d", actor_type="service", actor_id=None,
        action="job.run", subject_type="task_job", idempotency_key="audit-4",
    )
    first = service.query(org_id=org_id, trace_id="trace-d", idempotency_key="query-2")
    second = service.query(org_id=org_id, trace_id="trace-d", idempotency_key="query-2")
    assert first == second
    exported = service.export(org_id=org_id, trace_id="trace-d", idempotency_key="export-2")
    assert service.export(org_id=org_id, trace_id="trace-d", idempotency_key="export-2") == exported
