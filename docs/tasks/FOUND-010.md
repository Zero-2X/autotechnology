# FOUND-010 — 定义 `Platform` 注册表、最小 `DistributionTarget`、不可变 `DistributionTargetVersion`、`PublicationIntent`、`DeliveryAttempt` Schema，以及空的 `ConnectionPort`、`PublisherPort`、`InboxPort`、`MetricsPort`；允许无连接的 `planned/synthetic` target，但要求绑定 synthetic Policy 快照，不实现平台行为。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/foundation`  
优先级：`critical` / `P0`

## 目标

定义 `Platform` 注册表、最小 `DistributionTarget`、不可变 `DistributionTargetVersion`、`PublicationIntent`、`DeliveryAttempt` Schema，以及空的 `ConnectionPort`、`PublisherPort`、`InboxPort`、`MetricsPort`；允许无连接的 `planned/synthetic` target，但要求绑定 synthetic Policy 快照，不实现平台行为。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-005`
- `GOV-006`
- `FOUND-000`
- `FOUND-007A`
- `FOUND-007B`
- `FOUND-009`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `FOUND-010.implementation`
- `FOUND-010.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/platform.schema.json`
- `packages/contracts/jsonschema/distribution-target.schema.json`
- `packages/contracts/jsonschema/distribution-target-version.schema.json`
- `packages/contracts/jsonschema/publication-intent.schema.json`
- `packages/contracts/jsonschema/delivery-attempt.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_found_010_platform_contracts.py`
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

- 由 `TenantContext` 注入 `org_id` 和 actor；跨租户访问必须拒绝。
- 写命令使用 `Idempotency-Key` 和 payload hash；状态修改使用 `If-Match` 或 expected version。
- 确定性校验失败不重试；临时失败按任务卡与策略退避；未知外部结果转人工核查。
- 记录 `trace_id`、actor、输入/输出版本、Policy 快照、拒绝原因、耗时和成本。

## Given–When–Then

Given：

- `所有前置任务已完成`
- `TenantContext、trace_id 和 Idempotency-Key 可用`

When：

- `执行 FOUND-010 的公开用例或内部命令`

Then：

- `定义 `Platform` 注册表、最小 `DistributionTarget`、不可变 `DistributionTargetVersion`、`PublicationIntent`、`DeliveryAttempt` Schema，以及空的 `ConnectionPort`、`PublisherPort`、`InboxPort`、`MetricsPort`；允许无连接的 `planned/synthetic` target，但要求绑定 synthetic Policy 快照，不实现平台行为。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/contract tests/integration --maxfail=1
```

Gate：`found_010_acceptance`

## 外部依赖

- 无

## 实现规格

- `Platform` 为冻结值对象；key/adapter_key 使用小写注册键，fake 类型必须声明 adapter_key。
- `PlatformRegistry` 在构造时拒绝重复 id/key，只提供排序查询，不发现、不加载适配器。
- `ConnectionPort`、`PublisherPort`、`InboxPort`、`MetricsPort` 仅定义 Protocol 方法形状，无实现和网络行为。
- `DistributionTarget.status` 支持 `planned`；synthetic TargetVersion 只允许 dev/staging、无连接、包含 simulation 且必须绑定 Policy 快照。
- PublicationIntent 复用统一 delivery-mode Schema；DeliveryAttempt 冻结 attempt 下界、幂等键长度和 adapter_ref 格式。
- 本任务只冻结契约与 Port；迁移 revision 可逆且不执行 DDL，持久化归后续领域任务。

## 补充场景

- 成功：合法 fake Platform 可按 id/key 查询，列表按 key 稳定排序。
- 重复：重复 Platform id 或 key 被确定性拒绝，注册表不产生部分状态。
- 非法输入：大写 key、未知 kind/status、fake 缺 adapter_key、attempt_no=0 均被拒绝。
- 权限/跨租户：Port 必须接收 TenantContext；本任务不提供绕过上下文的适配器实现。
- 依赖缺失：无账号、连接或平台 SDK 时，planned/synthetic 契约仍能离线验证。
- 未知结果：本任务不执行投递；DeliveryAttempt 的 unknown 仅为后续实现预留的契约状态。

## 回滚

移除 PlatformRegistry、Port 和 FOUND-010 测试，恢复本任务收紧的 Schema；Alembic 降级到
`20260918_found_009`。revision 不含 DDL，不会删除业务数据。

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
