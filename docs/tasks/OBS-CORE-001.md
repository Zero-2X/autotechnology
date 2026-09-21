# OBS-CORE-001 — 实现追加式 AuditLog、trace 关联、最小指标和证据包引用；查询和导出也要留下审计记录。

状态：`done`
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/audit`  
优先级：`critical` / `P0`

## 目标

实现追加式 AuditLog、trace 关联、最小指标和证据包引用；查询和导出也要留下审计记录。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-004B`
- `FOUND-005`
- `FOUND-006A`
- `FOUND-006B`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `OBS-CORE-001.implementation`
- `OBS-CORE-001.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/audit-log.schema.json`
- `packages/contracts/jsonschema/outbox-event.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_obs_core_001.py`
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

- `执行 OBS-CORE-001 的公开用例或内部命令`

Then：

- `实现追加式 AuditLog、trace 关联、最小指标和证据包引用；查询和导出也要留下审计记录。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/audit tests/integration --maxfail=1
```

Gate：`obs_core_001_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。

## 实现规格

- `AuditLogService.record` 以 `audit-log.schema.json` 生成不可变、租户隔离的 SQLite 记录；同一租户的 `Idempotency-Key` 只接受相同输入摘要，数据库触发器禁止修改和删除记录。
- `query` 和 `export` 均带 `trace_id`，分别写入 `audit.query` 与 `audit.export` 审计记录；导出包包含记录 ID、内容摘要和外部证据引用。
- 服务提供 `audit_records_total`、`audit_queries_total`、`audit_exports_total` 与失败计数，所有公开记录只通过追加操作产生。

## 补充场景

- 跨租户读取返回 `TENANT_SCOPE_VIOLATION`，不能观察其他组织的审计记录。
- 租户内重复命令返回第一次结果；复用同一幂等键但输入不同必须拒绝。
- 导出证据引用只保存受控引用字符串，不保存 Token、完整 PII 或二进制内容。

## 回滚

撤销 `20260918_found_obs_core_001` 迁移即可回到 `20260918_found_sched_001`；服务没有更新或删除审计记录的操作。

## Implementation Evidence

- `modules/audit/service.py`：持久追加式记录、trace 关联、租户隔离、查询/导出留痕、证据包摘要和最小指标。
- `tests/integration/test_audit_persistence.py`：重启后的记录与幂等返回、跨租户过滤和底层修改/删除拒绝。
- `tests/unit/audit/test_service.py`：契约校验、幂等、跨租户拒绝、查询/导出留痕与证据引用。
- `docs/foundation/OBS-CORE-001-EVIDENCE.yaml`：测试、迁移和契约验证结果。
