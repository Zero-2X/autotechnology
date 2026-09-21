# AGENT-CORE-002 — 实现 `AgentRunner`：只依赖 `ModelPort`，校验结构化输出，拒绝越权工具调用和不符合 Schema 的结果。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/agent`  
优先级：`critical` / `P0`

## 目标

实现 `AgentRunner`：只依赖 `ModelPort`，校验结构化输出，拒绝越权工具调用和不符合 Schema 的结果。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `MODEL-CORE-002`
- `AGENT-CORE-001`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `AGENT-CORE-002.implementation`
- `AGENT-CORE-002.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/agent-run.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_agent_core_002.py`

## 实现规格

1. `AgentRunner` 只依赖 `ModelPort`，执行前校验 AgentDefinition 输入 Schema 与工具白名单，执行后校验输出 Schema。
2. 越权工具调用、跨租户定义、结构化输出失败分别以稳定错误码拒绝；ModelPort 错误记录为失败，不触发隐式工具执行。
3. 每次运行保存 input/output hash、状态、错误码和完成事件；低置信度或显式 needs_review 输出进入人工复核状态。

## 验收证据

- `modules/agent/runner.py` 实现 AgentRunner、AgentRun 和完成/失败事件，依赖接口而非供应商 SDK。
- 单元测试覆盖成功、输出 Schema 拒绝、越权工具、跨租户和人工复核边界。
- 迁移为无业务表 no-op，无真实工具、平台或凭据调用。
## 目录边界

拥有目录：

- `modules/agent`

允许目录：

- `modules/agent`
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

- `执行 AGENT-CORE-002 的公开用例或内部命令`

Then：

- `实现 `AgentRunner`：只依赖 `ModelPort`，校验结构化输出，拒绝越权工具调用和不符合 Schema 的结果。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/agent tests/integration --maxfail=1
```

Gate：`agent_core_002_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
