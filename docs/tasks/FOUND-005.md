# FOUND-005 — 建立统一 API 错误、`trace_id/request_id/org_id/actor_id` 和结构化日志。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/foundation`  
优先级：`critical` / `P0`

## 目标

建立统一 API 错误、`trace_id/request_id/org_id/actor_id` 和结构化日志。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-001`
- `FOUND-004E`

## 输入

- `TenantContext`：`trace_id`、`request_id`、`org_id`、`actor_id`；缺失的 trace/request ID 由 API 入口生成，租户和 actor 只接受安全的非空值。
- HTTP headers：`X-Trace-Id`、`X-Request-Id`、`X-Org-Id`、`X-Actor-Id`；响应回传同名 correlation headers。
- `HTTPException`、请求校验异常和未处理异常；不得把异常堆栈、token 或凭证写入客户端响应或结构化日志。

## 输出

- `infra/foundation/observability.py`：`TenantContext`、统一 `ApiError`、correlation context、JSON structured logger 和脱敏辅助函数。
- `apps/api/main.py`：安装 correlation middleware 和统一 HTTP/validation/unknown exception handlers；成功响应及错误响应携带统一 correlation fields。
- `packages/contracts/jsonschema/api-error.schema.json`、`correlation-context.schema.json`、`structured-log.schema.json`，并由 `foundation.schema.json` 汇总引用。
- `packages/db/migrations/versions/20260916_found_004f_api_observability.py`：FOUND-005 的连续兼容检查点，只记录运行时契约，不新增业务表或读取外部服务。
- `tests/contract/test_found_005_observability.py`、`tests/integration/test_found_005_observability_integration.py`。
- `docs/foundation/FOUND-005-EVIDENCE.yaml`：验证、脱敏和无外部副作用证据。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/foundation.schema.json`
- `packages/contracts/jsonschema/api-error.schema.json`
- `packages/contracts/jsonschema/correlation-context.schema.json`
- `packages/contracts/jsonschema/structured-log.schema.json`

迁移：

- `packages/db/migrations/versions/20260916_found_004f_api_observability.py`
## 目录边界

拥有目录：

- `infra/foundation`

允许目录：

- `infra/foundation`
- `apps`
- `packages`
- `infra`
- `deploy/environments/dev`
- `deploy/environments/staging`
- `scripts`
- `docs`
- `packages/contracts`
- `packages/db/migrations`
- `tests/unit`
- `tests/integration`
- `tests/contract`

禁止目录：

- `adapters/platforms`
- `deploy/environments/prod`
- `deploy/environments/prod/secrets`
- `secrets`
- `**/*.pem`
- `**/*secret*.json`
- `**/*token*.json`

## 权限、幂等、失败和审计

- 由 `TenantContext` 注入 `org_id` 和 actor；跨租户访问必须拒绝。
- 写命令使用 `Idempotency-Key` 和 payload hash；状态修改使用 `If-Match` 或 expected version。
- 确定性校验失败不重试；临时失败按任务卡与策略退避；未知外部结果转人工核查。
- 记录 `trace_id`、actor、输入/输出版本、Policy 快照、拒绝原因、耗时和成本。

## Given–When–Then

Given：

- `所有前置任务已完成`
- `TenantContext、trace_id 和 Idempotency-Key 可用`

When：

- `执行 FOUND-005 的公开用例或内部命令`

Then：

