# FEEDBACK-CORE-005 — 实现 `FeedbackAction` 执行事实：批准、启动、完成、失败、取消、结果快照和幂等；默认只允许内部内容刷新/重排命令，不得绕过 Policy、审批或版本锁定。

状态：`done`  
阶段：9（Analytics、Feedback Loop 和 Support）  
Owner：`team/feedback`  
优先级：`high` / `P1`

## 目标

实现 `FeedbackAction` 执行事实：批准、启动、完成、失败、取消、结果快照和幂等；默认只允许内部内容刷新/重排命令，不得绕过 Policy、审批或版本锁定。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `WORKFLOW-CORE-002`
- `POLICY-001`
- `DIST-010`
- `FEEDBACK-CORE-004`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `FEEDBACK-CORE-005.implementation`
- `FEEDBACK-CORE-005.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/feedback-action.schema.json`

迁移：

- `packages/db/migrations/versions/20260921_feedback_core_005.py`
## 目录边界

拥有目录：

- `modules/feedback/core`

允许目录：

- `modules/feedback/core`
- `packages/contracts`
- `packages/db/migrations`
- `tests/unit`
- `tests/integration`
- `tests/contract`

禁止目录：

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

- `执行 FEEDBACK-CORE-005 的公开用例或内部命令`

Then：

- `实现 `FeedbackAction` 执行事实：批准、启动、完成、失败、取消、结果快照和幂等；默认只允许内部内容刷新/重排命令，不得绕过 Policy、审批或版本锁定。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/feedback tests/integration --maxfail=1
```

Gate：`feedback_core_005_acceptance`

## 外部依赖

- 无

## 实现规格

1. `FeedbackActionService` 记录 `proposed→approved→executing→executed|failed|cancelled` 生命周期，所有状态变化追加新版本并要求 expected version。
2. 创建和启动均要求 Policy decision 允许且 `side_effect_blocked=false`；批准必须引用 approved approval 记录；外部平台调用永远不在本任务发生。
3. 结果快照只允许有限的哈希、版本、状态、原因和阻断标记字段，禁止 Token、Secret、Cookie、PII 和原始内容。
4. 同组织同幂等键同 payload 重放；不同 payload 返回 `IDEMPOTENCY_KEY_REUSED`。审计/Outbox 明确 `side_effect_triggered=false`。

## 补充场景

- Policy 拒绝、缺少审批、目标版本非法、状态非法和乐观锁冲突不产生新版本。
- 失败动作可重新进入 executing；已执行或已取消动作不可再次执行。

## 回滚

停止新的 FeedbackAction 生命周期命令，保留 FeedbackItem 和 Recommendation；Alembic 降级到 `20260921_feedback_core_004` 删除本任务表，不删除历史建议。
