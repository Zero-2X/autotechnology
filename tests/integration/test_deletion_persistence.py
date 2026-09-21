from uuid import uuid4

from modules.audit import AuditLogService, DeletionPropagationService


def test_failed_deletion_and_manual_queue_survive_restart(tmp_path) -> None:
    path = tmp_path / "deletions.db"
    audit = AuditLogService(tmp_path / "audit.db")
    org_id = uuid4()
    first = DeletionPropagationService(database=path, audit_log=audit)
    requested = first.request(org_id=org_id, subject_type="asset", subject_id=uuid4(),
        requested_by=uuid4(), idempotency_key="create", trace_id="trace-delete")
    failed = first.process_stage(org_id=org_id, request_id=requested.id, stage="object_storage",
        success=False, error="token=hidden-value unavailable", expected_version=0,
        idempotency_key="stage-failed", trace_id="trace-delete")
    task = next(iter(first.manual_tasks.values()))
    first.close()

    second = DeletionPropagationService(database=path, audit_log=audit)
    assert second.requests[requested.id] == failed
    assert second.request(org_id=org_id, subject_type="asset", subject_id=requested.subject_id,
        requested_by=requested.requested_by, idempotency_key="create", trace_id="trace-delete") == requested
    assert second.manual_tasks[task.id] == task
    assert "hidden-value" not in task.reason
    resolved = second.resolve_manual_task(org_id=org_id, task_id=task.id, success=True,
        expected_version=task.version, idempotency_key="resolve", trace_id="trace-delete")
    assert resolved.status == "running"
    second.close()

    third = DeletionPropagationService(database=path, audit_log=audit)
    assert third.manual_tasks[task.id].status == "resolved"
    assert third.stages[(requested.id, "object_storage")].status == "completed"
    third.close()
    audit.close()
