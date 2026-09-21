# ACCOUNT-CORE-001 — 建立无凭证的 `AccountProfile`、`DistributionTarget` 和 `DistributionTargetVersion` 引用模型；用 `profile_kind=planned|synthetic` 区分规划对象和测试对象，TargetVersion 的账号连接为空，只允许 `manual_export`/`simulation`，不允许真实副作用。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/distribution_account`  
优先级：`critical` / `P0`

## 目标

建立无凭证的 `AccountProfile`、`DistributionTarget` 和 `DistributionTargetVersion` 引用模型；用 `profile_kind=planned|synthetic` 区分规划对象和测试对象，TargetVersion 的账号连接为空，只允许 `manual_export`/`simulation`，不允许真实副作用。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-005`
- `GOV-006`
- `FOUND-000`
- `FOUND-010`
- `IAM-CORE-001`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `ACCOUNT-CORE-001.implementation`
- `ACCOUNT-CORE-001.tests`
- `audit_evidence`

## 实现规格

数据对象：

- `AccountProfile(id, org_id, platform_id, profile_kind=planned|synthetic, display_name, status=planned|active|disabled)`。
- `DistributionTarget(id, org_id, account_profile_id, channel, status=planned|ready|paused)`。
- `DistributionTargetVersion(id, target_id, version_no, delivery_mode=manual_export|simulation, account_connection_id=null, policy_snapshot_ref, config_json, created_by, created_at)`。

约束：`account_connection_id` 必须为 null；`profile_kind=planned` 只能 `manual_export`，`synthetic` 可 `manual_export|simulation`；版本号按 target 从 1 递增且不可更新；`(org_id, display_name)` 和 `(target_id, version_no)` 唯一。提供 `POST /internal/account-profiles`、`POST /internal/distribution-targets/{id}/versions`、`GET` 查询接口。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/account-profile.schema.json`
- `packages/contracts/jsonschema/distribution-target.schema.json`
- `packages/contracts/jsonschema/distribution-target-version.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_account_core_001.py`
## 目录边界

拥有目录：

- `modules/distribution/account`

允许目录：

- `modules/distribution/account`
- `apps/api`
- `adapters/contract`
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

- `执行 ACCOUNT-CORE-001 的公开用例或内部命令`

Then：

- `建立无凭证的 `AccountProfile`、`DistributionTarget` 和 `DistributionTargetVersion` 引用模型；用 `profile_kind=planned|synthetic` 区分规划对象和测试对象，TargetVersion 的账号连接为空，只允许 `manual_export`/`simulation`，不允许真实副作用。`
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- 创建 planned target 并请求 `authorized_api` 时返回 `ACCOUNT_CONNECTION_REQUIRED`，不得调用平台适配器。
- synthetic target 使用 `simulation` 生成可重放 `DeliveryAttempt`，结果标记 `simulated=true`。
- 旧 TargetVersion 已被 PublicationIntent 引用时仍可读取，任何修改必须创建新版本。


## 验收证据

- `modules/distribution/account` 提供无凭证的 AccountProfile、DistributionTarget 和不可变 TargetVersion；planned 仅允许 manual_export，synthetic 允许 simulation。
- `account_connection_id` 永远为 null，跨租户目标被拒绝，版本号按 target 从 1 单调递增；API 路由不进入现有生产 OpenAPI 基线。
- 单元测试覆盖模式限制、连接为空、版本单调性和租户隔离；没有平台适配器、账号凭据或真实副作用。

## 回滚与运行说明

- 通过任务级 feature flag 关闭新命令；已提交的业务事实和审计记录不删除。
- 迁移按 expand/contract 顺序执行；验证失败时停止后续任务，保留兼容字段，不执行破坏性回滚。
- 如产生可重试任务，先暂停对应队列，再按原幂等键重放；任何外部未知结果必须转人工核查。

## 验证

```text
python -m pytest tests/unit/distribution_account tests/integration --maxfail=1
```

Gate：`account_core_001_acceptance`

## 外部依赖

- `EXT-ACCOUNT-001`

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
