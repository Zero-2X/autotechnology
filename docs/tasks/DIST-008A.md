# DIST-008A — 实现平台、Target/TargetVersion 和快照不可变约束；Target 变更必须创建新 TargetVersion，不能修改已引用快照。

状态：`done`  
阶段：7（Distribution 抽象、Manual Export 和 Fake Adapter）  
Owner：`team/distribution`  
优先级：`critical` / `P0`

## 目标

实现平台、Target/TargetVersion 和快照不可变约束；Target 变更必须创建新 TargetVersion，不能修改已引用快照。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `FOUND-004A`
- `POLICY-001`
- `DIST-001`
- `DIST-007`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `DIST-008A.implementation`
- `DIST-008A.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/distribution-target-version.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_dist_008a.py`

## 实现规格

- `DistributionService` 将 Target 的平台、市场、语言、渠道和环境作为不可变身份字段；`TargetVersion` 创建时必须与 Target 快照一致，Target 退役后不得再创建版本。
- `update_target` 明确拒绝原地修改并要求通过新的 TargetVersion/Target 快照表达变更；读接口返回深拷贝，调用方不能通过返回对象改写内部事实。
- `activate_target_version` 和 `retire_target_version` 使用 `expected_etag` 作为 If-Match 保护，只修改 lifecycle 状态/etag/retired_at，不改写 snapshot_hash、能力、账号、Policy 或交付模式快照。
- `retire_target` 记录带原因的 Target 退役事件；TargetVersion 退役必须提供同一 Target 的 replacement version，或先退役 Target；跨租户访问、错误 ETag、非法状态和替代版本均拒绝。
- 版本创建、激活、退役均按 tenant/idempotency/payload hash 记录审计和 EventEnvelope，并通过 DistributionTarget/TargetVersion Schema 校验。
## 目录边界

拥有目录：

- `modules/distribution`

允许目录：

- `modules/distribution`
- `adapters/contract`
- `adapters/manual`
- `adapters/fake`
- `tests/replay`
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

- `执行 DIST-008A 的公开用例或内部命令`

Then：

- `实现平台、Target/TargetVersion 和快照不可变约束；Target 变更必须创建新 TargetVersion，不能修改已引用快照。`
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- 修改返回的 Target/TargetVersion 副本不得影响服务内存快照；原地 update 返回 `TARGET_IMMUTABLE`。
- TargetVersion 平台/市场/locale/channel/environment 与 Target 不一致、Target 已退役、跨租户读取或 ETag 不匹配均在写入前拒绝。
- draft→active 必须有 Policy snapshot；active 版本退役需要 replacement version 或已退役 Target，且 snapshot_hash 保持不变。
- 同一幂等键重放返回同一版本/退役结果，不重复创建版本或事件；生命周期命令不会调用平台 API。

回滚：

- 停止 Target 激活/退役命令，保留现有 Target、TargetVersion、快照哈希、事件和审计事实。
- 本 revision 不创建业务表，生命周期投影使用内存服务；若需回退迁移，执行 `python -m alembic downgrade 20260919_found_dist_007`。

## 验证

```text
python -m pytest tests/unit/distribution tests/integration --maxfail=1
```

Gate：`dist_008a_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
