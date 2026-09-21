# POLICY-002 — 实现政策卡过期和复核检查；`review_due_at` 到期后自动切换为人工模式并阻止新的副作用任务。

状态：`done`  
阶段：4（Production、Localization、QA、Policy 和 Approval）  
Owner：`team/policy`  
优先级：`critical` / `P0`

## 目标

实现政策卡过期和复核检查；`review_due_at` 到期后自动切换为人工模式并阻止新的副作用任务。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-005`
- `CANON-002`
- `POLICY-001`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `POLICY-002.implementation`
- `POLICY-002.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/policy-snapshot.schema.json`
- `packages/contracts/jsonschema/policy-decision.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_policy_002.py`

## 实现规格

- `PolicyExpiryService.check_snapshot` 只读取同租户或全局 `PolicySnapshot`，按 `effective_at`、`expires_at`、`review_due_at` 和 `status` 生成符合 `policy-decision.schema.json` 的生命周期决策，不修改 Snapshot 或其他业务事实。
- Snapshot 在 `review_due_at` 到期且尚未过期时，所有副作用相关 policy 切换为 `manual_review`，记录 `POLICY_SNAPSHOT_REVIEW_DUE`，创建租户范围的 `HumanTask(policy_review)` 投影并将 `side_effect_blocked=true` 写入审计；不得自动续期、自动放行或自动修改 Snapshot。
- Snapshot 过期、撤回或尚未生效时，生命周期决策为 `deny`，记录稳定原因并阻止新的副作用任务；当前 active 且未到复核时间时返回 `allow`，供 POLICY-001 的事实 Gate 继续聚合。
- 检查执行 Schema、租户和 subject 校验；同租户同幂等键重放原决策和同一 HumanTask，输入不同返回 `IDEMPOTENCY_KEY_REUSED`，审计记录 actor、trace、输入/输出哈希和阻断原因。

补充场景：

- Given active Snapshot 且当前时间早于 review_due_at，When 检查，Then 返回 `allow` 且不创建 HumanTask。
- Given review_due_at 已到但 expires_at 尚未到，When 检查，Then 返回 `manual_review`、阻断副作用并创建 `policy_review` HumanTask。
- Given expires_at 已到、status 为 expired/revoked 或 Snapshot 尚未生效，When 检查，Then 返回 `deny`，不创建重复 HumanTask。
- Given 其他租户 Snapshot，When 检查，Then 返回 `TENANT_SCOPE_VIOLATION`，不泄漏 Snapshot 内容。

## 回滚

- 停止新的生命周期检查并保留已创建 HumanTask 和决策审计；不回写或删除历史 Snapshot。
- 迁移为无业务表修订，后续 HumanTask/Decision 持久化使用追加兼容迁移。
## 目录边界

拥有目录：

- `modules/policy`

允许目录：

- `modules/policy`
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

- `执行 POLICY-002 的公开用例或内部命令`

Then：

- `实现政策卡过期和复核检查；`review_due_at` 到期后自动切换为人工模式并阻止新的副作用任务。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/policy tests/integration --maxfail=1
```

Gate：`policy_002_acceptance`

## 外部依赖

- 无

## 开工前细化

已按 Snapshot 生命周期、人工任务投影、副作用阻断、幂等和租户失败路径细化并完成实现；状态为 `done`。
