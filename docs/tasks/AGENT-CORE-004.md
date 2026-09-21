# AGENT-CORE-004 — 持久化 `AgentRun`/`ModelCall`：记录模型、Prompt、输入/输出哈希、成本、脱敏状态、重试和评审人。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/agent`  
优先级：`critical` / `P0`

## 目标

持久化 `AgentRun`/`ModelCall`：记录模型、Prompt、输入/输出哈希、成本、脱敏状态、重试和评审人。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-004A`
- `AGENT-CORE-002`
- `AGENT-CORE-003`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `AGENT-CORE-004.implementation`
- `AGENT-CORE-004.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/agent-run.schema.json`
- `packages/contracts/jsonschema/model-call.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_agent_core_004.py`

## 实现规格

1. `AgentRunLedger` 追加记录 AgentRun/ModelCall 的 org_id、版本、prompt/input/output hash、成本、耗时、状态、attempt_no、错误码与 reviewer。
2. 记录只保留哈希和脱敏元数据，不保存原始 prompt 或 token；读取必须按 org_id 隔离。
3. 失败、超时、重试和人工评审状态可复现，记录结构不可变；本阶段不创建生产表或连接外部服务。

## 验收证据

- `modules/agent/ledger.py` 提供 append-only AgentRun/ModelCall ledger、哈希和租户范围查询。
- 单元测试覆盖原始 prompt 不落盘、哈希、成本/耗时/重试/错误码和跨租户拒绝。
- 迁移为无业务表 no-op。
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

- `执行 AGENT-CORE-004 的公开用例或内部命令`

Then：

- `持久化 `AgentRun`/`ModelCall`：记录模型、Prompt、输入/输出哈希、成本、脱敏状态、重试和评审人。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/agent tests/integration --maxfail=1
```

Gate：`agent_core_004_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
