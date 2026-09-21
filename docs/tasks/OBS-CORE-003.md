# OBS-CORE-003 — 实现删除传播任务：关系库、对象、向量、缓存和导出包逐项确认，失败进入人工队列。

状态：`done`
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/audit`  
优先级：`critical` / `P0`

## 目标

实现删除传播任务：关系库、对象、向量、缓存和导出包逐项确认，失败进入人工队列。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `WORKFLOW-CORE-002`
- `OBS-CORE-002`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `OBS-CORE-003.implementation`
- `OBS-CORE-003.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/deletion-request.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_obs_core_003.py`
## 目录边界

拥有目录：

- `modules/audit`

允许目录：

- `modules/audit`
- `packages/observability`
- `infra/scripts`
- `tests/security`
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

- `执行 OBS-CORE-003 的公开用例或内部命令`

Then：

- `实现删除传播任务：关系库、对象、向量、缓存和导出包逐项确认，失败进入人工队列。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/audit tests/integration --maxfail=1
```

Gate：`obs_core_003_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。

## 实现规格

- `DeletionPropagationService.request` 创建符合 `deletion-request.schema.json` 的租户级请求，并为关系库、对象、向量、缓存和导出包建立待确认阶段。
- `propagate` 经每个目标 Port 执行删除并检查目标不存在后记录证据引用；请求、阶段、人工任务和命令写入可重启的 SQLite 存储。
- `resolve_manual_task` 以 expected version 重试失败阶段；全部阶段完成后请求才进入 `completed`，否则保留 `failed` 或 `partially_completed`。

## 补充场景

- 跨租户读取、阶段确认或人工复核必须返回 `TENANT_SCOPE_VIOLATION`。
- 同一幂等键的输入摘要改变时拒绝；已完成阶段不可重复确认，版本冲突不能推进传播。
- 错误信息只保留短文本并清理 Token、Secret、Password 等敏感值；实现不访问真实存储或平台。

## 回滚

撤销 `20260918_found_obs_core_003` 迁移即可回到 `20260918_found_obs_core_002`；人工队列和阶段确认没有外部副作用。

## Implementation Evidence

- `modules/audit/deletion.py`：删除请求、五阶段确认、可重启的人工复核队列、幂等和租户隔离。
- `tests/integration/test_deletion_persistence.py`：失败任务与人工复核在重启后保持一致。
- `tests/unit/audit/test_deletion.py`：全阶段成功、失败入队、脱敏、版本与跨租户校验。
- `docs/foundation/OBS-CORE-003-EVIDENCE.yaml`：测试、迁移和契约验证结果。
