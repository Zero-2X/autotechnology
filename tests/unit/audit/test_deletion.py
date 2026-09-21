from uuid import uuid4

import pytest

from modules.audit import AuditLogService, DeletionError, DeletionPropagationService, STAGES


def test_deletion_propagation_completes_all_stages_idempotently() -> None:
    audit = AuditLogService()
    service = DeletionPropagationService(audit_log=audit)
    org_id = uuid4()
    request = service.request(org_id=org_id, subject_type="canonical_content", subject_id=uuid4(),
                              requested_by=uuid4(), idempotency_key="delete-1", trace_id="trace-d1")
    outcomes = {stage: True for stage in STAGES}
    completed = service.process_all(org_id=org_id, request_id=request.id, outcomes=outcomes,
                                    expected_version=request.version, idempotency_key="run-1", trace_id="trace-d1")
    repeated = service.process_all(org_id=org_id, request_id=request.id, outcomes=outcomes,
                                   expected_version=request.version, idempotency_key="run-1", trace_id="trace-d1")
    assert completed == repeated
    assert completed.status == "completed"
    assert all(service.stages[(request.id, stage)].status == "completed" for stage in STAGES)
    assert audit.metric("audit_records_total") == 6


def test_failed_stage_creates_one_manual_review_task_and_redacts_error() -> None:
    service = DeletionPropagationService()
    org_id = uuid4()
    request = service.request(org_id=org_id, subject_type="asset", subject_id=uuid4(),
                              requested_by=uuid4(), idempotency_key="delete-2", trace_id="trace-d2")
    failed = service.process_stage(org_id=org_id, request_id=request.id, stage="vector", success=False,
                                   error="provider token=secret-value\ntransient", expected_version=request.version,
                                   idempotency_key="stage-1", trace_id="trace-d2")
    assert failed.status == "failed"
    tasks = tuple(service.manual_tasks.values())
    assert len(tasks) == 1
    assert "secret-value" not in tasks[0].reason
    assert "REDACTED" in tasks[0].reason
    with pytest.raises(DeletionError) as error:
        service.process_stage(org_id=org_id, request_id=request.id, stage="cache", success=True,
                              expected_version=request.version, idempotency_key="stage-2", trace_id="trace-d2",
                              evidence_ref="synthetic://cache")
    assert error.value.code == "VERSION_CONFLICT"


def test_manual_resolution_and_cross_tenant_access_are_guarded() -> None:
    service = DeletionPropagationService()
    org_id = uuid4()
    request = service.request(org_id=org_id, subject_type="export_package", subject_id=uuid4(),
                              requested_by=uuid4(), idempotency_key="delete-3", trace_id="trace-d3")
    service.process_stage(org_id=org_id, request_id=request.id, stage="export", success=False, error="offline",
                          expected_version=request.version, idempotency_key="stage-3", trace_id="trace-d3")
    task = next(iter(service.manual_tasks.values()))
    with pytest.raises(DeletionError) as error:
        service.resolve_manual_task(org_id=uuid4(), task_id=task.id, success=True, expected_version=task.version,
                                    idempotency_key="resolve-other", trace_id="trace-d3")
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    resolved = service.resolve_manual_task(org_id=org_id, task_id=task.id, success=True,
                                           expected_version=task.version, idempotency_key="resolve-1", trace_id="trace-d3")
    assert resolved.status == "running"
    assert service.manual_tasks[task.id].status == "resolved"
    with pytest.raises(DeletionError) as conflict:
        service.resolve_manual_task(org_id=org_id, task_id=task.id, success=True,
            expected_version=task.version, idempotency_key="resolve-other", trace_id="trace-d3")
    assert conflict.value.code == "VERSION_CONFLICT"


def test_propagation_confirms_independent_target_absence_and_queues_failure() -> None:
    class Target:
        def __init__(self, *, fails: bool = False) -> None:
            self.fails = fails
            self.exists = True

        def delete(self, **_kwargs) -> str:
            if not self.fails:
                self.exists = False
            return "synthetic://deletion-proof"

        def absent(self, **_kwargs) -> bool:
            return not self.exists

    service = DeletionPropagationService()
    org_id = uuid4()
    requested = service.request(org_id=org_id, subject_type="asset", subject_id=uuid4(),
        requested_by=uuid4(), idempotency_key="create-propagation", trace_id="trace-propagation")
    targets = {stage: Target(fails=stage == "vector_index") for stage in STAGES}
    result = service.propagate(org_id=org_id, request_id=requested.id, targets=targets,
        idempotency_key="run-propagation", trace_id="trace-propagation")
    assert result.status == "partially_completed"
    assert result.completed_at is None
    assert service.stages[(requested.id, "vector_index")].status == "failed"
    assert len(service.manual_tasks) == 1
    assert all(service.stages[(requested.id, name)].evidence_ref for name in STAGES if name != "vector_index")
