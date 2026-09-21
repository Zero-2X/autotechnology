# FOUND-006B — 建立 OpenTelemetry Tracing、成本记录和统一 correlation fields。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/foundation`  
优先级：`critical` / `P0`

## 目标

建立基于 OpenTelemetry API/SDK 的本地 tracing 基线、W3C Trace Context 传播、API server span、统一 correlation 映射和追加式成本记录基类；默认仅使用内存 exporter/sink，不连接 OTLP collector、模型或平台。

## 明确不做

- 不实现 Model Gateway、Provider 调用、Prompt 管理或 `ModelCall` 持久化；这些属于 MODEL-CORE-001/002 和 AGENT-CORE-004。
- 不配置远程 OTLP endpoint、collector、Jaeger、Tempo 或供应商 APM。
- 不把请求/响应正文、Prompt、Token、凭证、URL query、org/actor 身份写入 span attribute。
- 不实现 OBS-CORE-001 的持久 AuditLog 和证据包。
- 不修改禁止目录，不调用真实平台或真实模型。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-005`
- `FOUND-006A`

## 输入

- `infra/foundation/observability.py` 的 `TenantContext` 和结构化日志。
- `infra/foundation/metrics.py` 的 API composition 边界。
- W3C `traceparent`/`tracestate` 请求头和既有 `X-Trace-Id`/`X-Request-Id` correlation headers。
- 后续模型/Agent 可提交的脱敏用量、成本和耗时数字，不接收输入/输出正文。

## 输出

- `infra/foundation/tracing.py`：TracerProvider、W3C propagation、API server span middleware 和显式 span helper。
- `infra/foundation/costs.py`：不可变 CostRecord、进程内幂等 CostRecorder 和可注入 sink。
- `apps/api/main.py`：安装 tracing middleware；响应携带当前 `traceparent`/`X-Span-Id`。
- `docs/foundation/tracing-cost-baseline-v1.yaml`。
- `packages/contracts/jsonschema/tracing-cost-baseline.schema.json`、`cost-record.schema.json`，并纳入 foundation union。
- `packages/db/migrations/versions/20260916_found_006b_tracing_cost.py`：无持久表的连续检查点。
- `tests/contract/test_found_006b_tracing_cost.py`、`tests/integration/test_found_006b_tracing_cost_integration.py`。
- `docs/foundation/FOUND-006B-EVIDENCE.yaml`。

## 实现规格

1. 依赖锁定为 `opentelemetry-api>=1.27,<2` 和 `opentelemetry-sdk>=1.27,<2`。`create_tracing_runtime(service_name, exporter)` 每次创建独立 `TracerProvider`，默认使用 `InMemorySpanExporter`，不修改全局 provider、不访问网络。
2. `OpenTelemetryMiddleware` 使用 `TraceContextTextMapPropagator` 提取父上下文并创建 `SpanKind.SERVER` span；无父上下文时创建新 trace。请求缺少 `X-Trace-Id` 时，把当前 32 位 OTel trace ID 注入 scope，供既有 `TenantContext`、响应和日志复用。
3. 响应包含当前 span 的标准 `traceparent` 和 `X-Span-Id`。span 只记录 service、HTTP method、路由模板、status code、status class 和 correlation trace/request ID；禁止 raw URL、query、headers、body、org_id、actor_id 和异常消息。
4. 非法 W3C `traceparent` 由 correlation 校验返回 `INVALID_CORRELATION_CONTEXT`；有效 parent 的 trace ID 在 server span、响应 correlation body/header 和结构化日志中一致。显式 legacy `X-Trace-Id` 保留并写为 `correlation.trace_id`，不得冒充 W3C trace ID。
5. `CostRecord` 字段为 id、org_id、trace_id、request_id、service、operation、provider、model、input_units、output_units、cost_cents、latency_ms、status、idempotency_key、occurred_at。数字必须是非负整数；status 只允许 succeeded/failed/timed_out/budget_exceeded；字符串有界且无控制字符。
6. `CostRecorder.record()` 按 `(org_id,idempotency_key)` 幂等：相同规范化字段返回同一 CostRecord；不同字段复用 key 返回 `CostIdempotencyConflictError`。sink 只接收脱敏 record，不接收 prompt、payload、token 或 response。
7. `InMemoryCostSink` 仅用于 synthetic/dev 测试；持久化由 MODEL-CORE-002/AGENT-CORE-004 的事实表负责，本任务 revision 不新增成本表。
8. tracing exporter 或 cost sink 不得让业务请求因为观测失败而产生外部副作用；默认本地组件应可确定性关闭并 flush。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/foundation.schema.json`
- `packages/contracts/jsonschema/tracing-cost-baseline.schema.json`
- `packages/contracts/jsonschema/cost-record.schema.json`
- `packages/contracts/jsonschema/correlation-context.schema.json`

迁移 revision：

- `packages/db/migrations/versions/20260916_found_006b_tracing_cost.py`

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

- trace/cost 记录只能保存允许字段；org/actor 只用于 CostRecord tenant ownership，不进入 span attributes。
- 成本写入必须携带 8～200 字符幂等键；冲突不覆盖既有事实。
- 无效 traceparent、负用量、负成本、非法状态和秘密样式字段为确定性校验错误。
- exporter/sink 默认为本地内存；无网络、数据库或真实 Provider 副作用。

## Given–When–Then

Given：

- `GOV-006、FOUND-000、FOUND-005 和 FOUND-006A 已完成`
- `API 注入独立 OpenTelemetry runtime，成本记录器使用 InMemoryCostSink`

When：

- `发送无 traceparent、有效 traceparent、非法 traceparent 和 legacy X-Trace-Id 请求`
- `创建显式 child span，并重复/冲突地记录 synthetic cost`

Then：

- `无 parent 请求生成有效 W3C trace；响应 traceparent、X-Trace-Id、body trace_id、span trace ID 和日志 trace_id 一致。`
- `有效 parent 保持同一 trace ID并生成新的 server span_id；child span 继承 trace 并正确设置 parent。`
- `非法 traceparent 返回 INVALID_CORRELATION_CONTEXT；legacy X-Trace-Id 兼容保留但与 otel.trace_id 明确分栏。`
- `span attributes 使用路由模板且不包含 raw object ID、query、org_id、actor_id、headers、payload、prompt、token 或异常消息。`
- `同一成本幂等键和同一字段返回同一 record；不同字段冲突，sink 只追加一次。`
- `负成本/用量、非法状态、空 provider/model、短幂等键确定性拒绝且无部分写入。`
- `契约、迁移、证据、专项测试和全量测试可复现。`

## 验证

```text
python -m pytest tests/contract/test_found_006b_tracing_cost.py tests/integration/test_found_006b_tracing_cost_integration.py -q
python scripts/check_task_card_precision.py --task FOUND-006B --strict
python scripts/check_migrations.py --strict --json
python -m pytest tests --maxfail=1 -q
```

Gate：`found_006b_acceptance`

## 外部依赖

- 无远程依赖；仅新增锁定的 OpenTelemetry API/SDK Python 包。

## 开工前细化

已完成：W3C 传播、span 字段白名单、correlation 映射、成本事实与幂等、观测失败边界、迁移和验收场景已冻结并实现。专项测试、全量回归、迁移、OpenAPI、任务精度和注册表检查均通过；无远程 exporter、真实模型、真实平台或持久化副作用。
