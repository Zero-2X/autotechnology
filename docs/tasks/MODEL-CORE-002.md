# MODEL-CORE-002 — 实现一个可替换的 Model Gateway：供应商配置、Prompt/模型版本、调用哈希、成本、超时和重试均可记录；本阶段只允许 Fake Provider。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/model_gateway`  
优先级：`critical` / `P0`

## 目标

实现一个可替换的 Model Gateway：供应商配置、Prompt/模型版本、调用哈希、成本、超时和重试均可记录；本阶段只允许 Fake Provider。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-004B`
- `MODEL-CORE-001`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `MODEL-CORE-002.implementation`
- `MODEL-CORE-002.tests`
- `audit_evidence`

## 实现规格

`ModelGateway(id, org_id, provider, model, status=active|disabled, data_region, retention_policy, created_at)` 保存已登记的供应商配置；`ModelCall(id, org_id, model_config_id, provider, model, model_version, prompt_version, request_hash, input_hash, output_hash, status=started|succeeded|failed|timed_out|budget_exceeded, input_tokens, output_tokens, cost_cents, latency_ms, attempt_no, error_code, response_ref, created_at)` 保存每次调用事实。Gateway 仅接受注册的 Fake Provider；provider adapter 必须实现 `ModelPort`，不得在业务模块直接调用 SDK。

接口：`POST /internal/model-calls`（worker-only）和 `GET /internal/model-calls/{id}`。请求携带 `response_schema_ref`、timeout、预算和 Idempotency-Key；相同 `request_hash+model_config_id` 返回同一结果。可重试错误仅 `MODEL_TIMEOUT`、`PROVIDER_UNAVAILABLE`，最多 `max_retries`；Schema 校验、预算和权限错误不重试。事件：`model.call.started`、`model.call.succeeded`、`model.call.failed`。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/model-gateway.schema.json`
- `packages/contracts/jsonschema/model-call.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_model_core_002.py`

## 实现规格

1. `ModelGateway` 只接受显式注册的 Fake Provider，供应商配置和每次 ModelCall 均按 org_id 隔离。
2. request_hash、input/output hash、成本、耗时、attempt_no、错误码和状态都可查询；相同幂等键重放同一记录，payload 变化拒绝。
3. timeout/provider unavailable 仅按 max_retries 重试；Schema、预算、权限和未知 provider 错误不重试，并发出 started/succeeded/failed 事件。

## 验收证据

- `modules/model_gateway/service.py` 实现可替换 Gateway、Fake Provider 注册、调用记录、事件和租户范围查询。
- 单元测试覆盖 Fake 成功、幂等重放、调用哈希、provider 白名单、跨租户拒绝和事件记录；不读取真实凭据或调用外部 SDK。
- 迁移为无业务表 no-op，production provider 保持关闭。
## 目录边界

拥有目录：

- `modules/model_gateway`

允许目录：

- `modules/model_gateway`
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

- `执行 MODEL-CORE-002 的公开用例或内部命令`

Then：

- `实现一个可替换的 Model Gateway：供应商配置、Prompt/模型版本、调用哈希、成本、超时和重试均可记录；本阶段只允许 Fake Provider。`
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- 配置 provider 非 Fake 时返回 `PROVIDER_NOT_ALLOWED_IN_MVP`，不得发起外部请求。
- 达到预算上限先拒绝，再调用 provider；响应 Schema 不通过标记 failed。
- 同一幂等键不同 payload 返回 `IDEMPOTENCY_KEY_REUSED`。

回滚：禁用指定 ModelConfig feature flag；已有 ModelCall 只读，未完成调用按 timeout 收敛，不删除成本记录。

六类 GWT 必须覆盖：Fake 成功、重复 request_hash、非法 Schema/预算、权限/跨租户、provider 缺失、超时重试与未知结果。

## 验证

```text
python -m pytest tests/unit/model_gateway tests/integration --maxfail=1
```

Gate：`model_core_002_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
