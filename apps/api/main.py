"""Minimal API composition root for FOUND-002.

Business routes are intentionally absent until their owning domain tasks are
implemented. Health routes report process state and dependency configuration only.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from infra.foundation.metrics import (
    ApiMetricsMiddleware,
    HealthRegistry,
    MetricRegistry,
    default_health_registry,
    default_metric_registry,
    register_default_metrics,
)
from infra.foundation.observability import get_tenant_context, install_api_observability
from infra.foundation.outbox import OutboxError
from infra.foundation.task_claim import TaskClaimError
from infra.foundation.task_failure import TaskFailureError
from infra.foundation.task_replay import TaskReplayError
from infra.foundation.tracing import OpenTelemetryMiddleware, TracingRuntime, create_tracing_runtime
from modules.iam import IamError, InMemoryIamService
from modules.distribution.account import AccountError, InMemoryAccountService
from modules.workflow import DispatchError, WorkflowError, WorkflowService
from modules.topic import (
    TopicSignalError, TopicSignalImportService, TopicOpportunityError, TopicOpportunityService,
    TopicBriefError, TopicBriefService,
    EditorialCalendarError, EditorialCalendarService,
)
from modules.provenance import (
    RightsError, RightsGuardError, RightsGuardService, RightsService, SourceError, SourceService,
)
from modules.knowledge import KnowledgeCoreService, KnowledgeError, KnowledgeService
from modules.canonical_content import CanonicalContentError, CanonicalContentService
from adapters.xiaohongshu.session import diagnose_session, read_session_status
from adapters.xiaohongshu.operator import launch_operator_session, read_launch_status
from modules.media.local_demo_generator import generate_cover_svg, generate_demo_content
from modules.support.local_reply_generator import generate_local_reply
from modules.model_gateway.console_provider import generate_structured, model_config
from integrations.langchain.model import ModelError
from adapters.platforms.routing import profile_for, resolve_delivery_route


SERVICE_NAME = "api"
RUNTIME_NAME = "modular-monolith"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONSOLE_STATE_PATH = PROJECT_ROOT / ".local" / "workflow-state.json"


def dependency_status(registry: HealthRegistry) -> dict[str, Any]:
    """Return a redacted readiness aggregate without external probes."""
    snapshot = registry.readiness()
    checks = snapshot.as_contract()["checks"]
    database = checks.get(
        "database",
        {
            "component": "database",
            "status": "not_configured",
            "critical": True,
            "details": {"status": "not_configured", "probe": "skipped"},
        },
    )
    return {
        "status": snapshot.status,
        "database": database["status"],
        "database_health": database["details"],
        "checks": checks,
        "business_routes_registered": False,
    }


def create_app(
    outbox_dispatcher: Any | None = None,
    task_claim_store: Any | None = None,
    task_failure_store: Any | None = None,
    task_replay_store: Any | None = None,
    health_registry: HealthRegistry | None = None,
    metric_registry: MetricRegistry | None = None,
    tracing_runtime: TracingRuntime | None = None,
    iam_service: InMemoryIamService | None = None,
    account_service: InMemoryAccountService | None = None,
    workflow_service: WorkflowService | None = None,
    topic_signal_service: TopicSignalImportService | None = None,
    topic_opportunity_service: TopicOpportunityService | None = None,
    topic_brief_service: TopicBriefService | None = None,
    editorial_calendar_service: EditorialCalendarService | None = None,
    provenance_service: SourceService | None = None,
    rights_service: RightsService | None = None,
    rights_guard_service: RightsGuardService | None = None,
    knowledge_service: KnowledgeService | None = None,
    knowledge_core_service: KnowledgeCoreService | None = None,
    canonical_content_service: CanonicalContentService | None = None,
) -> FastAPI:
    health_checks = health_registry or default_health_registry()
    metrics = metric_registry or default_metric_registry()
    tracing = tracing_runtime or create_tracing_runtime(SERVICE_NAME)
    default_metrics = register_default_metrics(metrics)
    app = FastAPI(
        title="AI Content Workflow API",
        version="0.1.0",
        description="FOUND-002 composition root; domain routes are registered by later tasks.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            # A locally opened HTML file sends the literal `null` origin.  It
            # is still a local, operator-owned dashboard and needs to be able
            # to reach the loopback API during setup.
            'null',
            'http://127.0.0.1:8765', 'http://127.0.0.1:8766',
            'http://localhost:8765', 'http://localhost:8766',
        ],
        allow_origin_regex=r'https?://(?:127\.0\.0\.1|localhost)(?::\d+)?$',
        allow_methods=['GET', 'POST', 'PUT', 'OPTIONS'],
        allow_headers=['*'],
    )
    install_api_observability(app)
    app.add_middleware(ApiMetricsMiddleware, registry=metrics)
    app.add_middleware(OpenTelemetryMiddleware, runtime=tracing)
    app.state.health_registry = health_checks
    app.state.metric_registry = metrics
    app.state.tracing_runtime = tracing
    app.state.iam_service = iam_service or InMemoryIamService()
    app.state.account_service = account_service or InMemoryAccountService()
    app.state.workflow_service = workflow_service or WorkflowService()
    app.state.topic_signal_service = topic_signal_service or TopicSignalImportService()
    app.state.topic_opportunity_service = topic_opportunity_service or TopicOpportunityService(app.state.topic_signal_service)
    app.state.topic_brief_service = topic_brief_service or TopicBriefService(app.state.topic_opportunity_service)
    app.state.editorial_calendar_service = editorial_calendar_service or EditorialCalendarService(app.state.topic_opportunity_service)
    app.state.provenance_service = provenance_service or SourceService()
    app.state.rights_service = rights_service or RightsService(connection=app.state.provenance_service._connection)
    app.state.rights_guard_service = rights_guard_service or RightsGuardService(rights_service=app.state.rights_service)
    app.state.knowledge_service = knowledge_service or KnowledgeService(connection=app.state.provenance_service._connection)
    app.state.knowledge_core_service = knowledge_core_service or KnowledgeCoreService(connection=app.state.provenance_service._connection)
    app.state.canonical_content_service = canonical_content_service or CanonicalContentService(
        connection=app.state.provenance_service._connection,
        topic_brief_service=app.state.topic_brief_service,
    )

    def correlation_fields() -> dict[str, str | None]:
        context = get_tenant_context()
        if context is None:
            return {"trace_id": str(uuid4()), "request_id": str(uuid4()), "org_id": None, "actor_id": None}
        return context.as_dict()

    def success_response(data: Any) -> dict[str, Any]:
        return {"data": data, **correlation_fields()}

    @app.get("/health/live", tags=["health"])
    def live() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": SERVICE_NAME,
            "runtime": RUNTIME_NAME,
            **correlation_fields(),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    @app.get("/health/ready", tags=["health"])
    def ready() -> dict[str, Any]:
        dependencies = dependency_status(health_checks)
        for component, check in dependencies["checks"].items():
            default_metrics.dependency_ready.set(
                1 if check["status"] == "ready" else 0,
                component=component,
            )
        return {
            "status": dependencies["status"],
            "service": SERVICE_NAME,
            "runtime": RUNTIME_NAME,
            "dependencies": dependencies,
            **correlation_fields(),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    @app.get("/metrics", tags=["metrics"])
    def prometheus_metrics() -> Response:
        return Response(
            content=metrics.prometheus_text(),
            media_type="text/plain; version=0.0.4",
        )

    @app.get("/internal/xhs/accounts/{account_key}/session", tags=["internal"], include_in_schema=False)
    def xhs_session(account_key: str) -> dict[str, Any]:
        """Return redacted local browser-session state; never returns cookies or tokens."""
        try:
            return success_response(read_session_status(account_key))
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_XHS_ACCOUNT", "message": str(exc)}) from exc

    @app.get("/internal/xhs/accounts/{account_key}/diagnostics", tags=["internal"], include_in_schema=False)
    def xhs_diagnostics(account_key: str) -> dict[str, Any]:
        """Explain local login readiness without returning cookies or tokens."""
        try:
            return success_response(diagnose_session(account_key))
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_XHS_ACCOUNT", "message": str(exc)}) from exc

    @app.get("/internal/xhs/launches/{job_id}", tags=["internal"], include_in_schema=False)
    def xhs_launch(job_id: str) -> dict[str, Any]:
        try:
            return success_response(read_launch_status(job_id))
        except (ValueError, OSError, json.JSONDecodeError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail={"code": "XHS_LAUNCH_NOT_FOUND", "message": str(exc)}) from exc

    @app.get("/internal/console/state", tags=["internal"], include_in_schema=False)
    def console_state() -> dict[str, Any]:
        path = CONSOLE_STATE_PATH
        if not path.exists():
            return success_response({"state": None, "updated_at": None})
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=500, detail={"code": "CONSOLE_STATE_READ_FAILED", "message": str(exc)}) from exc
        return success_response(payload)

    @app.put("/internal/console/state", tags=["internal"], include_in_schema=False)
    async def put_console_state(request: Request) -> dict[str, Any]:
        try:
            payload = await request.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail={"code": "CONSOLE_STATE_INVALID", "message": "请求内容不是有效 JSON"}) from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("state"), dict):
            raise HTTPException(status_code=400, detail={"code": "CONSOLE_STATE_INVALID", "message": "state 必须是对象"})
        path = CONSOLE_STATE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"state": payload["state"], "updated_at": datetime.now(timezone.utc).isoformat()}
        try:
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            raise HTTPException(status_code=500, detail={"code": "CONSOLE_STATE_WRITE_FAILED", "message": str(exc)}) from exc
        return success_response(record)

    @app.get("/internal/model/status", tags=["internal"], include_in_schema=False)
    def model_status() -> dict[str, Any]:
        """Expose redacted model readiness for the local console."""
        config = model_config()
        return success_response({
            "provider": config["provider"],
            "base_url": config["base_url"],
            "model": config["model"],
            "configured": config["configured"],
            "key_present": config["key_present"],
        })

    @app.get("/internal/platforms/{platform}/route", tags=["internal"], include_in_schema=False)
    def platform_route(platform: str, action: str = "publish", api_authorized: bool = False,
                       browser_session_ready: bool = False) -> dict[str, Any]:
        """Explain why an account uses API, browser automation, or manual export."""
        allowed = {"publish", "inbox", "comment_reply", "message_reply"}
        if action not in allowed:
            raise HTTPException(status_code=400, detail={"code": "INVALID_PLATFORM_ACTION", "message": "unsupported platform action"})
        route = resolve_delivery_route(
            profile=profile_for(platform), action=action,
            api_authorized=api_authorized, browser_session_ready=browser_session_ready,
        )
        return success_response({"platform": route.platform, "action": route.action,
                                 "mode": route.mode, "reason": route.reason})

    @app.post("/internal/xhs/accounts/{account_key}/browser:open", tags=["internal"], include_in_schema=False)
    def open_xhs_browser(account_key: str, command: dict[str, Any] | None = None) -> dict[str, Any]:
        """Open the account's local browser session for login, inbox work, or draft preview."""
        payload = command or {}
        try:
            result = launch_operator_session(
                account_key,
                target=str(payload.get("target", "home")),
                content=payload.get("content"),
                auto_publish=bool(payload.get("auto_publish", False)),
            )
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": "XHS_BROWSER_LAUNCH_FAILED", "message": str(exc)},
            ) from exc
        return success_response(result)

    @app.post("/internal/content/drafts:generate", tags=["internal"], include_in_schema=False)
    def generate_local_draft(command: dict[str, Any] | None = None) -> dict[str, Any]:
        """Generate a model draft when configured, with a deterministic fallback."""
        payload = command or {}
        topic = str(payload.get("topic", "")).strip()
        audience = str(payload.get("audience", "AI 工程团队")).strip() or "AI 工程团队"
        if not topic or len(topic) > 120:
            raise HTTPException(status_code=400, detail={"code": "INVALID_DRAFT_TOPIC", "message": "topic is required and must be <= 120 characters"})
        try:
            schema = {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "minLength": 1},
                    "body": {"type": "string", "minLength": 1},
                    "hashtags": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
                },
                "required": ["title", "body", "hashtags"],
                "additionalProperties": False,
            }
            try:
                content_data = generate_structured(
                    messages=[
                        {"role": "system", "content": "你是内容运营编辑。输出适合小红书图文的中文标题、正文和话题。只返回 JSON。"},
                        {"role": "user", "content": f"目标受众：{audience}\n选题：{topic}"},
                    ], schema=schema, purpose="content_draft",
                )
                hashtags = tuple(str(item).strip() for item in content_data.get("hashtags", []) if str(item).strip())
                content = type("GeneratedContent", (), {
                    "title": str(content_data["title"]).strip(),
                    "body": str(content_data["body"]).strip(),
                    "hashtags": hashtags,
                })()
                source = "model"
                model_used = True
            except (ModelError, ValueError) as exc:
                content = generate_demo_content(topic, audience=audience)
                source = "local-template"
                model_used = False
                fallback_reason = getattr(exc, "code", "MODEL_CONFIG_INVALID")
            cover_path = Path(".tmp") / "generated-content" / "api-cover.svg"
            generate_cover_svg(content, cover_path)
            cover_svg = cover_path.read_text(encoding="utf-8")
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=500, detail={"code": "LOCAL_DRAFT_GENERATION_FAILED", "message": str(exc)}) from exc
        return success_response({
            "title": content.title,
            "body": content.body,
            "hashtags": list(content.hashtags),
            "cover_svg": cover_svg,
            "source": source,
            "model_used": model_used,
            **({"fallback_reason": fallback_reason} if not model_used and "fallback_reason" in locals() else {}),
        })

    @app.post("/internal/support/replies:generate", tags=["internal"], include_in_schema=False)
    def generate_local_reply_draft(command: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = command or {}
        message = str(payload.get("message", "")).strip()
        if not message or len(message) > 2000:
            raise HTTPException(status_code=400, detail={"code": "INVALID_SUPPORT_MESSAGE", "message": "message is required and must be <= 2000 characters"})
        try:
            intent = str(payload.get("intent", "question"))
            risk = str(payload.get("risk", "low"))
            if risk == "high":
                result = generate_local_reply(message, intent=intent, risk=risk)
            else:
                schema = {
                    "type": "object",
                    "properties": {"reply": {"type": "string", "minLength": 1}, "requires_human": {"type": "boolean"}},
                    "required": ["reply", "requires_human"], "additionalProperties": False,
                }
                try:
                    result = generate_structured(
                        messages=[
                            {"role": "system", "content": "你是谨慎的品牌客服。只输出 JSON，回复简洁、友好，不承诺未核实的事实。"},
                            {"role": "user", "content": f"意图：{intent}\n用户消息：{message}"},
                        ], schema=schema, purpose="support_reply",
                    )
                except (ModelError, ValueError) as exc:
                    result = generate_local_reply(message, intent=intent, risk=risk)
                    result["fallback_reason"] = getattr(exc, "code", "MODEL_CONFIG_INVALID")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_SUPPORT_MESSAGE", "message": str(exc)}) from exc
        return success_response(result)

    @app.post("/internal/outbox/dispatch", tags=["internal"], include_in_schema=False)
    def dispatch_outbox(
        command: dict[str, Any] | None = None,
        x_worker_id: str | None = Header(default=None, alias="X-Worker-Id"),
    ) -> dict[str, Any]:
        """Worker-only synthetic dispatch command; no default network publisher."""
        if not x_worker_id or not x_worker_id.strip():
            raise HTTPException(status_code=403, detail={"code": "WORKER_ONLY"})
        if outbox_dispatcher is None:
            raise HTTPException(status_code=503, detail={"code": "OUTBOX_NOT_CONFIGURED"})
        payload = command or {}
        try:
            limit = int(payload.get("limit", 10))
            if limit < 1 or limit > 100:
                raise ValueError("limit must be between 1 and 100")
            results = outbox_dispatcher.dispatch_once(
                worker_id=x_worker_id.strip(),
                org_id=payload.get("org_id"),
                limit=limit,
            )
        except (TypeError, ValueError, OutboxError) as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_DISPATCH_COMMAND", "message": str(exc)}) from exc
        return success_response([
                {
                    "event_id": result.event_id,
                    "status": result.status,
                    "code": result.code,
                    "attempt_count": result.attempt_count,
                    "error": result.error,
                }
                for result in results
            ])

    @app.post("/internal/workflow/outbox:dispatch", tags=["internal"], include_in_schema=False)
    def dispatch_workflow_outbox(
        command: dict[str, Any] | None = None,
        x_worker_id: str | None = Header(default=None, alias="X-Worker-Id"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        """Workflow-owned dispatch command with explicit command idempotency."""
        if outbox_dispatcher is None:
            raise HTTPException(status_code=503, detail={"code": "OUTBOX_NOT_CONFIGURED"})
        payload = command or {}
        try:
            worker = require_worker(x_worker_id)
            key = require_idempotency_key(idempotency_key)
            results = outbox_dispatcher.dispatch_once(
                worker_id=worker,
                org_id=payload.get("org_id"),
                limit=int(payload.get("limit", 10)),
                idempotency_key=key,
            )
        except TypeError:
            # FOUND-004B's DB adapter already deduplicates by event_id and
            # event idempotency key; keep it compatible while this route also
            # requires the command header.
            results = outbox_dispatcher.dispatch_once(
                worker_id=worker,
                org_id=payload.get("org_id"),
                limit=int(payload.get("limit", 10)),
            )
        except (DispatchError, OutboxError, TypeError, ValueError) as exc:
            code = getattr(exc, "code", "INVALID_DISPATCH_COMMAND")
            raise HTTPException(status_code=409 if code == "IDEMPOTENCY_KEY_REUSED" else 400, detail={"code": code, "message": str(exc)}) from exc
        return success_response([
            result.as_contract() if hasattr(result, "as_contract") else {
                "event_id": getattr(result, "event_id", None),
                "status": getattr(result, "status", None),
                "code": getattr(result, "code", None),
                "attempt_count": getattr(result, "attempt_count", None),
                "error": getattr(result, "error", None),
            }
            for result in results
        ])

    def require_worker(worker_id: str | None) -> str:
        if not worker_id or not worker_id.strip():
            raise HTTPException(status_code=403, detail={"code": "WORKER_ONLY"})
        return worker_id.strip()

    def require_idempotency_key(value: str | None) -> str:
        key = value.strip() if value else ""
        if not key:
            raise ValueError("Idempotency-Key header is required")
        if len(key) < 8 or len(key) > 200:
            raise ValueError("Idempotency-Key header must be between 8 and 200 characters")
        return key

    def claim_error(exc: TaskClaimError) -> HTTPException:
        status = 409 if exc.code in {"JOB_NOT_CLAIMABLE", "JOB_VERSION_CONFLICT"} else 400
        return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})

    def failure_error(exc: TaskFailureError) -> HTTPException:
        status = 403 if exc.code == "TENANT_SCOPE_VIOLATION" else 409 if exc.code in {
            "RETRY_NOT_ALLOWED", "MAX_ATTEMPTS_EXCEEDED", "REQUEUE_NOT_ALLOWED",
        } else 400
        return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})

    def replay_error(exc: TaskReplayError) -> HTTPException:
        status = 403 if exc.code == "TENANT_SCOPE_VIOLATION" else 409 if exc.code in {
            "REPLAY_NOT_ALLOWED", "REPLAY_VERSION_CONFLICT",
        } else 400
        return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})

    def iam_error(exc: IamError) -> HTTPException:
        status = 403 if exc.code in {"FORBIDDEN", "TENANT_SCOPE_VIOLATION", "ACTOR_DISABLED"} else 409 if exc.code in {
            "DUPLICATE_BINDING", "DUPLICATE_IDENTITY", "IDEMPOTENCY_KEY_REUSED",
        } else 400
        return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})

    def account_error(exc: AccountError) -> HTTPException:
        status = 403 if exc.code == "TENANT_SCOPE_VIOLATION" else 409 if exc.code == "DUPLICATE_PROFILE" else 400
        return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})

    def workflow_error(exc: WorkflowError) -> HTTPException:
        status = 403 if exc.code in {"TENANT_SCOPE_VIOLATION", "FORBIDDEN"} else 409 if exc.code in {
            "VERSION_CONFLICT", "INVALID_STATE_TRANSITION", "RETRY_NOT_ALLOWED",
        } else 400
        return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})

    def provenance_error(exc: SourceError) -> HTTPException:
        status = 403 if exc.code in {"TENANT_SCOPE_VIOLATION", "FORBIDDEN"} else 409 if exc.code in {
            "IDEMPOTENCY_KEY_REUSED", "SOURCE_ALREADY_EXISTS", "SOURCE_NOT_WRITABLE",
            "VERSION_CONFLICT", "INVALID_SOURCE_STATE", "REASON_REQUIRED",
        } else 400
        return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})

    def rights_error(exc: RightsError) -> HTTPException:
        status = 403 if exc.code in {"TENANT_SCOPE_VIOLATION", "FORBIDDEN"} else 409 if exc.code in {
            "IDEMPOTENCY_KEY_REUSED", "RIGHTS_CONFLICT", "RIGHTS_SOURCE_CONFLICT", "VERSION_CONFLICT",
            "INVALID_RIGHTS_STATE", "SOURCE_SNAPSHOT_NOT_USABLE",
        } else 400
        return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})

    def rights_guard_error(exc: RightsGuardError) -> HTTPException:
        status = 403 if exc.code in {"TENANT_SCOPE_VIOLATION", "FORBIDDEN", "RIGHTS_NOT_USABLE"} else 409 if exc.code in {
            "IDEMPOTENCY_KEY_REUSED", "GUARD_CONFLICT", "LINEAGE_CONFLICT", "VERSION_CONFLICT",
        } else 400
        return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})

    def knowledge_error(exc: KnowledgeError) -> HTTPException:
        status = 403 if exc.code in {"TENANT_SCOPE_VIOLATION", "FORBIDDEN"} else 409 if exc.code in {
            "IDEMPOTENCY_KEY_REUSED", "VERSION_CONFLICT", "ENTITY_ALREADY_EXISTS", "CLAIM_CONFLICT",
            "EVIDENCE_CONFLICT", "INVALID_ENTITY_STATE", "INVALID_CLAIM_STATE", "INVALID_EVIDENCE_STATE",
            "CLAIM_EVIDENCE_REQUIRED", "SOURCE_SNAPSHOT_NOT_USABLE", "RIGHTS_NOT_USABLE",
            "KNOWLEDGE_CORE_CONFLICT", "KNOWLEDGE_CONFLICT_REVIEW", "KNOWLEDGE_EVIDENCE_INSUFFICIENT",
        } else 400
        return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})

    def canonical_content_error(exc: CanonicalContentError) -> HTTPException:
        status = 403 if exc.code in {"TENANT_SCOPE_VIOLATION", "FORBIDDEN"} else 409 if exc.code in {
            "IDEMPOTENCY_KEY_REUSED", "CANONICAL_CONTENT_EXISTS", "VERSION_CONFLICT", "IMMUTABLE_VERSION",
            "TOPIC_BRIEF_MISMATCH", "INPUT_SNAPSHOT_MISMATCH", "CONTENT_HASH_MISMATCH",
            "KNOWLEDGE_CORE_NOT_VERIFIED", "REFRESH_QUEUE_NOT_CLAIMABLE",
        } else 400
        return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})

    def header_uuid(value: str | None, name: str) -> UUID:
        if not value:
            raise HTTPException(status_code=400, detail={"code": "TENANT_CONTEXT_REQUIRED", "message": f"{name} header is required"})
        try:
            return UUID(value)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "TENANT_CONTEXT_REQUIRED", "message": f"{name} must be a UUID"}) from exc

    @app.post("/internal/topic-signals:import", tags=["internal"], include_in_schema=False, status_code=202)
    @app.post("/v1/topic-signals", tags=["topic"], include_in_schema=False, status_code=202)
    async def import_topic_signals(
        request: Request,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        context = get_tenant_context()
        if context is None:
            raise HTTPException(status_code=400, detail={"code": "TENANT_CONTEXT_REQUIRED"})
        org_id = header_uuid(context.org_id, "X-Org-Id")
        actor_id = header_uuid(context.actor_id, "X-Actor-Id")
        try:
            key = require_idempotency_key(idempotency_key)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_IDEMPOTENCY_KEY", "message": str(exc)}) from exc
        body = await request.body()
        if len(body) > 5 * 1024 * 1024:
            raise HTTPException(status_code=413, detail={"code": "IMPORT_BODY_TOO_LARGE"})
        content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
        try:
            if content_type == "application/json":
                try:
                    rows = json.loads(body.decode("utf-8-sig"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise HTTPException(status_code=400, detail={"code": "INVALID_JSON_BATCH"}) from exc
                result = app.state.topic_signal_service.import_json(
                    org_id=org_id, actor_id=actor_id, trace_id=context.trace_id,
                    idempotency_key=key, rows=rows,
                )
            elif content_type == "text/csv":
                result = app.state.topic_signal_service.import_csv(
                    org_id=org_id, actor_id=actor_id, trace_id=context.trace_id,
                    idempotency_key=key, content=body,
                )
            else:
                raise HTTPException(status_code=415, detail={"code": "UNSUPPORTED_IMPORT_TYPE"})
        except TopicSignalError as exc:
            status = 409 if exc.code == "IDEMPOTENCY_KEY_REUSED" else 400
            raise HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)}) from exc
        return success_response(result)

    def topic_opportunity_error(exc: TopicOpportunityError) -> HTTPException:
        status = 403 if exc.code == "TENANT_SCOPE_VIOLATION" else 409 if exc.code in {
            "IDEMPOTENCY_KEY_REUSED", "TOPIC_ACTIVE_CONFLICT", "VERSION_CONFLICT",
            "INVALID_TOPIC_STATE", "RIGHTS_BLOCK_SHORTLIST", "TOPIC_OPPORTUNITY_EXPIRED",
        } else 400
        return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})

    @app.post("/internal/topic-opportunities:score", tags=["internal"], include_in_schema=False)
    def score_topic_opportunity(
        command: dict[str, Any],
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        context = get_tenant_context()
        if context is None:
            raise HTTPException(status_code=400, detail={"code": "TENANT_CONTEXT_REQUIRED"})
        org_id = header_uuid(context.org_id, "X-Org-Id")
        actor_id = header_uuid(context.actor_id, "X-Actor-Id")
        try:
            key = require_idempotency_key(idempotency_key)
            result = app.state.topic_opportunity_service.score(
                org_id=org_id, actor_id=actor_id, trace_id=context.trace_id,
                idempotency_key=key, signal_ids=command.get("signal_ids", []),
                canonical_topic=command.get("canonical_topic"), scores=command.get("scores"),
                expires_at=command.get("expires_at"),
                scoring_version=command.get("scoring_version", "topic-score-v1"),
            )
        except ValueError as exc:
            if isinstance(exc, TopicOpportunityError):
                raise topic_opportunity_error(exc) from exc
            raise HTTPException(status_code=400, detail={"code": "INVALID_IDEMPOTENCY_KEY", "message": str(exc)}) from exc
        return success_response(result)

    @app.post("/internal/topic-opportunities/{opportunity_id}:shortlist", tags=["internal"], include_in_schema=False)
    def shortlist_topic_opportunity(
        opportunity_id: str, command: dict[str, Any],
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        x_actor_type: str | None = Header(default=None, alias="X-Actor-Type"),
    ) -> dict[str, Any]:
        if x_actor_type != "user":
            raise HTTPException(status_code=403, detail={"code": "HUMAN_ACTOR_REQUIRED"})
        context = get_tenant_context()
        if context is None:
            raise HTTPException(status_code=400, detail={"code": "TENANT_CONTEXT_REQUIRED"})
        org_id = header_uuid(context.org_id, "X-Org-Id")
        actor_id = header_uuid(context.actor_id, "X-Actor-Id")
        try:
            key = require_idempotency_key(idempotency_key)
            result = app.state.topic_opportunity_service.shortlist(
                org_id=org_id, opportunity_id=opportunity_id, actor_id=actor_id,
                trace_id=context.trace_id, idempotency_key=key,
                expected_version=command.get("expected_version"),
                decision_reason=command.get("decision_reason"),
            )
        except ValueError as exc:
            if isinstance(exc, TopicOpportunityError):
                raise topic_opportunity_error(exc) from exc
            raise HTTPException(status_code=400, detail={"code": "INVALID_IDEMPOTENCY_KEY", "message": str(exc)}) from exc
        return success_response(result)

    def topic_brief_error(exc: TopicBriefError) -> HTTPException:
        status = 403 if exc.code in {"TENANT_SCOPE_VIOLATION", "BRIEF_CREATOR_CANNOT_APPROVE"} else 409 if exc.code in {
            "IDEMPOTENCY_KEY_REUSED", "BRIEF_ALREADY_EXISTS", "BRIEF_ALREADY_LOCKED", "VERSION_CONFLICT",
            "TOPIC_BRIEF_NOT_ELIGIBLE", "INVALID_BRIEF_STATE", "EVIDENCE_PLAN_INCOMPLETE",
            "CLAIM_EVIDENCE_PLAN_MISSING", "POLICY_DENIED", "OPTIMISTIC_LOCK_CONFLICT", "IMMUTABLE_VERSION",
        } else 400
        return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})

    @app.post("/internal/topic-briefs", tags=["internal"], include_in_schema=False)
    def create_topic_brief(
        command: dict[str, Any], idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        context = get_tenant_context()
        if context is None:
            raise HTTPException(status_code=400, detail={"code": "TENANT_CONTEXT_REQUIRED"})
        try:
            result = app.state.topic_brief_service.create(
                org_id=header_uuid(context.org_id, "X-Org-Id"),
                opportunity_id=command.get("opportunity_id"), actor_id=header_uuid(context.actor_id, "X-Actor-Id"),
                trace_id=context.trace_id, idempotency_key=require_idempotency_key(idempotency_key),
                content=command.get("content", {}),
            )
        except TopicBriefError as exc:
            raise topic_brief_error(exc) from exc
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_BRIEF_COMMAND", "message": str(exc)}) from exc
        return success_response(result)

    @app.post("/v1/topic-briefs/{brief_id}/approve", tags=["topic"], include_in_schema=False)
    def approve_topic_brief(
        brief_id: str,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        if_match: str | None = Header(default=None, alias="If-Match"),
    ) -> dict[str, Any]:
        context = get_tenant_context()
        if context is None:
            raise HTTPException(status_code=400, detail={"code": "TENANT_CONTEXT_REQUIRED"})
        try:
            result = app.state.topic_brief_service.approve(
                org_id=header_uuid(context.org_id, "X-Org-Id"), brief_id=brief_id,
                actor_id=header_uuid(context.actor_id, "X-Actor-Id"), trace_id=context.trace_id,
                idempotency_key=require_idempotency_key(idempotency_key), if_match=if_match,
            )
        except TopicBriefError as exc:
            raise topic_brief_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_IDEMPOTENCY_KEY", "message": str(exc)}) from exc
        return success_response(result)

    @app.post("/internal/topic-briefs/{brief_id}:lock", tags=["internal"], include_in_schema=False)
    def lock_topic_brief(
        brief_id: str, command: dict[str, Any],
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        context = get_tenant_context()
        if context is None:
            raise HTTPException(status_code=400, detail={"code": "TENANT_CONTEXT_REQUIRED"})
        try:
            result = app.state.topic_brief_service.lock(
                org_id=header_uuid(context.org_id, "X-Org-Id"), brief_id=brief_id,
                actor_id=header_uuid(context.actor_id, "X-Actor-Id"), trace_id=context.trace_id,
                idempotency_key=require_idempotency_key(idempotency_key),
                expected_version_no=command.get("expected_version_no"),
                policy_snapshot_ref=command.get("policy_snapshot_ref"),
            )
        except TopicBriefError as exc:
            raise topic_brief_error(exc) from exc
        return success_response(result)

    @app.post("/internal/topic-briefs/{brief_id}:supersede", tags=["internal"], include_in_schema=False)
    def supersede_topic_brief(
        brief_id: str, command: dict[str, Any],
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        context = get_tenant_context()
        if context is None:
            raise HTTPException(status_code=400, detail={"code": "TENANT_CONTEXT_REQUIRED"})
        try:
            result = app.state.topic_brief_service.supersede(
                org_id=header_uuid(context.org_id, "X-Org-Id"), brief_id=brief_id,
                actor_id=header_uuid(context.actor_id, "X-Actor-Id"), trace_id=context.trace_id,
                idempotency_key=require_idempotency_key(idempotency_key),
                expected_version_no=command.get("expected_version_no"),
                policy_snapshot_ref=command.get("policy_snapshot_ref"), content=command.get("content", {}),
            )
        except TopicBriefError as exc:
            raise topic_brief_error(exc) from exc
        return success_response(result)

    def editorial_calendar_error(exc: EditorialCalendarError) -> HTTPException:
        status = 403 if exc.code == "TENANT_SCOPE_VIOLATION" else 409 if exc.code in {
            "IDEMPOTENCY_KEY_REUSED", "EDITORIAL_PLAN_EXISTS", "VERSION_CONFLICT",
            "TOPIC_OPPORTUNITY_EXPIRED",
        } else 400
        return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})

    def schedule_calendar_command(
        opportunity_id: str, command: dict[str, Any], idempotency_key: str | None,
        *, override: bool,
    ) -> dict[str, Any]:
        context = get_tenant_context()
        if context is None:
            raise HTTPException(status_code=400, detail={"code": "TENANT_CONTEXT_REQUIRED"})
        try:
            owner_id = command.get("owner_id") or context.actor_id
            result = app.state.editorial_calendar_service.schedule(
                org_id=header_uuid(context.org_id, "X-Org-Id"), opportunity_id=opportunity_id,
                actor_id=header_uuid(context.actor_id, "X-Actor-Id"), trace_id=context.trace_id,
                idempotency_key=require_idempotency_key(idempotency_key),
                expected_version=command.get("expected_version"), owner_id=owner_id,
                priority=command.get("priority"), due_at=command.get("due_at"),
                manual_override_reason=command.get("manual_override_reason"), override=override,
            )
        except EditorialCalendarError as exc:
            raise editorial_calendar_error(exc) from exc
        return success_response(result)

    @app.post("/internal/topic-opportunities/{opportunity_id}:schedule", tags=["internal"], include_in_schema=False)
    def schedule_topic_opportunity(
        opportunity_id: str, command: dict[str, Any],
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        return schedule_calendar_command(opportunity_id, command, idempotency_key, override=False)

    @app.post("/internal/topic-opportunities/{opportunity_id}:override", tags=["internal"], include_in_schema=False)
    def override_topic_opportunity_schedule(
        opportunity_id: str, command: dict[str, Any],
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        return schedule_calendar_command(opportunity_id, command, idempotency_key, override=True)

    @app.post("/internal/topic-opportunities/{opportunity_id}:{action}", tags=["internal"], include_in_schema=False)
    def transition_topic_opportunity(
        opportunity_id: str, action: str, command: dict[str, Any] | None = None,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        context = get_tenant_context()
        if context is None:
            raise HTTPException(status_code=400, detail={"code": "TENANT_CONTEXT_REQUIRED"})
        payload = command or {}
        try:
            result = app.state.topic_opportunity_service.transition(
                org_id=header_uuid(context.org_id, "X-Org-Id"), opportunity_id=opportunity_id,
                actor_id=header_uuid(context.actor_id, "X-Actor-Id"), trace_id=context.trace_id,
                idempotency_key=require_idempotency_key(idempotency_key), action=action,
                expected_version=payload.get("expected_version"), reason=payload.get("reason"),
            )
        except TopicOpportunityError as exc:
            status = 403 if exc.code in {"TENANT_SCOPE_VIOLATION"} else 409 if exc.code in {
                "IDEMPOTENCY_KEY_REUSED", "VERSION_CONFLICT", "INVALID_TOPIC_STATE", "BRIEF_LOCKED",
            } else 400
            raise HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)}) from exc
        return success_response(result)

    @app.post("/internal/topic-score-snapshots/{snapshot_id}:verify", tags=["internal"], include_in_schema=False)
    def verify_topic_score_snapshot(
        snapshot_id: str,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        context = get_tenant_context()
        if context is None:
            raise HTTPException(status_code=400, detail={"code": "TENANT_CONTEXT_REQUIRED"})
        try:
            result = app.state.topic_opportunity_service.verify_snapshot(
                org_id=header_uuid(context.org_id, "X-Org-Id"), snapshot_id=snapshot_id,
                actor_id=header_uuid(context.actor_id, "X-Actor-Id"), trace_id=context.trace_id,
                idempotency_key=require_idempotency_key(idempotency_key),
            )
        except TopicOpportunityError as exc:
            status = 403 if exc.code == "TENANT_SCOPE_VIOLATION" else 409 if exc.code in {
                "IDEMPOTENCY_KEY_REUSED", "SCORING_SNAPSHOT_MISMATCH",
            } else 400
            raise HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)}) from exc
        return success_response(result)

    def provenance_context() -> tuple[Any, UUID, UUID]:
        context = get_tenant_context()
        if context is None:
            raise HTTPException(status_code=400, detail={"code": "TENANT_CONTEXT_REQUIRED"})
        return context, header_uuid(context.org_id, "X-Org-Id"), header_uuid(context.actor_id, "X-Actor-Id")

    def provenance_key(value: str | None) -> str:
        try:
            return require_idempotency_key(value)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_IDEMPOTENCY_KEY", "message": str(exc)}) from exc

    @app.post("/internal/sources:ingest", tags=["internal"], include_in_schema=False, status_code=201)
    @app.post("/v1/sources", tags=["provenance"], include_in_schema=False, status_code=201)
    def ingest_source(
        command: dict[str, Any],
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        context, org_id, actor_id = provenance_context()
        try:
            result = app.state.provenance_service.ingest(
                org_id=org_id,
                actor_id=actor_id,
                trace_id=context.trace_id,
                idempotency_key=provenance_key(idempotency_key),
                source_type=str(command.get("source_type", "")),
                canonical_url=command.get("canonical_url"),
                content=command.get("content", command.get("raw_content")),
                storage_object_ref=command.get("storage_object_ref"),
                terms_snapshot_ref=command.get("terms_snapshot_ref"),
                confidence=command.get("confidence", 0.5),
                fetch_method=command.get("fetch_method"),
                captured_at=command.get("captured_at"),
            )
        except SourceError as exc:
            raise provenance_error(exc) from exc
        return success_response(result)

    @app.post("/internal/sources/{source_id}/snapshots", tags=["internal"], include_in_schema=False, status_code=201)
    def create_source_snapshot(
        source_id: str,
        command: dict[str, Any],
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        context, org_id, actor_id = provenance_context()
        try:
            result = app.state.provenance_service.create_snapshot(
                org_id=org_id,
                source_id=source_id,
                actor_id=actor_id,
                trace_id=context.trace_id,
                idempotency_key=provenance_key(idempotency_key),
                content=command.get("content", command.get("raw_content")),
                storage_object_ref=command.get("storage_object_ref"),
                terms_snapshot_ref=command.get("terms_snapshot_ref"),
                confidence=command.get("confidence", 0.5),
                captured_at=command.get("captured_at"),
            )
        except SourceError as exc:
            raise provenance_error(exc) from exc
        return success_response(result)

    @app.post("/internal/source-snapshots/{snapshot_id}:{action}", tags=["internal"], include_in_schema=False)
    def transition_source_snapshot(
        snapshot_id: str,
        action: str,
        command: dict[str, Any] | None = None,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        if_match: str | None = Header(default=None, alias="If-Match"),
    ) -> dict[str, Any]:
        context, org_id, actor_id = provenance_context()
        payload = command or {}
        expected = payload.get("expected_version")
        if expected is None and if_match is not None:
            try:
                expected = int(if_match.strip().strip('"'))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail={"code": "INVALID_VERSION", "message": "If-Match must be an integer version"}) from exc
        try:
            result = app.state.provenance_service.transition_snapshot(
                org_id=org_id,
                snapshot_id=snapshot_id,
                actor_id=actor_id,
                trace_id=context.trace_id,
                idempotency_key=provenance_key(idempotency_key),
                action=action,
                expected_version=expected,
                reason=payload.get("reason"),
            )
        except SourceError as exc:
            raise provenance_error(exc) from exc
        return success_response(result)

    @app.post("/internal/source-snapshots/{snapshot_id}:verify", tags=["internal"], include_in_schema=False)
    def verify_source_snapshot(
        snapshot_id: str,
        command: dict[str, Any],
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        context, org_id, actor_id = provenance_context()
        try:
            result = app.state.provenance_service.verify_snapshot(
                org_id=org_id,
                snapshot_id=snapshot_id,
                content=command.get("content", command.get("raw_content")),
                actor_id=actor_id,
                trace_id=context.trace_id,
                idempotency_key=provenance_key(idempotency_key),
            )
        except SourceError as exc:
            raise provenance_error(exc) from exc
        return success_response(result)

    @app.get("/internal/sources", tags=["internal"], include_in_schema=False)
    def list_sources(x_org_id: str | None = Header(default=None, alias="X-Org-Id")) -> dict[str, Any]:
        return success_response(app.state.provenance_service.list_sources(org_id=header_uuid(x_org_id, "X-Org-Id")))

    @app.get("/internal/sources/{source_id}", tags=["internal"], include_in_schema=False)
    def get_source(source_id: str, x_org_id: str | None = Header(default=None, alias="X-Org-Id")) -> dict[str, Any]:
        try:
            source = app.state.provenance_service.get_source(
                org_id=header_uuid(x_org_id, "X-Org-Id"), source_id=source_id
            )
        except SourceError as exc:
            raise provenance_error(exc) from exc
        return success_response(source)

    def parse_if_match(value: str | None) -> int | None:
        if value is None:
            return None
        try:
            return int(value.strip().strip('"'))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_VERSION", "message": "If-Match must be an integer version"}) from exc

    @app.post("/internal/rights-records/{record_id}/versions", tags=["internal"], include_in_schema=False, status_code=201)
    @app.post("/v1/rights-records/{record_id}/versions", tags=["provenance"], include_in_schema=False, status_code=201)
    def create_rights_record_version(
        record_id: str,
        command: dict[str, Any],
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        if_match: str | None = Header(default=None, alias="If-Match"),
    ) -> dict[str, Any]:
        context, org_id, actor_id = provenance_context()
        try:
            result = app.state.rights_service.create_version(
                org_id=org_id,
                rights_record_id=record_id,
                actor_id=actor_id,
                trace_id=context.trace_id,
                idempotency_key=provenance_key(idempotency_key),
                source_snapshot_ids=command.get("source_snapshot_ids"),
                license_ref=command.get("license_ref"),
                contract_ref=command.get("contract_ref"),
                evidence_object_refs=command.get("evidence_object_refs"),
                terms_snapshot_hash=command.get("terms_snapshot_hash"),
                rights_holder=command.get("rights_holder"),
                permitted_regions=command.get("permitted_regions"),
                permitted_locales=command.get("permitted_locales"),
                permitted_media=command.get("permitted_media"),
                permitted_use=command.get("permitted_use"),
                valid_from=command.get("valid_from"),
                valid_to=command.get("valid_to"),
                policy_rule_version=command.get("policy_rule_version"),
                supersedes_version_id=command.get("supersedes_version_id"),
                expected_version=command["expected_version"] if "expected_version" in command else parse_if_match(if_match),
            )
        except RightsError as exc:
            raise rights_error(exc) from exc
        return success_response(result)

    @app.post("/internal/rights-records/{record_id}/versions/{version_id}/verify", tags=["internal"], include_in_schema=False)
    @app.post("/v1/rights-records/{record_id}/versions/{version_id}/verify", tags=["provenance"], include_in_schema=False)
    def verify_rights_record_version(
        record_id: str,
        version_id: str,
        command: dict[str, Any] | None = None,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        if_match: str | None = Header(default=None, alias="If-Match"),
    ) -> dict[str, Any]:
        context, org_id, actor_id = provenance_context()
        payload = command or {}
        try:
            result = app.state.rights_service.verify_version(
                org_id=org_id,
                rights_record_id=record_id,
                version_id=version_id,
                actor_id=actor_id,
                trace_id=context.trace_id,
                idempotency_key=provenance_key(idempotency_key),
                expected_version=payload["expected_version"] if "expected_version" in payload else parse_if_match(if_match),
                verification_reason=payload.get("verification_reason", payload.get("reason")),
                verified_at=payload.get("verified_at"),
            )
        except RightsError as exc:
            raise rights_error(exc) from exc
        return success_response(result)

    @app.post("/internal/rights-records/{record_id}/versions/{version_id}:{action}", tags=["internal"], include_in_schema=False)
    def transition_rights_record_version(
        record_id: str,
        version_id: str,
        action: str,
        command: dict[str, Any] | None = None,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        if_match: str | None = Header(default=None, alias="If-Match"),
    ) -> dict[str, Any]:
        context, org_id, actor_id = provenance_context()
        payload = command or {}
        try:
            result = app.state.rights_service.transition_version(
                org_id=org_id,
                rights_record_id=record_id,
                version_id=version_id,
                actor_id=actor_id,
                trace_id=context.trace_id,
                idempotency_key=provenance_key(idempotency_key),
                action=action,
                expected_version=payload["expected_version"] if "expected_version" in payload else parse_if_match(if_match),
                reason=payload.get("reason"),
            )
        except RightsError as exc:
            raise rights_error(exc) from exc
        return success_response(result)

    @app.get("/internal/rights-records/{record_id}", tags=["internal"], include_in_schema=False)
    def get_rights_record(record_id: str, x_org_id: str | None = Header(default=None, alias="X-Org-Id")) -> dict[str, Any]:
        try:
            record = app.state.rights_service.get_record(
                org_id=header_uuid(x_org_id, "X-Org-Id"), rights_record_id=record_id
            )
        except RightsError as exc:
            raise rights_error(exc) from exc
        return success_response(record)

    @app.post("/internal/rights-guard/check", tags=["internal"], include_in_schema=False)
    def check_rights_guard(
        command: dict[str, Any],
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        context, org_id, actor_id = provenance_context()
        try:
            result = app.state.rights_guard_service.check_authorization(
                org_id=org_id,
                rights_record_version_id=command.get("rights_record_version_id"),
                actor_id=actor_id,
                trace_id=context.trace_id,
                idempotency_key=provenance_key(idempotency_key),
                region=command.get("region"),
                locale=command.get("locale"),
                media=command.get("media"),
                use=command.get("use"),
                as_of=command.get("as_of"),
            )
        except RightsGuardError as exc:
            raise rights_guard_error(exc) from exc
        return success_response(result)

    @app.post("/internal/rights-guard/expiry-reminders", tags=["internal"], include_in_schema=False)
    def schedule_rights_expiry_reminders(
        command: dict[str, Any] | None = None,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        context, org_id, actor_id = provenance_context()
        payload = command or {}
        try:
            result = app.state.rights_guard_service.schedule_expiry_reminders(
                org_id=org_id, actor_id=actor_id, trace_id=context.trace_id,
                idempotency_key=provenance_key(idempotency_key),
                horizon_seconds=payload.get("horizon_seconds", 7 * 24 * 60 * 60),
                lead_seconds=payload.get("lead_seconds", 24 * 60 * 60), as_of=payload.get("as_of"),
            )
        except RightsGuardError as exc:
            raise rights_guard_error(exc) from exc
        return success_response(result)

    @app.post("/internal/rights-lineage", tags=["internal"], include_in_schema=False)
    def register_rights_lineage(
        command: dict[str, Any],
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        context, org_id, actor_id = provenance_context()
        try:
            result = app.state.rights_guard_service.register_lineage(
                org_id=org_id, actor_id=actor_id, trace_id=context.trace_id,
                idempotency_key=provenance_key(idempotency_key),
                rights_record_version_id=command.get("rights_record_version_id"),
                derived_type=command.get("derived_type"), derived_id=command.get("derived_id"),
                relation=command.get("relation", "derived_from"),
                parent_derived_type=command.get("parent_derived_type"),
                parent_derived_id=command.get("parent_derived_id"), metadata=command.get("metadata"),
            )
        except RightsGuardError as exc:
            raise rights_guard_error(exc) from exc
        return success_response(result)

    @app.post("/internal/rights-record-versions/{version_id}:complaint-hold", tags=["internal"], include_in_schema=False)
    def complaint_hold_rights_version(
        version_id: str,
        command: dict[str, Any],
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        context, org_id, actor_id = provenance_context()
        try:
            result = app.state.rights_guard_service.freeze_complaint(
                org_id=org_id, rights_record_id=command.get("rights_record_id"), version_id=version_id,
                actor_id=actor_id, trace_id=context.trace_id, idempotency_key=provenance_key(idempotency_key),
                expected_version=command.get("expected_version"), reason=command.get("reason"),
            )
        except RightsGuardError as exc:
            raise rights_guard_error(exc) from exc
        except RightsError as exc:
            raise rights_error(exc) from exc
        return success_response(result)

    # KNOW-001: Entity/Claim/Evidence commands.  These routes are internal
    # composition boundaries today; the same use cases back the versioned API
    # aliases so no caller can bypass tenant and idempotency checks.
    @app.post("/internal/entities", tags=["internal"], include_in_schema=False, status_code=201)
    @app.post("/v1/entities", tags=["knowledge"], include_in_schema=False, status_code=201)
    def create_entity(
        command: dict[str, Any],
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        context, org_id, actor_id = provenance_context()
        try:
            result = app.state.knowledge_service.create_entity(
                org_id=org_id, actor_id=actor_id, trace_id=context.trace_id,
                idempotency_key=provenance_key(idempotency_key),
                canonical_name=command.get("canonical_name", command.get("name")),
                aliases=command.get("aliases", []), entity_type=command.get("entity_type", "concept"),
            )
        except KnowledgeError as exc:
            raise knowledge_error(exc) from exc
        return success_response(result)

    @app.post("/internal/entities/{entity_id}:{action}", tags=["internal"], include_in_schema=False)
    def transition_entity(
        entity_id: str,
        action: str,
        command: dict[str, Any] | None = None,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        if_match: str | None = Header(default=None, alias="If-Match"),
    ) -> dict[str, Any]:
        context, org_id, actor_id = provenance_context()
        payload = command or {}
        expected = payload.get("expected_version")
        if expected is None and if_match is not None:
            expected = parse_if_match(if_match)
        if expected is None:
            expected = 0
        try:
            result = app.state.knowledge_service.transition_entity(
                org_id=org_id, entity_id=entity_id, actor_id=actor_id, trace_id=context.trace_id,
                idempotency_key=provenance_key(idempotency_key), action=action,
                expected_version=expected, reason=payload.get("reason"),
            )
        except KnowledgeError as exc:
            raise knowledge_error(exc) from exc
        return success_response(result)

    @app.get("/internal/entities", tags=["internal"], include_in_schema=False)
    def list_knowledge_entities(
        x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
        status: str | None = None,
    ) -> dict[str, Any]:
        try:
            result = app.state.knowledge_service.list_entities(org_id=header_uuid(x_org_id, "X-Org-Id"), status=status)
        except KnowledgeError as exc:
            raise knowledge_error(exc) from exc
        return success_response(result)

    @app.get("/internal/entities/{entity_id}", tags=["internal"], include_in_schema=False)
    def get_knowledge_entity(entity_id: str, x_org_id: str | None = Header(default=None, alias="X-Org-Id")) -> dict[str, Any]:
        try:
            result = app.state.knowledge_service.get_entity(
                org_id=header_uuid(x_org_id, "X-Org-Id"), entity_id=entity_id
            )
        except KnowledgeError as exc:
            raise knowledge_error(exc) from exc
        return success_response(result)

    @app.post("/internal/claims", tags=["internal"], include_in_schema=False, status_code=201)
    @app.post("/v1/claims", tags=["knowledge"], include_in_schema=False, status_code=201)
    def create_claim(
        command: dict[str, Any],
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        context, org_id, actor_id = provenance_context()
        try:
            result = app.state.knowledge_service.create_claim(
                org_id=org_id, actor_id=actor_id, trace_id=context.trace_id,
                idempotency_key=provenance_key(idempotency_key), entity_ids=command.get("entity_ids", []),
                statement=command.get("statement", ""), fact_type=command.get("fact_type", "fact"),
                applicable_versions=command.get("applicable_versions", []),
                applicable_regions=command.get("applicable_regions", []),
                applicable_locales=command.get("applicable_locales", []),
                valid_from=command.get("valid_from"), valid_to=command.get("valid_to"),
                review_due_at=command.get("review_due_at"), supersedes_claim_id=command.get("supersedes_claim_id"),
            )
        except KnowledgeError as exc:
            raise knowledge_error(exc) from exc
        return success_response(result)

    @app.post("/internal/claims/{claim_id}:{action}", tags=["internal"], include_in_schema=False)
    def transition_claim(
        claim_id: str,
        action: str,
        command: dict[str, Any] | None = None,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        if_match: str | None = Header(default=None, alias="If-Match"),
    ) -> dict[str, Any]:
        context, org_id, actor_id = provenance_context()
        payload = command or {}
        expected = payload.get("expected_version")
        if expected is None and if_match is not None:
            expected = parse_if_match(if_match)
        if expected is None:
            expected = 0
        try:
            if action == "freshness":
                result = app.state.knowledge_service.mark_claim_freshness(
                    org_id=org_id, claim_id=claim_id, actor_id=actor_id, trace_id=context.trace_id,
                    idempotency_key=provenance_key(idempotency_key),
                    freshness_status=payload.get("freshness_status", "review_due"),
                    expected_version=expected, reason=payload.get("reason"),
                )
            else:
                result = app.state.knowledge_service.transition_claim(
                    org_id=org_id, claim_id=claim_id, actor_id=actor_id, trace_id=context.trace_id,
                    idempotency_key=provenance_key(idempotency_key), action=action,
                    expected_version=expected, reason=payload.get("reason"),
                )
        except KnowledgeError as exc:
            raise knowledge_error(exc) from exc
        return success_response(result)

    @app.get("/internal/claims", tags=["internal"], include_in_schema=False)
    def list_knowledge_claims(
        x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
        status: str | None = None,
        entity_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            result = app.state.knowledge_service.list_claims(
                org_id=header_uuid(x_org_id, "X-Org-Id"), status=status, entity_id=entity_id
            )
        except KnowledgeError as exc:
            raise knowledge_error(exc) from exc
        return success_response(result)

    @app.get("/internal/claims/{claim_id}", tags=["internal"], include_in_schema=False)
    def get_knowledge_claim(claim_id: str, x_org_id: str | None = Header(default=None, alias="X-Org-Id")) -> dict[str, Any]:
        try:
            result = app.state.knowledge_service.get_claim(
                org_id=header_uuid(x_org_id, "X-Org-Id"), claim_id=claim_id
            )
        except KnowledgeError as exc:
            raise knowledge_error(exc) from exc
        return success_response(result)

    @app.post("/internal/evidences", tags=["internal"], include_in_schema=False, status_code=201)
    @app.post("/v1/evidences", tags=["knowledge"], include_in_schema=False, status_code=201)
    def create_evidence(
        command: dict[str, Any],
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        context, org_id, actor_id = provenance_context()
        try:
            result = app.state.knowledge_service.create_evidence(
                org_id=org_id, actor_id=actor_id, trace_id=context.trace_id,
                idempotency_key=provenance_key(idempotency_key),
                source_snapshot_id=command.get("source_snapshot_id"), claim_id=command.get("claim_id"),
                rights_record_version_id=command.get("rights_record_version_id"),
                evidence_type=command.get("evidence_type", "quote"), quote=command.get("quote", ""),
                locator=command.get("locator"), applicable_versions=command.get("applicable_versions", []),
                applicable_regions=command.get("applicable_regions", []),
                applicable_locales=command.get("applicable_locales", []),
                valid_from=command.get("valid_from"), valid_to=command.get("valid_to"),
                review_due_at=command.get("review_due_at"), captured_at=command.get("captured_at"),
            )
        except KnowledgeError as exc:
            raise knowledge_error(exc) from exc
        return success_response(result)

    @app.post("/internal/evidences/{evidence_id}:{action}", tags=["internal"], include_in_schema=False)
    def transition_evidence(
        evidence_id: str,
        action: str,
        command: dict[str, Any] | None = None,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        if_match: str | None = Header(default=None, alias="If-Match"),
    ) -> dict[str, Any]:
        context, org_id, actor_id = provenance_context()
        payload = command or {}
        expected = payload.get("expected_version")
        if expected is None and if_match is not None:
            expected = parse_if_match(if_match)
        if expected is None:
            expected = 0
        try:
            result = app.state.knowledge_service.transition_evidence(
                org_id=org_id, evidence_id=evidence_id, actor_id=actor_id, trace_id=context.trace_id,
                idempotency_key=provenance_key(idempotency_key), action=action,
                expected_version=expected, reason=payload.get("reason"),
            )
        except KnowledgeError as exc:
            raise knowledge_error(exc) from exc
        return success_response(result)

    @app.post("/internal/claims/{claim_id}/evidence", tags=["internal"], include_in_schema=False)
    def link_claim_evidence(
        claim_id: str,
        command: dict[str, Any],
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        context, org_id, actor_id = provenance_context()
        try:
            result = app.state.knowledge_service.link_evidence(
                org_id=org_id, claim_id=claim_id, evidence_id=command.get("evidence_id"),
                relation_type=command.get("relation_type", "supports"), actor_id=actor_id,
                trace_id=context.trace_id, idempotency_key=provenance_key(idempotency_key),
            )
        except KnowledgeError as exc:
            raise knowledge_error(exc) from exc
        return success_response(result)

    @app.get("/internal/evidences", tags=["internal"], include_in_schema=False)
    def list_knowledge_evidence(
        x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
        claim_id: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        try:
            result = app.state.knowledge_service.list_evidence(
                org_id=header_uuid(x_org_id, "X-Org-Id"), claim_id=claim_id, status=status
            )
        except KnowledgeError as exc:
            raise knowledge_error(exc) from exc
        return success_response(result)

    @app.get("/internal/evidences/{evidence_id}", tags=["internal"], include_in_schema=False)
    def get_knowledge_evidence(evidence_id: str, x_org_id: str | None = Header(default=None, alias="X-Org-Id")) -> dict[str, Any]:
        try:
            result = app.state.knowledge_service.get_evidence(
                org_id=header_uuid(x_org_id, "X-Org-Id"), evidence_id=evidence_id
            )
        except KnowledgeError as exc:
            raise knowledge_error(exc) from exc
        return success_response(result)

    # KNOW-002: KnowledgeCore is a versioned, read-only snapshot of verified
    # Claim/Evidence facts.  Refresh never mutates the prior version.
    @app.post("/internal/knowledge-cores", tags=["internal"], include_in_schema=False, status_code=201)
    def create_knowledge_core(
        command: dict[str, Any],
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        context, org_id, actor_id = provenance_context()
        try:
            result = app.state.knowledge_core_service.create_core(
                org_id=org_id, actor_id=actor_id, trace_id=context.trace_id,
                idempotency_key=provenance_key(idempotency_key),
                topic_brief_id=command.get("topic_brief_id"), entity_ids=command.get("entity_ids"),
                claim_ids=command.get("claim_ids", []), evidence_ids=command.get("evidence_ids"),
                conflict_claim_groups=command.get("conflict_claim_groups"),
            )
        except KnowledgeError as exc:
            raise knowledge_error(exc) from exc
        return success_response(result)

    @app.post("/internal/knowledge-cores/{core_id}:validate", tags=["internal"], include_in_schema=False)
    def validate_knowledge_core(
        core_id: str,
        command: dict[str, Any] | None = None,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        if_match: str | None = Header(default=None, alias="If-Match"),
    ) -> dict[str, Any]:
        context, org_id, actor_id = provenance_context()
        payload = command or {}
        expected = payload.get("expected_version")
        if expected is None and if_match is not None:
            expected = parse_if_match(if_match)
        try:
            result = app.state.knowledge_core_service.validate_core(
                org_id=org_id, core_id=core_id, actor_id=actor_id, trace_id=context.trace_id,
                idempotency_key=provenance_key(idempotency_key), expected_version=expected,
            )
        except KnowledgeError as exc:
            raise knowledge_error(exc) from exc
        return success_response(result)

    @app.post("/internal/knowledge-cores/{core_id}:refresh", tags=["internal"], include_in_schema=False)
    def refresh_knowledge_core(
        core_id: str,
        command: dict[str, Any] | None = None,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        if_match: str | None = Header(default=None, alias="If-Match"),
    ) -> dict[str, Any]:
        context, org_id, actor_id = provenance_context()
        payload = command or {}
        expected = payload.get("expected_version")
        if expected is None and if_match is not None:
            expected = parse_if_match(if_match)
        try:
            result = app.state.knowledge_core_service.refresh_core(
                org_id=org_id, core_id=core_id, actor_id=actor_id, trace_id=context.trace_id,
                idempotency_key=provenance_key(idempotency_key), expected_version=expected,
                entity_ids=payload.get("entity_ids"), claim_ids=payload.get("claim_ids"),
                evidence_ids=payload.get("evidence_ids"), conflict_claim_groups=payload.get("conflict_claim_groups"),
            )
        except KnowledgeError as exc:
            raise knowledge_error(exc) from exc
        return success_response(result)

    @app.get("/internal/knowledge-cores", tags=["internal"], include_in_schema=False)
    def list_knowledge_cores(
        x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
        status: str | None = None,
    ) -> dict[str, Any]:
        try:
            result = app.state.knowledge_core_service.list_cores(
                org_id=header_uuid(x_org_id, "X-Org-Id"), status=status
            )
        except KnowledgeError as exc:
            raise knowledge_error(exc) from exc
        return success_response(result)

    @app.get("/internal/knowledge-cores/{core_id}", tags=["internal"], include_in_schema=False)
    def get_knowledge_core(core_id: str, x_org_id: str | None = Header(default=None, alias="X-Org-Id")) -> dict[str, Any]:
        try:
            result = app.state.knowledge_core_service.get_core(
                org_id=header_uuid(x_org_id, "X-Org-Id"), core_id=core_id
            )
        except KnowledgeError as exc:
            raise knowledge_error(exc) from exc
        return success_response(result)

    # CANON-001: channel-neutral editorial roots and immutable versions.
    @app.post("/internal/canonical-contents", tags=["internal"], include_in_schema=False, status_code=201)
    @app.post("/v1/canonical-contents", tags=["knowledge"], include_in_schema=False, status_code=201)
    def create_canonical_content(
        command: dict[str, Any],
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        context, org_id, actor_id = provenance_context()
        nested = command.get("version")
        if nested is None:
            content_keys = {"title", "abstract", "sections", "claims", "code_blocks", "examples", "limitations",
                            "source_snapshot_refs", "source_snapshot_ids", "knowledge_core_version",
                            "knowledge_core_version_id", "input_snapshot_hash", "content_hash", "rights_snapshot_ids",
                            "freshness_status", "freshness_checked_at", "freshness_expires_at", "freshness_ttl_days",
                            "conflict_set_ids"}
            nested = {key: command[key] for key in content_keys if key in command}
        try:
            result = app.state.canonical_content_service.create(
                org_id=org_id, actor_id=actor_id, trace_id=context.trace_id,
                idempotency_key=provenance_key(idempotency_key),
                topic_brief_id=command.get("topic_brief_id"), stable_key=command.get("stable_key"),
                version=nested or None,
            )
        except CanonicalContentError as exc:
            raise canonical_content_error(exc) from exc
        return success_response(result)

    @app.post("/internal/canonical-contents/{content_id}/versions", tags=["internal"], include_in_schema=False, status_code=201)
    @app.post("/v1/canonical-contents/{content_id}/versions", tags=["knowledge"], include_in_schema=False, status_code=201)
    def create_canonical_content_version(
        content_id: str,
        command: dict[str, Any],
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        context, org_id, actor_id = provenance_context()
        payload = command.get("version", command)
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail={"code": "INVALID_CANONICAL_COMMAND"})
        try:
            result = app.state.canonical_content_service.create_version(
                org_id=org_id, canonical_content_id=content_id, actor_id=actor_id,
                trace_id=context.trace_id, idempotency_key=provenance_key(idempotency_key), content=payload,
            )
        except CanonicalContentError as exc:
            raise canonical_content_error(exc) from exc
        return success_response(result)

    @app.post("/internal/canonical-contents/{content_id}:submit-review", tags=["internal"], include_in_schema=False)
    def submit_canonical_content_review(
        content_id: str,
        command: dict[str, Any] | None = None,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        if_match: str | None = Header(default=None, alias="If-Match"),
    ) -> dict[str, Any]:
        context, org_id, actor_id = provenance_context()
        payload = command or {}
        expected = payload.get("expected_version")
        if expected is None and if_match is not None:
            expected = parse_if_match(if_match)
        try:
            result = app.state.canonical_content_service.submit_review(
                org_id=org_id, canonical_content_id=content_id, actor_id=actor_id,
                trace_id=context.trace_id, idempotency_key=provenance_key(idempotency_key),
                expected_version=expected,
            )
        except CanonicalContentError as exc:
            raise canonical_content_error(exc) from exc
        return success_response(result)

    @app.post("/internal/canonical-contents/{content_id}:assess-freshness", tags=["internal"], include_in_schema=False)
    def assess_canonical_content_freshness(
        content_id: str,
        command: dict[str, Any] | None = None,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        context, org_id, actor_id = provenance_context()
        payload = command or {}
        try:
            result = app.state.canonical_content_service.assess_freshness(
                org_id=org_id, canonical_content_id=content_id, actor_id=actor_id,
                trace_id=context.trace_id, idempotency_key=provenance_key(idempotency_key),
                version_id=payload.get("version_id"), version_no=payload.get("version_no"),
                now=payload.get("now"), force_stale=bool(payload.get("force_stale", False)),
                conflict_set_ids=payload.get("conflict_set_ids"),
                review_window_seconds=payload.get("review_window_seconds", 7 * 24 * 60 * 60),
            )
        except CanonicalContentError as exc:
            raise canonical_content_error(exc) from exc
        return success_response(result)

    @app.post("/internal/canonical-contents/{content_id}:enqueue-refresh", tags=["internal"], include_in_schema=False)
    def enqueue_canonical_content_refresh(
        content_id: str,
        command: dict[str, Any] | None = None,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        context, org_id, actor_id = provenance_context()
        payload = command or {}
        try:
            result = app.state.canonical_content_service.enqueue_refresh(
                org_id=org_id, canonical_content_id=content_id, actor_id=actor_id,
                trace_id=context.trace_id, idempotency_key=provenance_key(idempotency_key),
                version_id=payload.get("version_id"), version_no=payload.get("version_no"),
                reason=payload.get("reason", "manual"), priority=payload.get("priority", 50),
                available_at=payload.get("available_at"),
            )
        except CanonicalContentError as exc:
            raise canonical_content_error(exc) from exc
        return success_response(result)

    @app.get("/internal/canonical-refresh-queue", tags=["internal"], include_in_schema=False)
    def list_canonical_refresh_queue(
        status: str | None = None,
        canonical_content_version_id: str | None = None,
        x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
    ) -> dict[str, Any]:
        try:
            result = app.state.canonical_content_service.list_refresh_queue(
                org_id=header_uuid(x_org_id, "X-Org-Id"), status=status,
                canonical_content_version_id=canonical_content_version_id,
            )
        except CanonicalContentError as exc:
            raise canonical_content_error(exc) from exc
        return success_response({"items": result})

    @app.post("/internal/canonical-refresh-queue/{queue_id}:claim", tags=["internal"], include_in_schema=False)
    def claim_canonical_refresh(
        queue_id: str,
        command: dict[str, Any] | None = None,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        context, org_id, actor_id = provenance_context()
        payload = command or {}
        try:
            result = app.state.canonical_content_service.claim_refresh(
                org_id=org_id, queue_id=queue_id, actor_id=actor_id,
                trace_id=context.trace_id, idempotency_key=provenance_key(idempotency_key),
                lease_seconds=payload.get("lease_seconds", 300), now=payload.get("now"),
            )
        except CanonicalContentError as exc:
            raise canonical_content_error(exc) from exc
        return success_response(result)

    @app.post("/internal/canonical-refresh-queue/{queue_id}:complete", tags=["internal"], include_in_schema=False)
    def complete_canonical_refresh(
        queue_id: str,
        command: dict[str, Any] | None = None,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        context, org_id, actor_id = provenance_context()
        payload = command or {}
        try:
            result = app.state.canonical_content_service.complete_refresh(
                org_id=org_id, queue_id=queue_id, actor_id=actor_id,
                trace_id=context.trace_id, idempotency_key=provenance_key(idempotency_key),
                expected_attempts=payload.get("expected_attempts"), now=payload.get("now"),
            )
        except CanonicalContentError as exc:
            raise canonical_content_error(exc) from exc
        return success_response(result)

    @app.get("/internal/canonical-contents/{content_id}", tags=["internal"], include_in_schema=False)
    def get_canonical_content(content_id: str, x_org_id: str | None = Header(default=None, alias="X-Org-Id")) -> dict[str, Any]:
        try:
            result = app.state.canonical_content_service.get(
                org_id=header_uuid(x_org_id, "X-Org-Id"), canonical_content_id=content_id
            )
        except CanonicalContentError as exc:
            raise canonical_content_error(exc) from exc
        return success_response(result)

    @app.get("/internal/canonical-contents/{content_id}/versions", tags=["internal"], include_in_schema=False)
    @app.get("/v1/canonical-contents/{content_id}/versions", tags=["knowledge"], include_in_schema=False)
    def list_canonical_content_versions(
        content_id: str,
        x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
        from_version_id: str | None = None,
        to_version_id: str | None = None,
        from_version_no: int | None = None,
        to_version_no: int | None = None,
    ) -> dict[str, Any]:
        try:
            result = app.state.canonical_content_service.list_versions(
                org_id=header_uuid(x_org_id, "X-Org-Id"), canonical_content_id=content_id,
                from_version_id=from_version_id, to_version_id=to_version_id,
                from_version_no=from_version_no, to_version_no=to_version_no,
            )
        except CanonicalContentError as exc:
            raise canonical_content_error(exc) from exc
        return success_response(result)

    @app.post("/internal/dev-identities", tags=["internal"], include_in_schema=False)
    def create_dev_identity(
        command: dict[str, Any],
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        x_trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> dict[str, Any]:
        if not idempotency_key or not idempotency_key.strip():
            raise HTTPException(status_code=400, detail={"code": "TENANT_CONTEXT_REQUIRED", "message": "Idempotency-Key header is required"})
        try:
            identity = app.state.iam_service.create_identity(
                org_id=header_uuid(command.get("org_id"), "org_id"),
                subject=str(command["subject"]),
                display_name=str(command["display_name"]),
                idempotency_key=idempotency_key.strip(),
                trace_id=x_trace_id or str(uuid4()),
            )
        except KeyError as exc:
            raise HTTPException(status_code=400, detail={"code": "TENANT_CONTEXT_REQUIRED", "message": f"missing {exc.args[0]}"}) from exc
        except IamError as exc:
            raise iam_error(exc) from exc
        return success_response(identity.as_contract())

    @app.get("/internal/me", tags=["internal"], include_in_schema=False)
    def get_me(
        x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
        x_actor_id: str | None = Header(default=None, alias="X-Actor-Id"),
        x_trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> dict[str, Any]:
        try:
            context = app.state.iam_service.context(
                org_id=header_uuid(x_org_id, "X-Org-Id"),
                actor_id=header_uuid(x_actor_id, "X-Actor-Id"),
                trace_id=x_trace_id or str(uuid4()),
            )
        except IamError as exc:
            raise iam_error(exc) from exc
        return success_response(context.as_contract())

    @app.post("/internal/role-bindings", tags=["internal"], include_in_schema=False)
    def create_role_binding(
        command: dict[str, Any],
        x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
        x_actor_id: str | None = Header(default=None, alias="X-Actor-Id"),
        x_trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    ) -> dict[str, Any]:
        try:
            org_id = header_uuid(x_org_id, "X-Org-Id")
            actor_id = header_uuid(x_actor_id, "X-Actor-Id")
            context = app.state.iam_service.context(org_id=org_id, actor_id=actor_id, trace_id=x_trace_id or str(uuid4()))
            binding = app.state.iam_service.bind_role(
                context=context,
                actor_id=header_uuid(command.get("actor_id"), "actor_id"),
                role=str(command.get("role", "")),
            )
        except IamError as exc:
            raise iam_error(exc) from exc
        return success_response(binding.as_contract())

    @app.post("/internal/account-profiles", tags=["internal"], include_in_schema=False)
    def create_account_profile(command: dict[str, Any], x_org_id: str | None = Header(default=None, alias="X-Org-Id")) -> dict[str, Any]:
        try:
            profile = app.state.account_service.create_profile(
                org_id=header_uuid(x_org_id, "X-Org-Id"),
                platform_id=header_uuid(command.get("platform_id"), "platform_id"),
                profile_kind=str(command.get("profile_kind", "")),
                display_name=str(command.get("display_name", "")),
                status=str(command.get("status", "planned")),
            )
        except AccountError as exc:
            raise account_error(exc) from exc
        return success_response(profile.as_contract())

    @app.post("/internal/distribution-targets/{target_id}/versions", tags=["internal"], include_in_schema=False)
    def create_distribution_target_version(target_id: str, command: dict[str, Any], x_org_id: str | None = Header(default=None, alias="X-Org-Id"), x_actor_id: str | None = Header(default=None, alias="X-Actor-Id")) -> dict[str, Any]:
        try:
            version = app.state.account_service.create_version(
                org_id=header_uuid(x_org_id, "X-Org-Id"),
                target_id=UUID(target_id),
                delivery_mode=str(command.get("delivery_mode", "")),
                policy_snapshot_ref=str(command.get("policy_snapshot_ref", "")),
                config_json=dict(command.get("config_json", {})),
                created_by=header_uuid(x_actor_id, "X-Actor-Id"),
            )
        except (ValueError, AccountError) as exc:
            if isinstance(exc, AccountError):
                raise account_error(exc) from exc
            raise HTTPException(status_code=400, detail={"code": "INVALID_TARGET", "message": str(exc)}) from exc
        return success_response(version.as_contract())

    @app.post("/internal/workflow-runs", tags=["internal"], include_in_schema=False)
    def create_workflow_run(command: dict[str, Any], x_org_id: str | None = Header(default=None, alias="X-Org-Id")) -> dict[str, Any]:
        try:
            run = app.state.workflow_service.start(
                org_id=header_uuid(x_org_id, "X-Org-Id"),
                workflow_key=str(command.get("workflow_key", "")),
                workflow_version=int(command.get("workflow_version", 0)),
                input_payload=command.get("input_payload", {}),
            )
        except WorkflowError as exc:
            raise workflow_error(exc) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_WORKFLOW_COMMAND", "message": str(exc)}) from exc
        return success_response({"id": str(run.id), "org_id": str(run.org_id), "workflow_key": run.workflow_key, "workflow_version": run.workflow_version, "status": run.status, "input_hash": run.input_hash, "version": run.version, "created_at": run.created_at})

    def workflow_run_command(run_id: str, command: dict[str, Any] | None, action: str, x_org_id: str | None) -> dict[str, Any]:
        payload = command or {}
        try:
            org_id = header_uuid(x_org_id, "X-Org-Id")
            expected_version = int(payload["expected_version"])
            parsed_id = UUID(run_id)
            run = getattr(app.state.workflow_service, action)(org_id=org_id, run_id=parsed_id, expected_version=expected_version)
        except WorkflowError as exc:
            raise workflow_error(exc) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_WORKFLOW_COMMAND", "message": str(exc)}) from exc
        return success_response({"id": str(run.id), "org_id": str(run.org_id), "status": run.status, "version": run.version, "replayed_from_run_id": str(run.replayed_from_run_id) if run.replayed_from_run_id else None})

    @app.post("/internal/workflow-runs/{run_id}:pause", tags=["internal"], include_in_schema=False)
    def pause_workflow_run(run_id: str, command: dict[str, Any] | None = None, x_org_id: str | None = Header(default=None, alias="X-Org-Id")) -> dict[str, Any]:
        return workflow_run_command(run_id, command, "pause", x_org_id)

    @app.post("/internal/workflow-runs/{run_id}:resume", tags=["internal"], include_in_schema=False)
    def resume_workflow_run(run_id: str, command: dict[str, Any] | None = None, x_org_id: str | None = Header(default=None, alias="X-Org-Id")) -> dict[str, Any]:
        return workflow_run_command(run_id, command, "resume", x_org_id)

    @app.post("/internal/workflow-runs/{run_id}:replay", tags=["internal"], include_in_schema=False)
    def replay_workflow_run(run_id: str, command: dict[str, Any] | None = None, x_org_id: str | None = Header(default=None, alias="X-Org-Id")) -> dict[str, Any]:
        return workflow_run_command(run_id, command, "replay", x_org_id)

    @app.post("/internal/workflow-runs/{run_id}/human-tasks", tags=["internal"], include_in_schema=False)
    def create_workflow_human_task(run_id: str, command: dict[str, Any] | None = None, x_org_id: str | None = Header(default=None, alias="X-Org-Id")) -> dict[str, Any]:
        try:
            payload = command or {}
            task = app.state.workflow_service.create_human_task(
                org_id=header_uuid(x_org_id, "X-Org-Id"),
                run_id=UUID(run_id),
                due_at=datetime.fromisoformat(payload["due_at"]) if payload.get("due_at") else None,
            )
        except WorkflowError as exc:
            raise workflow_error(exc) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_WORKFLOW_COMMAND", "message": str(exc)}) from exc
        return success_response({"id": str(task.id), "run_id": str(task.run_id), "status": task.status, "version": task.version, "due_at": task.due_at.isoformat() if task.due_at else None})

    def human_task_command(task_id: str, command: dict[str, Any] | None, action: str, x_org_id: str | None, x_actor_id: str | None) -> dict[str, Any]:
        try:
            payload = command or {}
            org_id = header_uuid(x_org_id, "X-Org-Id")
            actor_id = header_uuid(x_actor_id, "X-Actor-Id")
            task = app.state.workflow_service.update_task(
                org_id=org_id,
                task_id=UUID(task_id),
                actor_id=actor_id,
                expected_version=int(payload["expected_version"]),
                action=action,
            )
        except WorkflowError as exc:
            raise workflow_error(exc) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_WORKFLOW_COMMAND", "message": str(exc)}) from exc
        return success_response({"id": str(task.id), "run_id": str(task.run_id), "status": task.status, "version": task.version, "assignee_actor_id": str(task.assignee_actor_id) if task.assignee_actor_id else None})

    @app.post("/internal/human-tasks/{task_id}:claim", tags=["internal"], include_in_schema=False)
    def claim_workflow_human_task(task_id: str, command: dict[str, Any] | None = None, x_org_id: str | None = Header(default=None, alias="X-Org-Id"), x_actor_id: str | None = Header(default=None, alias="X-Actor-Id")) -> dict[str, Any]:
        try:
            payload = command or {}
            task = app.state.workflow_service.claim_task(org_id=header_uuid(x_org_id, "X-Org-Id"), task_id=UUID(task_id), actor_id=header_uuid(x_actor_id, "X-Actor-Id"), expected_version=int(payload["expected_version"]))
        except WorkflowError as exc:
            raise workflow_error(exc) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_WORKFLOW_COMMAND", "message": str(exc)}) from exc
        return success_response({"id": str(task.id), "run_id": str(task.run_id), "status": task.status, "version": task.version, "assignee_actor_id": str(task.assignee_actor_id) if task.assignee_actor_id else None})

    @app.post("/internal/human-tasks/{task_id}:{action}", tags=["internal"], include_in_schema=False)
    def update_workflow_human_task(task_id: str, action: str, command: dict[str, Any] | None = None, x_org_id: str | None = Header(default=None, alias="X-Org-Id"), x_actor_id: str | None = Header(default=None, alias="X-Actor-Id")) -> dict[str, Any]:
        if action not in {"start", "submit", "complete"}:
            raise HTTPException(status_code=404, detail={"code": "UNKNOWN_WORKFLOW_ACTION"})
        return human_task_command(task_id, command, action, x_org_id, x_actor_id)

    @app.post("/internal/task-jobs:claim", tags=["internal"], include_in_schema=False)
    def claim_task(
        command: dict[str, Any] | None = None,
        x_worker_id: str | None = Header(default=None, alias="X-Worker-Id"),
    ) -> dict[str, Any]:
        if task_claim_store is None:
            raise HTTPException(status_code=503, detail={"code": "TASK_CLAIM_NOT_CONFIGURED"})
        require_worker(x_worker_id)
        payload = command or {}
        try:
            leases = task_claim_store.claim(
                org_id=payload["org_id"],
                worker_id=require_worker(x_worker_id),
                limit=int(payload.get("limit", 1)),
            )
        except KeyError as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_CLAIM_COMMAND", "message": f"missing {exc.args[0]}"}) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_CLAIM_COMMAND", "message": str(exc)}) from exc
        except TaskClaimError as exc:
            raise claim_error(exc) from exc
        return success_response([lease.as_contract() for lease in leases])

    @app.post("/internal/task-jobs/{job_id}:heartbeat", tags=["internal"], include_in_schema=False)
    def heartbeat_task(
        job_id: str,
        command: dict[str, Any] | None = None,
        x_worker_id: str | None = Header(default=None, alias="X-Worker-Id"),
    ) -> dict[str, Any]:
        if task_claim_store is None:
            raise HTTPException(status_code=503, detail={"code": "TASK_CLAIM_NOT_CONFIGURED"})
        require_worker(x_worker_id)
        payload = command or {}
        try:
            lease = task_claim_store.heartbeat(
                job_id=job_id,
                lease_token=payload["lease_token"],
                worker_id=require_worker(x_worker_id),
                org_id=payload.get("org_id"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_CLAIM_COMMAND", "message": f"missing {exc.args[0]}"}) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_CLAIM_COMMAND", "message": str(exc)}) from exc
        except TaskClaimError as exc:
            raise claim_error(exc) from exc
        return success_response(lease.as_contract())

    @app.post("/internal/task-jobs/{job_id}:complete", tags=["internal"], include_in_schema=False)
    def complete_task(
        job_id: str,
        command: dict[str, Any] | None = None,
        x_worker_id: str | None = Header(default=None, alias="X-Worker-Id"),
    ) -> dict[str, Any]:
        if task_claim_store is None:
            raise HTTPException(status_code=503, detail={"code": "TASK_CLAIM_NOT_CONFIGURED"})
        require_worker(x_worker_id)
        payload = command or {}
        try:
            job = task_claim_store.complete(
                job_id=job_id,
                lease_token=payload["lease_token"],
                worker_id=require_worker(x_worker_id),
                expected_version=payload.get("expected_version"),
                org_id=payload.get("org_id"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_CLAIM_COMMAND", "message": f"missing {exc.args[0]}"}) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_CLAIM_COMMAND", "message": str(exc)}) from exc
        except TaskClaimError as exc:
            raise claim_error(exc) from exc
        return success_response(job.as_contract())

    @app.post("/internal/task-jobs/{job_id}:fail", tags=["internal"], include_in_schema=False)
    def fail_task(
        job_id: str,
        command: dict[str, Any] | None = None,
        x_worker_id: str | None = Header(default=None, alias="X-Worker-Id"),
    ) -> dict[str, Any]:
        if task_claim_store is None:
            raise HTTPException(status_code=503, detail={"code": "TASK_CLAIM_NOT_CONFIGURED"})
        payload = command or {}
        try:
            job = task_claim_store.fail(
                job_id=job_id,
                lease_token=payload["lease_token"],
                worker_id=require_worker(x_worker_id),
                error=payload["error"],
                expected_version=payload.get("expected_version"),
                org_id=payload.get("org_id"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_CLAIM_COMMAND", "message": f"missing {exc.args[0]}"}) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_CLAIM_COMMAND", "message": str(exc)}) from exc
        except TaskClaimError as exc:
            raise claim_error(exc) from exc
        return success_response(job.as_contract())

    @app.post("/internal/task-jobs/{job_id}:retry", tags=["internal"], include_in_schema=False)
    def retry_task(
        job_id: str,
        command: dict[str, Any] | None = None,
        x_worker_id: str | None = Header(default=None, alias="X-Worker-Id"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        if task_failure_store is None:
            raise HTTPException(status_code=503, detail={"code": "TASK_FAILURE_NOT_CONFIGURED"})
        require_worker(x_worker_id)
        payload = command or {}
        try:
            key = require_idempotency_key(idempotency_key)
            if payload.get("error_class") is not None:
                decision = task_failure_store.record_failure(
                    job_id=job_id,
                    org_id=payload["org_id"],
                    error_class=payload["error_class"],
                    error_code=payload.get("error_code", "TASK_FAILURE"),
                    trace_id=payload.get("trace_id", str(uuid4())),
                    attempt_count=payload.get("attempt_count"),
                    message_redacted=payload.get("message_redacted"),
                    retryable=payload.get("retryable"),
                    expected_version=payload.get("expected_version"),
                    lease_token=payload.get("lease_token"),
                    worker_id=require_worker(x_worker_id),
                    idempotency_key=key,
                )
            else:
                decision = task_failure_store.retry(
                    job_id=job_id,
                    org_id=payload["org_id"],
                    trace_id=payload.get("trace_id", str(uuid4())),
                    error_code=payload.get("error_code", "MANUAL_RETRY"),
                    message_redacted=payload.get("message_redacted", "manual retry requested"),
                    idempotency_key=key,
                )
        except KeyError as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_RETRY_COMMAND", "message": f"missing {exc.args[0]}"}) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_RETRY_COMMAND", "message": str(exc)}) from exc
        except TaskFailureError as exc:
            raise failure_error(exc) from exc
        return success_response(decision.as_contract())

    @app.post("/internal/task-jobs/{job_id}:requeue-dead", tags=["internal"], include_in_schema=False)
    def requeue_dead_task(
        job_id: str,
        command: dict[str, Any] | None = None,
        x_worker_id: str | None = Header(default=None, alias="X-Worker-Id"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        if task_failure_store is None:
            raise HTTPException(status_code=503, detail={"code": "TASK_FAILURE_NOT_CONFIGURED"})
        require_worker(x_worker_id)
        payload = command or {}
        try:
            key = require_idempotency_key(idempotency_key)
            job = task_failure_store.requeue_dead(
                job_id=job_id,
                org_id=payload["org_id"],
                reason=payload["reason"],
                trace_id=payload.get("trace_id"),
                idempotency_key=key,
                failure_id=payload.get("failure_id"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_REQUEUE_COMMAND", "message": f"missing {exc.args[0]}"}) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_REQUEUE_COMMAND", "message": str(exc)}) from exc
        except TaskFailureError as exc:
            raise failure_error(exc) from exc
        return success_response(job.as_contract())

    @app.post("/internal/task-jobs/{job_id}:replay", tags=["internal"], include_in_schema=False)
    def replay_task(
        job_id: str,
        command: dict[str, Any] | None = None,
        x_worker_id: str | None = Header(default=None, alias="X-Worker-Id"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        if task_replay_store is None:
            raise HTTPException(status_code=503, detail={"code": "TASK_REPLAY_NOT_CONFIGURED"})
        require_worker(x_worker_id)
        payload = command or {}
        try:
            key = require_idempotency_key(idempotency_key)
            if "source_job_id" not in payload:
                raise KeyError("source_job_id")
            source_job_id = payload["source_job_id"]
            if source_job_id != job_id:
                raise TaskReplayError("REPLAY_VERSION_CONFLICT", "path job_id and source_job_id differ")
            decision = task_replay_store.replay(
                source_job_id=source_job_id,
                org_id=payload["org_id"],
                source_attempt_count=payload["source_attempt_count"],
                reason=payload["reason"],
                idempotency_key=key,
                trace_id=payload.get("trace_id", str(uuid4())),
            )
        except KeyError as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_REPLAY_COMMAND", "message": f"missing {exc.args[0]}"}) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_REPLAY_COMMAND", "message": str(exc)}) from exc
        except TaskReplayError as exc:
            raise replay_error(exc) from exc
        return success_response(decision.as_contract())

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("API_PORT", "8000")))
