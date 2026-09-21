from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from modules.qa import ExecutionResult, QAError, SandboxService


IMAGE = "a" * 64


class FakeExecutor:
    def __init__(self, result: ExecutionResult) -> None:
        self.result = result
        self.calls: list[tuple[tuple[str, ...], str, int]] = []

    def run(self, argv, *, cwd, env, timeout_ms):
        self.calls.append((tuple(argv), cwd, timeout_ms))
        return self.result


def _args(service: SandboxService, *, key: str = "sandbox-1", org_id: str | None = None,
          actor_id: str | None = None, **kwargs):
    tenant, actor = org_id or str(uuid4()), actor_id or str(uuid4())
    return service.run(
        org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key=key,
        commands=[["python", "main.py"]], image_digest=IMAGE,
        workspace_files={"main.py": "print('ok')", "requirements.lock": "demo==1.0"},
        dependency_lock_hash=hashlib.sha256(b"demo==1.0").hexdigest(), **kwargs,
    )


def test_sandbox_runs_allowlisted_argv_and_reuses_reproducible_cache() -> None:
    executor = FakeExecutor(ExecutionResult(0, b"ok\n", b""))
    service = SandboxService(executor=executor)
    tenant, actor = str(uuid4()), str(uuid4())
    first = _args(service, org_id=tenant, actor_id=actor)
    assert first["status"] == "passed"
    assert first["reproducible"] is False
    assert first["stdout_ref"].startswith("private://")
    assert service.evidence[first["stdout_ref"]]["size"] == 3
    schema = json.loads((Path(__file__).resolve().parents[3] /
                         "packages/contracts/jsonschema/sandbox-run.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(first)
    assert _args(service, org_id=tenant, actor_id=actor) == first
    cached = _args(service, key="sandbox-2", org_id=tenant, actor_id=actor)
    assert cached["reproducible"] is True
    assert cached["id"] == first["id"]
    assert len(executor.calls) == 1


def test_sandbox_blocks_shell_network_and_secret_paths_without_starting_process() -> None:
    executor = FakeExecutor(ExecutionResult(0))
    service = SandboxService(executor=executor)
    base = dict(org_id=str(uuid4()), actor_id=str(uuid4()), trace_id="trace", image_digest=IMAGE)
    blocked = service.run(**base, idempotency_key="blocked-1", commands=[["curl.exe", "https://example.test"]])
    assert blocked["status"] == "blocked"
    assert executor.calls == []
    with pytest.raises(QAError) as error:
        service.run(**base, idempotency_key="lock-bad", commands=[["python", "main.py"]],
                    workspace_files={"requirements.lock": "demo==1.0"}, dependency_lock_hash="b" * 64)
    assert error.value.code == "DEPENDENCY_LOCK_MISMATCH"
    with pytest.raises(QAError) as error:
        service.run(**base, idempotency_key="secret-path", commands=[["python", "secret.txt"]],
                    workspace_files={"secret.txt": "nope"})
    assert error.value.code == "WORKSPACE_PATH_BLOCKED"
    with pytest.raises(QAError) as error:
        service.run(**base, idempotency_key="network-source", commands=[["python", "main.py"]],
                    workspace_files={"main.py": "import socket"})
    assert error.value.code == "WORKSPACE_CONTENT_BLOCKED"


def test_sandbox_records_failure_timeout_and_resource_admission() -> None:
    failed = SandboxService(executor=FakeExecutor(ExecutionResult(2, b"", b"bad")))
    assert _args(failed)["status"] == "failed"
    timed_out = SandboxService(executor=FakeExecutor(ExecutionResult(-1, timed_out=True)))
    assert _args(timed_out)["status"] == "timed_out"
    limited = SandboxService(executor=FakeExecutor(ExecutionResult(0)))
    result = _args(limited, key="limited", timeout_ms=limited.max_timeout_ms + 1)
    assert result["status"] == "blocked"
    assert limited.audit[-1]["blocked_reason"] == "resource limit exceeds sandbox maximum"


def test_sandbox_idempotency_rejects_changed_commands() -> None:
    service = SandboxService(executor=FakeExecutor(ExecutionResult(0)))
    _args(service, key="same")
    with pytest.raises(QAError) as error:
        service.run(org_id=service.audit[0]["org_id"], actor_id=service.audit[0]["actor_id"], trace_id="trace",
                    idempotency_key="same", commands=[["python", "other.py"]], image_digest=IMAGE,
                    workspace_files={"other.py": "print('different')"})
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"
