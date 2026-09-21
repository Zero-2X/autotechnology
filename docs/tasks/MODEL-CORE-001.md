# MODEL-CORE-001 — 定义 `ModelPort`、供应商错误结构、脱敏入口、超时、预算和 Fake Model Provider。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/model_gateway`  
优先级：`critical` / `P0`

## 目标

定义 `ModelPort`、供应商错误结构、脱敏入口、超时、预算和 Fake Model Provider。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-007C`
- `FOUND-009`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `MODEL-CORE-001.implementation`
- `MODEL-CORE-001.tests`
- `audit_evidence`

## 实现规格

`ModelPort.generate(request)` 请求字段：`model_id`、`prompt_version`、`input`、`response_schema_ref`、`timeout_ms`、`budget_cents`、`trace_id`。响应字段：`output`、`provider`、`model_version`、`usage{input_tokens,output_tokens}`、`cost_cents`、`latency_ms`、`finish_reason`、`request_hash`。Fake Provider 必须支持 deterministic fixture、timeout 和 quota exceeded 三种结果；生产密钥只从 secret provider 读取，日志中不得出现 prompt 原文或 token。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/model-gateway.schema.json`
- `packages/contracts/jsonschema/model-call.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_model_core_001.py`
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

- `执行 MODEL-CORE-001 的公开用例或内部命令`

Then：

- `定义 `ModelPort`、供应商错误结构、脱敏入口、超时、预算和 Fake Model Provider。`
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- 响应无法通过 `response_schema_ref` 校验返回 `MODEL_OUTPUT_SCHEMA_INVALID`，不自动发布。
- 超时按 deadline 返回 `MODEL_TIMEOUT`；预算不足返回 `MODEL_BUDGET_EXCEEDED` 且不调用 provider。
- 相同 `request_hash` 在幂等窗口内返回同一 fixture 结果，并记录 `model.call` 审计事件。


## 验收证据

- `modules/model_gateway` 提供 `ModelPort`、结构化 `ModelError`、`ModelRequest/Response` 和无网络无凭证的 `FakeModelProvider`。
- Fake provider 在调用前执行 timeout/budget 拒绝，按 request_hash 返回确定性 fixture，并对 response_schema_ref 做校验；错误不会自动重试或记录 prompt 原文。
- 单元测试覆盖确定性、超时、预算、Schema 拒绝和输入脱敏；迁移为无业务表 no-op。

## 回滚与运行说明

- 通过任务级 feature flag 关闭新命令；已提交的业务事实和审计记录不删除。
- 迁移按 expand/contract 顺序执行；验证失败时停止后续任务，保留兼容字段，不执行破坏性回滚。
- 如产生可重试任务，先暂停对应队列，再按原幂等键重放；任何外部未知结果必须转人工核查。

## 验证

```text
python -m pytest tests/unit/model_gateway tests/integration --maxfail=1
```

Gate：`model_core_001_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
