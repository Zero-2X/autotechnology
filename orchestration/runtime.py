"""GraphRun execution, lease, pause, interruption and replay semantics."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import inspect
import json
from threading import RLock
from typing import Any, Mapping
from uuid import UUID, uuid4

from packages.observability import TraceLedger

from .checkpoint import Checkpoint, Checkpointer, InMemoryCheckpointer
from .errors import GraphError, GraphInterrupt
from .registry import GraphDefinition, GraphRegistry
from .state import StateViolation, state_hash, validate_state


def _stamp(value: datetime | None = None) -> str:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _uid(value: Any, field: str) -> str:
    try:
        return str(value if isinstance(value, UUID) else UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise GraphError("TENANT_CONTEXT_INVALID", f"{field} must be a UUID") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


@dataclass(frozen=True)
class GraphRun:
    id: str
    org_id: str
    actor_id: str
    graph_key: str
    workflow_version: int
    status: str
    input_hash: str
    trace_id: str
    idempotency_key: str
    current_node: str | None = None
    result_refs: dict[str, str] = field(default_factory=dict)
    error_ref: str | None = None
    human_interrupt_ref: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def as_contract(self) -> dict[str, Any]:
        return {"id": self.id, "org_id": self.org_id, "actor_id": self.actor_id,
                "workflow_key": self.graph_key, "workflow_version": self.workflow_version,
                "status": self.status, "input_hash": self.input_hash, "trace_id": self.trace_id,
                "idempotency_key": self.idempotency_key, "current_node": self.current_node,
                "result_refs": dict(self.result_refs), "error_ref": self.error_ref,
                "human_interrupt_ref": self.human_interrupt_ref,
                "created_at": self.created_at, "updated_at": self.updated_at}


@dataclass(frozen=True)
class GraphAttempt:
    id: str
    run_id: str
    attempt_no: int
    status: str
    started_at: str
    finished_at: str | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class NodeExecution:
    id: str
    run_id: str
    node: str
    sequence: int
    status: str
    input_hash: str
    output_hash: str | None = None
    error_code: str | None = None
    started_at: str = ""
    finished_at: str | None = None


class GraphRunner:
    """Run registered graphs while keeping business facts outside checkpoints."""

    def __init__(self, registry: GraphRegistry, *, checkpointer: Checkpointer | None = None,
                 ledger: TraceLedger | None = None, clock: Any | None = None,
                 lease_seconds: int = 300, max_steps: int = 64,
                 kill_switch: Any | None = None) -> None:
        if lease_seconds < 1 or max_steps < 1:
            raise ValueError("lease_seconds and max_steps must be positive")
        self.registry = registry
        self.checkpointer = checkpointer or InMemoryCheckpointer()
        self.ledger = ledger or TraceLedger(clock=clock)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.lease_seconds, self.max_steps = lease_seconds, max_steps
        self.kill_switch = kill_switch
        self.runs: dict[str, GraphRun] = {}
        self.attempts: dict[str, list[GraphAttempt]] = {}
        self.nodes: list[NodeExecution] = []
        self.commands: dict[tuple[str, str], tuple[str, str]] = {}
        self.audit: list[dict[str, Any]] = []
        self.outbox: list[dict[str, Any]] = []
        self.resume_commands: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
        self._leases: dict[str, tuple[str, datetime]] = {}
        self._lock = RLock()

    def run(self, *, org_id: UUID | str, actor_id: UUID | str, graph_key: str,
            input_refs: Mapping[str, str], idempotency_key: str, trace_id: str,
            workflow_version: int | None = None, context: Mapping[str, Any] | None = None,
            run_id: UUID | str | None = None) -> dict[str, Any]:
        tenant, actor = _uid(org_id, "org_id"), _uid(actor_id, "actor_id")
        self._text(idempotency_key, "idempotency_key")
        self._text(trace_id, "trace_id")
        if not isinstance(input_refs, Mapping) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in input_refs.items()):
            raise GraphError("GRAPH_INPUT_INVALID", "input_refs must be a string-to-string reference map")
        if any(k.lower() in {"token", "secret", "password", "body", "prompt"} for k in input_refs):
            raise GraphError("SENSITIVE_STATE_REJECTED", "input_refs contains a sensitive key")
        definition = self.registry.resolve(graph_key, workflow_version)
        normalized_input = definition.validate_input(input_refs)
        digest = _digest({"graph_key": definition.graph_key, "workflow_version": definition.workflow_version,
                          "input_refs": normalized_input})
        command_key = (tenant, idempotency_key)
        with self._lock:
            prior = self.commands.get(command_key)
            if prior:
                if prior[0] != digest:
                    raise GraphError("IDEMPOTENCY_KEY_REUSED", "graph command differs from prior request")
                return self.runs[prior[1]].as_contract()
            identity = str(run_id or uuid4())
            _uid(identity, "run_id")
            now = _stamp(self._clock())
            run = GraphRun(identity, tenant, actor, definition.graph_key, definition.workflow_version, "running",
                           digest, trace_id, idempotency_key, created_at=now, updated_at=now)
            self.runs[identity] = run
            self.commands[command_key] = (digest, identity)
            self.attempts[identity] = [GraphAttempt(str(uuid4()), identity, 1, "running", now)]
            self._audit("graph.run.started", run, {"graph_key": definition.graph_key, "workflow_version": definition.workflow_version})
        state = {
            "run_id": identity, "org_id": tenant, "actor_id": actor,
            "workflow_key": definition.graph_key, "workflow_version": definition.workflow_version,
            "input_refs": dict(normalized_input), "artifact_refs": {}, "evidence_refs": [], "qa_refs": [],
            "idempotency_key": idempotency_key, "trace_id": trace_id, "status": "running",
            "state_version": definition.state_version,
        }
        return self._execute(run_id=identity, definition=definition, state=state, context=context or {}, attempt_no=1)

    def resume(self, *, org_id: UUID | str, actor_id: UUID | str, run_id: UUID | str,
               idempotency_key: str, trace_id: str, decision: Mapping[str, Any] | None = None,
               context: Mapping[str, Any] | None = None) -> dict[str, Any]:
        tenant, actor, identity = _uid(org_id, "org_id"), _uid(actor_id, "actor_id"), _uid(run_id, "run_id")
        self._text(idempotency_key, "idempotency_key"); self._text(trace_id, "trace_id")
        resume_digest = _digest({"run_id": identity, "decision": dict(decision or {})})
        prior_resume = self.resume_commands.get((tenant, idempotency_key))
        if prior_resume:
            if prior_resume[0] != resume_digest:
                raise GraphError("IDEMPOTENCY_KEY_REUSED", "resume command differs from prior request")
            return deepcopy(prior_resume[1])
        run = self.runs.get(identity)
        if run is None or run.org_id != tenant:
            raise GraphError("GRAPH_RUN_NOT_FOUND", "run is not available in organization")
        if run.actor_id != actor:
            raise GraphError("FORBIDDEN", "only the run actor may resume this run")
        if run.status not in {"paused", "waiting", "failed"}:
            raise GraphError("GRAPH_STATE_INVALID", "run is not resumable")
        self._check_kill_switch(run, context or {})
        checkpoint = self.checkpointer.latest(org_id=tenant, run_id=identity)
        if checkpoint is None:
            raise GraphError("CHECKPOINT_NOT_FOUND", "run has no checkpoint")
        definition = self.registry.resolve(run.graph_key, run.workflow_version)
        state = deepcopy(checkpoint.state)
        if decision is not None:
            if any(str(key).lower() in {"token", "secret", "password", "body", "prompt"} for key in decision):
                raise GraphError("SENSITIVE_STATE_REJECTED", "decision contains a sensitive field")
            state["result_refs"] = {**state.get("result_refs", {}), **{str(k): str(v) for k, v in decision.items()}}
        state["status"] = "running"
        attempt_no = len(self.attempts.get(identity, [])) + 1
        self.attempts.setdefault(identity, []).append(GraphAttempt(str(uuid4()), identity, attempt_no, "running", _stamp(self._clock())))
        result = self._execute(run_id=identity, definition=definition, state=state, context=context or {}, attempt_no=attempt_no)
        self.resume_commands[(tenant, idempotency_key)] = (resume_digest, deepcopy(result))
        return result

    def pause(self, *, org_id: UUID | str, run_id: UUID | str, reason: str = "operator_pause") -> dict[str, Any]:
        tenant, identity = _uid(org_id, "org_id"), _uid(run_id, "run_id")
        run = self._owned_run(tenant, identity)
        if run.status not in {"running", "waiting"}:
            raise GraphError("GRAPH_STATE_INVALID", "only running runs can be paused")
        self._text(reason, "reason")
        updated = self._replace(run, status="paused")
        latest = self.checkpointer.latest(org_id=tenant, run_id=identity)
        if latest is not None:
            paused_state = deepcopy(latest.state)
            paused_state["status"] = "paused"
            self._save_checkpoint(updated, paused_state, latest.node)
        self._audit("graph.run.paused", updated, {"reason": reason})
        return updated.as_contract()

    def claim(self, *, org_id: UUID | str, run_id: UUID | str, worker_id: str) -> dict[str, Any]:
        """Claim a run for a bounded worker lease."""
        tenant, identity = _uid(org_id, "org_id"), _uid(run_id, "run_id")
        self._owned_run(tenant, identity)
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise GraphError("LEASE_INVALID", "worker_id is required")
        now = self._clock()
        current = self._leases.get(identity)
        if current is not None and current[1] > now and current[0] != worker_id:
            raise GraphError("LEASE_CONFLICT", "run is leased by another worker", category="transient", retryable=True)
        self._leases[identity] = (worker_id.strip(), now + timedelta(seconds=self.lease_seconds))
        return {"run_id": identity, "org_id": tenant, "worker_id": worker_id.strip(),
                "expires_at": _stamp(self._leases[identity][1])}

    def renew(self, *, org_id: UUID | str, run_id: UUID | str, worker_id: str) -> dict[str, Any]:
        tenant, identity = _uid(org_id, "org_id"), _uid(run_id, "run_id")
        self._owned_run(tenant, identity)
        current = self._leases.get(identity)
        if current is None or current[0] != worker_id or current[1] <= self._clock():
            raise GraphError("LEASE_REQUIRED", "worker lease is missing or expired")
        now = self._clock()
        self._leases[identity] = (worker_id, now + timedelta(seconds=self.lease_seconds))
        return {"run_id": identity, "org_id": tenant, "worker_id": worker_id, "expires_at": _stamp(self._leases[identity][1])}

    def release(self, *, org_id: UUID | str, run_id: UUID | str, worker_id: str) -> None:
        tenant, identity = _uid(org_id, "org_id"), _uid(run_id, "run_id")
        self._owned_run(tenant, identity)
        current = self._leases.get(identity)
        if current is not None and current[0] != worker_id:
            raise GraphError("LEASE_REQUIRED", "worker does not own run lease")
        self._leases.pop(identity, None)

    def cancel(self, *, org_id: UUID | str, actor_id: UUID | str, run_id: UUID | str, reason: str = "operator_cancel") -> dict[str, Any]:
        tenant, actor, identity = _uid(org_id, "org_id"), _uid(actor_id, "actor_id"), _uid(run_id, "run_id")
        run = self._owned_run(tenant, identity)
        if run.actor_id != actor:
            raise GraphError("FORBIDDEN", "only the run actor may cancel this run")
        if run.status in {"succeeded", "cancelled"}:
            return run.as_contract()
        updated = self._replace(run, status="cancelled")
        latest = self.checkpointer.latest(org_id=tenant, run_id=identity)
        if latest is not None:
            cancelled_state = deepcopy(latest.state)
            cancelled_state["status"] = "cancelled"
            self._save_checkpoint(updated, cancelled_state, latest.node)
        self._audit("graph.run.cancelled", updated, {"reason": reason})
        return updated.as_contract()

    def replay(self, *, org_id: UUID | str, actor_id: UUID | str, run_id: UUID | str,
               trace_id: str | None = None) -> dict[str, Any]:
        tenant, actor, identity = _uid(org_id, "org_id"), _uid(actor_id, "actor_id"), _uid(run_id, "run_id")
        run = self._owned_run(tenant, identity)
        if run.actor_id != actor:
            raise GraphError("FORBIDDEN", "only the run actor may replay this run")
        latest = self.checkpointer.latest(org_id=tenant, run_id=identity)
        if latest is None:
            raise GraphError("CHECKPOINT_NOT_FOUND", "run has no checkpoint")
        self.ledger.emit("graph.replay.requested", org_id=tenant, actor_id=actor, trace_id=trace_id or run.trace_id,
                         aggregate_id=identity, payload={"status": run.status, "checkpoint_sequence": latest.sequence})
        return {"run_id": identity, "replayable": True, "checkpoint_sequence": latest.sequence,
                "side_effect_replayed": False, "status": run.status}

    def _execute(self, *, run_id: str, definition: GraphDefinition, state: dict[str, Any],
                 context: Mapping[str, Any], attempt_no: int) -> dict[str, Any]:
        run = self.runs[run_id]
        try:
            state = validate_state(state)
            self._check_kill_switch(run, context)
            self._save_checkpoint(run, state, None)
            if definition.nodes:
                for index, node in enumerate(definition.nodes, start=1):
                    if index > self.max_steps:
                        raise GraphError("STEP_LIMIT", "graph step limit exceeded")
                    self._check_kill_switch(run, context)
                    node_name = getattr(node, "__name__", f"node_{index}")
                    state["current_node"] = node_name
                    started = _stamp(self._clock())
                    node_input_hash = state_hash(state)
                    try:
                        output = self._call(node, state, context)
                        if output:
                            state = self._merge_node_output(state, output)
                        state["last_node"] = node_name
                        state["current_node"] = None
                        self.nodes.append(NodeExecution(str(uuid4()), run_id, node_name, index, "succeeded",
                                                         node_input_hash, state_hash(state), started_at=started,
                                                         finished_at=_stamp(self._clock())))
                        self._save_checkpoint(run, state, node_name)
                    except GraphInterrupt:
                        raise
                    except Exception as exc:
                        code, category, retryable = self._classify(exc)
                        self.nodes.append(NodeExecution(str(uuid4()), run_id, node_name, index, "failed",
                                                         node_input_hash, error_code=code, started_at=started,
                                                         finished_at=_stamp(self._clock())))
                        raise GraphError(code, str(exc), category=category, retryable=retryable) from exc
            elif definition.entrypoint:
                self._check_kill_switch(run, context)
                output = self._call(definition.entrypoint, state, context)
                if output:
                    state = self._merge_node_output(state, output)
            state["status"] = "succeeded"
            validated = definition.validate_output(state)
            self._save_checkpoint(run, validated, state.get("last_node"))
            updated = self._replace(run, status="succeeded", current_node=state.get("last_node"),
                                    result_refs=dict(validated.get("result_refs", {})))
            self._finish_attempt(run_id, attempt_no, "succeeded")
            self._audit("graph.run.succeeded", updated, {"state_hash": state_hash(validated)})
            return updated.as_contract() | {"state": validated}
        except GraphInterrupt as exc:
            state["status"] = "waiting"; state["human_interrupt_ref"] = exc.interrupt_ref
            self._save_checkpoint(run, state, state.get("current_node"))
            updated = self._replace(run, status="waiting", human_interrupt_ref=exc.interrupt_ref,
                                    current_node=state.get("current_node"))
            self._finish_attempt(run_id, attempt_no, "waiting", error_code=exc.code)
            self._audit("graph.run.waiting", updated, {"interrupt_ref": exc.interrupt_ref})
            return updated.as_contract()
        except GraphError as exc:
            state["status"] = "failed"; state["error_ref"] = f"error://{exc.code}/{uuid4()}"
            self._save_checkpoint(run, state, state.get("current_node"))
            updated = self._replace(run, status="failed", error_ref=state["error_ref"], current_node=state.get("current_node"))
            self._finish_attempt(run_id, attempt_no, "failed", error_code=exc.code)
            self._audit("graph.run.failed", updated, {"code": exc.code, "category": exc.category, "retryable": exc.retryable})
            return updated.as_contract()
        except StateViolation as exc:
            error = GraphError("STATE_INVALID", str(exc), category="validation")
            state["status"] = "failed"; state["error_ref"] = f"error://{error.code}/{uuid4()}"
            self._save_checkpoint(run, state, state.get("current_node"))
            updated = self._replace(run, status="failed", error_ref=state["error_ref"], current_node=state.get("current_node"))
            self._finish_attempt(run_id, attempt_no, "failed", error_code=error.code)
            self._audit("graph.run.failed", updated, {"code": error.code, "category": error.category, "retryable": error.retryable})
            return updated.as_contract()
        except Exception as exc:
            code, category, retryable = self._classify(exc)
            state["status"] = "failed"; state["error_ref"] = f"error://{code}/{uuid4()}"
            self._save_checkpoint(run, state, state.get("current_node"))
            updated = self._replace(run, status="failed", error_ref=state["error_ref"], current_node=state.get("current_node"))
            self._finish_attempt(run_id, attempt_no, "failed", error_code=code)
            self._audit("graph.run.failed", updated, {"code": code, "category": category, "retryable": retryable})
            return updated.as_contract()

    @staticmethod
    def _call(function: Any, state: Mapping[str, Any], context: Mapping[str, Any]) -> Mapping[str, Any] | None:
        try:
            parameters = inspect.signature(function).parameters
        except (TypeError, ValueError):
            # A callable without an inspectable signature gets the full node
            # contract.  Do not catch TypeError from the callable itself: a
            # failed node must not be invoked a second time.
            result = function(state, context)
        else:
            result = function(state, context) if len(parameters) >= 2 else function(state)
        if result is None:
            return None
        if not isinstance(result, Mapping):
            raise GraphError("NODE_OUTPUT_INVALID", "node output must be an object")
        return result

    @staticmethod
    def _merge_node_output(state: Mapping[str, Any], output: Mapping[str, Any]) -> dict[str, Any]:
        candidate = dict(state)
        for key, value in output.items():
            if key in {"token", "secret", "password", "body", "prompt", "raw_content", "raw_output"}:
                raise GraphError("SENSITIVE_STATE_REJECTED", f"node output contains forbidden field {key}")
            candidate[key] = deepcopy(value)
        return validate_state(candidate)

    def _save_checkpoint(self, run: GraphRun, state: Mapping[str, Any], node: str | None) -> None:
        rows = self.checkpointer.list(org_id=run.org_id, run_id=run.id)
        self.checkpointer.save(Checkpoint(run.id, run.org_id, len(rows) + 1, validate_state(state), node, _stamp(self._clock())))

    def _owned_run(self, tenant: str, identity: str) -> GraphRun:
        run = self.runs.get(identity)
        if run is None or run.org_id != tenant:
            raise GraphError("GRAPH_RUN_NOT_FOUND", "run is not available in organization")
        return run

    def _check_kill_switch(self, run: GraphRun, context: Mapping[str, Any]) -> None:
        """Evaluate the injected control-plane gate immediately before work."""
        probe = context.get("kill_switch") if isinstance(context, Mapping) else None
        if probe is None:
            probe = self.kill_switch
        active = context.get("kill_switch_active") is True if isinstance(context, Mapping) else False
        if isinstance(probe, Mapping):
            active = active or probe.get("active") is True or probe.get("paused") is True
        elif callable(probe):
            try:
                active = active or bool(probe(org_id=run.org_id, run_id=run.id, trace_id=run.trace_id))
            except TypeError:
                active = active or bool(probe())
        elif probe is True:
            active = True
        if active:
            raise GraphError("KILL_SWITCH_ACTIVE", "graph execution is paused by the control plane", category="policy")

    def _replace(self, run: GraphRun, **changes: Any) -> GraphRun:
        values = run.__dict__.copy(); values.update(changes); values["updated_at"] = _stamp(self._clock())
        updated = GraphRun(**values); self.runs[run.id] = updated; return updated

    def _finish_attempt(self, run_id: str, attempt_no: int, status: str, error_code: str | None = None) -> None:
        rows = self.attempts.get(run_id, [])
        if rows and rows[-1].attempt_no == attempt_no:
            current = rows[-1]
            rows[-1] = GraphAttempt(current.id, current.run_id, current.attempt_no, status, current.started_at,
                                     _stamp(self._clock()), error_code)

    def _audit(self, event_type: str, run: GraphRun, payload: Mapping[str, Any]) -> None:
        event = self.ledger.emit(event_type, org_id=run.org_id, actor_id=run.actor_id, trace_id=run.trace_id,
                                 aggregate_id=run.id, payload=payload)
        self.audit.append(event)
        self.outbox.append(deepcopy(event))

    @staticmethod
    def _classify(exc: Exception) -> tuple[str, str, bool]:
        if isinstance(exc, GraphError):
            return exc.code, exc.category, exc.retryable
        if isinstance(exc, (TimeoutError, ConnectionError)):
            return "DEPENDENCY_UNAVAILABLE", "transient", True
        if isinstance(exc, StateViolation):
            return "STATE_INVALID", "validation", False
        return "NODE_EXECUTION_FAILED", "validation", False

    @staticmethod
    def _text(value: Any, field: str) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > 200:
            raise GraphError("GRAPH_INPUT_INVALID", f"{field} must be non-empty bounded text")
        return value.strip()


__all__ = ["GraphAttempt", "GraphRun", "GraphRunner", "NodeExecution"]
