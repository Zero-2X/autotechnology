# AGENT-CORE-001 — 建立 `AgentDefinition`/Registry：版本、输入/输出 Schema、工具白名单、权限、成本上限、超时和人工升级条件。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/agent`  
优先级：`critical` / `P0`

## 目标

建立 `AgentDefinition`/Registry：版本、输入/输出 Schema、工具白名单、权限、成本上限、超时和人工升级条件。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-007C`
- `MODEL-CORE-001`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `AGENT-CORE-001.implementation`
- `AGENT-CORE-001.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/agent-definition.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_agent_core_001.py`

## 实现规格

1. `AgentRegistry` 按 org_id、key、version 管理不可变 AgentDefinition；版本必须单调递增，跨租户查询返回未找到。
2. 注册时强制输入/输出 Schema 存在、工具白名单非空、权限、成本上限、超时和人工升级条件完整。
3. 执行前后分别校验 input/output Schema，拒绝未知 Schema、非法预算/超时和非递增版本；不调用外部工具或平台。

## 验收证据

- `modules/agent/registry.py` 提供版本化 Registry、租户隔离、Schema 校验和安全约束。
- 单元测试覆盖版本不可变、跨租户隔离、Schema 拒绝、未知 Schema、成本/超时约束和版本冲突。
- 迁移为无业务表 no-op，工具白名单仅记录声明，不执行工具。
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

- `执行 AGENT-CORE-001 的公开用例或内部命令`

Then：

- `建立 `AgentDefinition`/Registry：版本、输入/输出 Schema、工具白名单、权限、成本上限、超时和人工升级条件。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/agent tests/integration --maxfail=1
```

Gate：`agent_core_001_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
