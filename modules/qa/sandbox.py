"""Local, deterministic sandbox admission and execution for QA-003."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePath
import re
import subprocess
import tempfile
from threading import RLock
from time import monotonic
from typing import Any, Mapping, Protocol, Sequence
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker

from .service import QAError, _hash, _stamp, _text, _uuid


_ROOT = Path(__file__).resolve().parents[2]
_RUN_VALIDATOR = Draft202012Validator(
    json.loads((_ROOT / "packages/contracts/jsonschema/sandbox-run.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
_SHA256 = re.compile(r"^[A-Fa-f0-9]{64}$")
_SHELL_OPERATOR = re.compile(r"(?:&&|\|\||[;|><`&]|\$\(|\r|\n)")
_NETWORK_COMMAND = re.compile(r"(?i)(?:^|[\s\\/])(?:curl|wget|invoke-webrequest|iwr|nc|ncat|netcat|ssh|scp|ftp|telnet)(?:\.exe)?(?:$|[\s\\/])")
_NETWORK_MODULE = re.compile(r"(?i)(?:urllib|requests|socket|http\.client|ftplib|paramiko)")
_DANGEROUS_PATH = re.compile(r"(?i)(?:secret|token|\.pem|deploy[\\/]environments[\\/]prod|[\\/]prod(?:[\\/]|$))")
_SECRET_CONTENT = re.compile(r"(?i)(?:-----begin [^-]*private key-----|aws_secret_access_key|github_token|openai_api_key)")
_LOCK_NAMES = {"requirements.lock", "poetry.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "cargo.lock", "go.sum"}


@dataclass(frozen=True)
class ExecutionResult:
    returncode: int
    stdout: bytes = b""
    stderr: bytes = b""
    timed_out: bool = False


class CommandExecutor(Protocol):
    def run(self, argv: Sequence[str], *, cwd: str, env: Mapping[str, str], timeout_ms: int) -> ExecutionResult: ...


class SubprocessExecutor:
    """Small subprocess adapter; all admission checks happen before it is called."""

    def run(self, argv: Sequence[str], *, cwd: str, env: Mapping[str, str], timeout_ms: int) -> ExecutionResult:
        try:
            completed = subprocess.run(
                list(argv), cwd=cwd, env=dict(env), shell=False, capture_output=True,
                timeout=timeout_ms / 1000, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, bytes) else (exc.stdout or "").encode()
            stderr = exc.stderr if isinstance(exc.stderr, bytes) else (exc.stderr or "").encode()
            return ExecutionResult(returncode=-1, stdout=stdout, stderr=stderr, timed_out=True)
        return ExecutionResult(completed.returncode, completed.stdout or b"", completed.stderr or b"")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise QAError("INVALID_SANDBOX_INPUT", "workspace file path must be nonempty text")
    path = value.replace("\\", "/")
    pure = PurePath(path)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise QAError("WORKSPACE_PATH_BLOCKED", "workspace file path must stay relative")
    if _DANGEROUS_PATH.search(path):
        raise QAError("WORKSPACE_PATH_BLOCKED", "secret, token, pem, or production path is forbidden")
    return "/".join(pure.parts)


def _bytes(value: object, name: str) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    raise QAError("INVALID_SANDBOX_INPUT", f"{name} must be UTF-8 text or bytes")


class SandboxService:
    """Admit and execute a bounded command set in a disposable private workspace."""

    rule_version = "qa-003/v1"
    default_allowlist = frozenset({"pytest", "ruff", "mypy", "python"})
    max_cpu_ms = 600_000
    max_memory_mb = 2_048
    max_timeout_ms = 120_000

    def __init__(self, *, executor: CommandExecutor | None = None,
                 allowed_commands: Sequence[str] | None = None) -> None:
        self.executor = executor or SubprocessExecutor()
        self.allowed_commands = frozenset(str(item).casefold() for item in (allowed_commands or self.default_allowlist))
        if not self.allowed_commands:
            raise QAError("INVALID_SANDBOX_POLICY", "allowed_commands must not be empty")
        self.audit: list[dict[str, Any]] = []
        self.evidence: dict[str, dict[str, Any]] = {}
        self._results: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
        self._cache: dict[tuple[str, str, tuple[tuple[str, ...], ...]], dict[str, Any]] = {}
        self._lock = RLock()

    def _command_reason(self, command: Sequence[str], allowed: frozenset[str]) -> str | None:
        if not isinstance(command, (list, tuple)) or not command or any(not isinstance(item, str) or not item for item in command):
            return "structured argv is required"
        joined = " ".join(command)
        if _SHELL_OPERATOR.search(joined):
            return "shell operator is forbidden"
        if _NETWORK_COMMAND.search(joined) or _NETWORK_MODULE.search(joined):
            return "network command or module is forbidden"
        if _DANGEROUS_PATH.search(joined):
            return "secret, token, pem, or production path is forbidden"
        executable = Path(command[0].replace("\\", "/")).name.casefold()
        if executable not in allowed:
            return f"command {executable!r} is not allowlisted"
        return None

    @staticmethod
    def _minimal_env() -> dict[str, str]:
        keep = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR"}
        environment = {key: value for key, value in os.environ.items() if key.upper() in keep}
        environment["PYTHONNOUSERSITE"] = "1"
        return environment

    def run(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        commands: Sequence[Sequence[str]], image_digest: str, workspace_files: Mapping[str, str | bytes] | None = None,
        allowlisted_commands: Sequence[str] | None = None, cpu_ms: int = 60_000,
        memory_mb: int = 512, timeout_ms: int = 30_000, dependency_lock_hash: str | None = None,
    ) -> dict[str, Any]:
        tenant = _uuid(org_id, "org_id")
        actor = _uuid(actor_id, "actor_id")
        trace = _text(trace_id, "trace_id")
        key = _text(idempotency_key, "idempotency_key", 200)
        if not isinstance(commands, (list, tuple)) or not commands:
            raise QAError("INVALID_SANDBOX_INPUT", "commands must be a nonempty argv list")
        if not isinstance(image_digest, str) or not _SHA256.fullmatch(image_digest):
            raise QAError("INVALID_SANDBOX_INPUT", "image_digest must be a SHA-256 hex digest")
        if type(cpu_ms) is not int or type(memory_mb) is not int or type(timeout_ms) is not int or min(cpu_ms, memory_mb, timeout_ms) <= 0:
            raise QAError("INVALID_SANDBOX_LIMITS", "resource limits must be positive integers")
        allowed = frozenset(str(item).casefold() for item in (allowlisted_commands or self.allowed_commands))
        if not allowed or not allowed <= self.allowed_commands:
            raise QAError("INVALID_SANDBOX_POLICY", "task allowlist must be a subset of the service allowlist")
        if workspace_files is not None and not isinstance(workspace_files, Mapping):
            raise QAError("INVALID_SANDBOX_INPUT", "workspace_files must be an object")
        files = dict(workspace_files or {})
        normalized_files: dict[str, bytes] = {}
        for raw_path, content in files.items():
            path = _safe_relative_path(raw_path)
            normalized_files[path] = _bytes(content, f"workspace_files[{path}]")
        for path, content in normalized_files.items():
            if Path(path).name.casefold() in _LOCK_NAMES:
                continue
            try:
                source = content.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if _SECRET_CONTENT.search(source):
                raise QAError("WORKSPACE_CONTENT_BLOCKED", "secret material is forbidden in the sandbox workspace")
            if _NETWORK_MODULE.search(source):
                raise QAError("WORKSPACE_CONTENT_BLOCKED", "network modules are forbidden in the sandbox workspace")
        if dependency_lock_hash is not None and not _SHA256.fullmatch(dependency_lock_hash):
            raise QAError("INVALID_SANDBOX_INPUT", "dependency_lock_hash must be a SHA-256 hex digest")
        lock_paths = [path for path in normalized_files if Path(path).name.casefold() in _LOCK_NAMES]
        if dependency_lock_hash is not None:
            if not lock_paths:
                raise QAError("DEPENDENCY_LOCK_MISSING", "dependency lock hash supplied without a lock file")
            actual_lock_hash = (_sha(normalized_files[lock_paths[0]]) if len(lock_paths) == 1 else
                                _sha(b"".join(path.encode() + b"\0" + normalized_files[path] for path in sorted(lock_paths))))
            if actual_lock_hash.casefold() != dependency_lock_hash.casefold():
                raise QAError("DEPENDENCY_LOCK_MISMATCH", "dependency lock hash does not match workspace lock file")
        command_set = tuple(tuple(command) if isinstance(command, (list, tuple)) else (repr(command),) for command in commands)
        argv_list: list[tuple[str, ...]] = []
        blocked_reason: str | None = None
        for command in commands:
            reason = self._command_reason(command, allowed)
            if reason is not None:
                blocked_reason = reason
                break
            argv_list.append(tuple(command))
        input_hash = _hash({"files": {path: _sha(normalized_files[path]) for path in sorted(normalized_files)},
                            "dependency_lock_hash": dependency_lock_hash})
        request_hash = _hash({"input_hash": input_hash, "image_digest": image_digest, "commands": command_set,
                              "allowlisted_commands": sorted(allowed), "cpu_ms": cpu_ms, "memory_mb": memory_mb,
                              "timeout_ms": timeout_ms})
        with self._lock:
            prior = self._results.get((tenant, key))
            if prior is not None:
                if prior[0] != request_hash:
                    raise QAError("IDEMPOTENCY_KEY_REUSED", "sandbox request differs from prior request")
                return deepcopy(prior[1])
            run_id = str(uuid4())
            created_at = _stamp(datetime.now(timezone.utc))
            run: dict[str, Any] = {
                "id": run_id, "org_id": tenant, "input_hash": input_hash,
                "workspace_ref": f"private://sandbox/{run_id}", "image_digest": image_digest,
                "allowlisted_commands": sorted(allowed), "network": "none", "secret_mounts": [],
                "cpu_ms": cpu_ms, "memory_mb": memory_mb, "timeout_ms": timeout_ms,
                "reproducible": False, "status": "queued", "stdout_ref": None, "stderr_ref": None,
                "created_at": created_at,
            }
            if blocked_reason is not None:
                run["status"] = "blocked"
                self._record(run, actor, trace, key, request_hash, blocked_reason=blocked_reason)
                return deepcopy(run)
            if cpu_ms > self.max_cpu_ms or memory_mb > self.max_memory_mb or timeout_ms > self.max_timeout_ms:
                run["status"] = "blocked"
                self._record(run, actor, trace, key, request_hash, blocked_reason="resource limit exceeds sandbox maximum")
                return deepcopy(run)
            cache_key = (tenant, input_hash, image_digest, command_set)
            cached = self._cache.get(cache_key)
            if cached is not None:
                run = deepcopy(cached)
                run["reproducible"] = True
                self._record(run, actor, trace, key, request_hash, cache_hit=True)
                return deepcopy(run)
            run["status"] = "running"
            stdout = bytearray()
            stderr = bytearray()
            status = "passed"
            returncode = 0
            started = monotonic()
            with tempfile.TemporaryDirectory(prefix="qa-sandbox-") as workspace:
                for relative_path, content in normalized_files.items():
                    destination = Path(workspace, *relative_path.split("/"))
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(content)
                environment = self._minimal_env()
                for command in argv_list:
                    elapsed_ms = int((monotonic() - started) * 1000)
                    remaining_ms = timeout_ms - elapsed_ms
                    if remaining_ms <= 0:
                        status, returncode = "timed_out", -1
                        break
                    result = self.executor.run(command, cwd=workspace, env=environment, timeout_ms=remaining_ms)
                    stdout.extend(result.stdout)
                    stderr.extend(result.stderr)
                    returncode = result.returncode
                    if result.timed_out:
                        status = "timed_out"
                        break
                    if result.returncode != 0:
                        status = "failed"
                        break
            run["status"] = status
            if stdout:
                ref = f"private://sandbox/{run_id}/stdout"
                run["stdout_ref"] = ref
                self.evidence[ref] = {"sha256": _sha(bytes(stdout)), "size": len(stdout)}
            if stderr:
                ref = f"private://sandbox/{run_id}/stderr"
                run["stderr_ref"] = ref
                self.evidence[ref] = {"sha256": _sha(bytes(stderr)), "size": len(stderr)}
            self._cache[cache_key] = deepcopy(run)
            self._record(run, actor, trace, key, request_hash, returncode=returncode,
                         stdout_hash=_sha(bytes(stdout)), stderr_hash=_sha(bytes(stderr)))
            return deepcopy(run)

    def _record(self, run: Mapping[str, Any], actor: str, trace: str, key: str, request_hash: str,
                *, blocked_reason: str | None = None, cache_hit: bool = False, returncode: int | None = None,
                stdout_hash: str | None = None, stderr_hash: str | None = None) -> None:
        event: dict[str, Any] = {"event_type": "qa.sandbox_run.created", "org_id": run["org_id"],
                                 "actor_id": actor, "trace_id": trace, "idempotency_key": key,
                                 "input_hash": run["input_hash"], "request_hash": request_hash,
                                 "run_id": run["id"], "status": run["status"], "cache_hit": cache_hit,
                                 "output_hash": _hash(dict(run))}
        if blocked_reason is not None:
            event["blocked_reason"] = blocked_reason
        if returncode is not None:
            event["returncode"] = returncode
        if stdout_hash is not None:
            event["stdout_hash"] = stdout_hash
        if stderr_hash is not None:
            event["stderr_hash"] = stderr_hash
        errors = list(_RUN_VALIDATOR.iter_errors(dict(run)))
        if errors:
            raise QAError("INVALID_SANDBOX_RUN", errors[0].message)
        self.audit.append(event)
        self._results[(str(run["org_id"]), key)] = (request_hash, deepcopy(dict(run)))


__all__ = ["CommandExecutor", "ExecutionResult", "SandboxService", "SubprocessExecutor"]
