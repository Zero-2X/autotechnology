# OBS-CORE-002 — 实现数据库/对象存储备份、恢复命令和恢复后队列暂停；用 synthetic 数据验证 RPO/RTO。

状态：`done`
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/audit`  
优先级：`critical` / `P0`

## 目标

实现数据库/对象存储备份、恢复命令和恢复后队列暂停；用 synthetic 数据验证 RPO/RTO。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-003A`
- `FOUND-003B`
- `FOUND-004A`
- `OBS-CORE-001`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `OBS-CORE-002.implementation`
- `OBS-CORE-002.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/deletion-request.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_obs_core_002.py`
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

- `执行 OBS-CORE-002 的公开用例或内部命令`

Then：

- `实现数据库/对象存储备份、恢复命令和恢复后队列暂停；用 synthetic 数据验证 RPO/RTO。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/audit tests/integration --maxfail=1
```

Gate：`obs_core_002_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。

## 实现规格

- `LocalRecoveryDrill.backup` 将 synthetic SQLite 数据库镜像与私有对象写入校验摘要的本地备份；同一租户幂等键只接受相同 payload。
- `restore` 计算 RPO/RTO 与缺失事件数，恢复完成前暂停指定队列；只有达到恢复目标时 `release_queues` 才能放行队列。
- 所有快照、恢复和队列放行命令都带租户、trace 和审计记录，可由 `AuditLogService` 注入验证。

## 补充场景

- 跨租户快照或恢复访问返回 `TENANT_SCOPE_VIOLATION`。
- 恢复时间线不合法、幂等键复用或 RPO/RTO 未达标时拒绝放行队列并保留暂停状态。
- 备份引用只指向 synthetic URI，不读取真实数据库、对象存储或凭证。

## 回滚

撤销 `20260918_found_obs_core_002` 迁移即可回到 `20260918_found_obs_core_001`；恢复演练状态只存在于服务实例内，队列放行需重新通过目标校验。

## Implementation Evidence

- `modules/audit/recovery.py` 与 `modules/audit/infrastructure/local_recovery.py`：synthetic 备份、镜像校验与恢复、队列暂停/放行和 RPO/RTO 测量。
- `tests/integration/test_local_recovery_drill.py`：数据库和对象恢复、损坏备份拒绝、暂停时 Worker 不领取任务。
- `tests/unit/audit/test_recovery.py`：幂等、租户隔离、恢复指标、队列安全闸和审计事件。
- `docs/foundation/OBS-CORE-002-EVIDENCE.yaml`：测试、迁移和恢复验证结果。