- 所有 API 响应均回传 `X-Trace-Id`、`X-Request-Id`，存在时回传 `X-Org-Id`、`X-Actor-Id`；响应体中的 `trace_id/request_id/org_id/actor_id` 与请求上下文一致。
- HTTP、请求校验和未知异常统一为 `detail={code,message,details,trace_id,request_id,org_id,actor_id,retryable}`，未知异常只暴露 `INTERNAL_ERROR`。
- 结构化日志每条输出 JSON，至少包含 `event,timestamp,level,service,trace_id,request_id,org_id,actor_id,method,path,status_code,duration_ms`；敏感 header、body、异常堆栈不写入日志。
- `TenantContext` 使用 request-scoped contextvar，处理完成后清理，不会串请求或串租户。
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- Given 请求没有 trace/request header，When 调用 `/health/live`，Then API 生成 UUID correlation ID 并在响应 header、body 和日志中使用同一值。
- Given 请求带有 `X-Trace-Id/X-Request-Id/X-Org-Id/X-Actor-Id`，When 调用任一路由，Then 不覆盖安全值，响应和日志保持一致。
- Given 路由抛出已有 domain `HTTPException`，When 返回错误，Then 保留稳定业务 `code`，补齐 correlation fields 和 `retryable`，不泄露内部异常。
- Given 请求体校验失败或路由抛出未知异常，When API 返回，Then 分别使用 `REQUEST_VALIDATION_ERROR` 或 `INTERNAL_ERROR`，未知异常消息固定且日志含 `error_type` 而不含堆栈/秘密值。
- Given 两个并发请求使用不同租户，When 同时完成，Then 结构化日志和 `request.state.tenant_context` 不互串。
- Given API 未配置数据库或外部服务，When 请求健康/内部命令，Then correlation 层不发起网络探测，不改变既有 `not_configured` 语义。

## 外部依赖

- 无

## 实现规格

1. `TenantContext` 为不可变 dataclass；从 headers 读取安全 correlation 值，缺失的 `trace_id/request_id` 用 UUID 生成，空值、控制字符和超长值返回 `INVALID_CORRELATION_CONTEXT`。
2. `CorrelationMiddleware` 在请求开始设置 contextvar 和 `request.state.tenant_context`，在响应结束前写入 correlation headers，并在 `finally` 中 reset contextvar。
3. `ApiError` 统一包含 `code`、脱敏 `message`、`details`、`trace_id`、`request_id`、`org_id`、`actor_id` 和 `retryable`；HTTP 状态到 retryable 的映射固定为 408/429/5xx 可重试，其余不可重试。
4. 异常 handlers 覆盖 `HTTPException`、`RequestValidationError` 和通用 `Exception`。已有 `detail.code` 必须保留；未知异常日志记录类型和 request correlation，客户端不返回原始异常文本。
5. `structured_log()` 只接受白名单 correlation/request 字段，统一输出 UTC ISO-8601 JSON；任何字段值先执行控制字符和 secret/token/password/authorization 脱敏。
6. 本任务不创建 audit 事实表、不调用 PostgreSQL/Redis/S3/平台 API；迁移仅作为可回退的契约检查点。

## 验证

```text
python -m pytest tests/contract/test_found_005_observability.py tests/integration/test_found_005_observability_integration.py -q
python scripts/check_migrations.py --strict --json
python scripts/check_task_card_precision.py --task FOUND-005 --strict
```

Gate：`found_005_acceptance`

## 回滚与运行说明

- 删除新 middleware/handlers 的装配即可恢复既有路由；不删除业务事实或日志文件。
- 迁移可回退到 `20260916_found_004e`，其 upgrade/downgrade 均为 no-op，不修改既有表。
- 发现日志含敏感字段时暂停日志 sink、修正脱敏白名单并重跑 synthetic 测试；不得读取或轮换真实凭证。

## 实施证据

- 已实现 [observability.py](../../infra/foundation/observability.py)：不可变 `TenantContext`、request-scoped contextvar、统一 `ApiError`、JSON 脱敏日志和纯 ASGI correlation middleware。
- 已在 [apps/api/main.py](../../apps/api/main.py) 安装 middleware/异常 handlers，并让健康检查及既有内部命令返回统一 correlation fields；旧 `detail.code` 兼容保留。
- 已创建 `api-error`、`correlation-context`、`structured-log` JSON Schema，并纳入 `foundation.schema.json`；未新增业务事实表。
- 已创建 `20260916_found_004f` 兼容 no-op migration，保留既有 `004*` head 断言和可回退路径。
- 已完成 contract/integration 测试：6 passed；全量 `python -m pytest tests --maxfail=1 -q`：102 passed, 8 warnings。
- 已完成 migration、inventory、task precision、registry refs、OpenAPI 和 plan consistency 检查；剩余 OpenAPI/catalog 仅为既有基线差异警告。

## 开工前细化

本卡已完成从 `planned` 到 `in_progress` 再到 `done` 的状态闭环；后续观测、IAM 和业务模块必须复用本任务的 correlation/error 契约。
