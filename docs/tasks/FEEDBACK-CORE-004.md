# FEEDBACK-CORE-004 — 把反馈回写 TopicOpportunity 评分、Refresh Queue、Variant/Channel 策略和 Prompt Eval，但只生成 Recommendation。

状态：`done`  
阶段：9（Analytics、Feedback Loop 和 Support）  
Owner：`team/feedback`  
优先级：`high` / `P1`

## 目标

把反馈回写 TopicOpportunity 评分、Refresh Queue、Variant/Channel 策略和 Prompt Eval，但只生成 Recommendation。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `TOPIC-007`
- `CANON-005`
- `PROD-002`
- `EVAL-001`
- `DIST-010`
- `FEEDBACK-CORE-003`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `FEEDBACK-CORE-004.implementation`
- `FEEDBACK-CORE-004.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/feedback-item.schema.json`
- `packages/contracts/jsonschema/feedback-recommendation.schema.json`

迁移：

- `packages/db/migrations/versions/20260921_feedback_core_004.py`
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

- `执行 FEEDBACK-CORE-004 的公开用例或内部命令`

Then：

- `把反馈回写 TopicOpportunity 评分、Refresh Queue、Variant/Channel 策略和 Prompt Eval，但只生成 Recommendation。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/feedback tests/integration --maxfail=1
```

Gate：`feedback_core_004_acceptance`

## 外部依赖

- 无

## 实现规格

1. `FeedbackRecommendationServiceV2` 将 proposed/approved FeedbackItem 映射为 TopicOpportunity、Refresh Queue、Variant、Channel 或 Prompt Eval recommendation。
2. 每条 recommendation 保存目标类型/ID、置信度、规则版本和证据哈希，状态固定为 `proposed`；不得直接修改 Topic、Variant、Channel、Prompt 或执行 FeedbackAction。
3. 命令经过 TenantContext 与 idempotency key 校验；同 payload 重放，不同 payload 返回 `IDEMPOTENCY_KEY_REUSED`。
4. 审计和 Outbox 只携带 recommendation 元数据和推理哈希，不携带原始观察值或个人信息。

## 补充场景

- 已执行/拒绝/过期的 FeedbackItem 不得生成新的 recommendation。
- 未显式指定目标时按 recommendation_type 使用固定映射；目标 ID 必须是 UUID。

## 回滚

停止 recommendation 生成，保留 FeedbackItem 和 Observation；Alembic 降级到 `20260921_feedback_core_003` 删除本任务投影和命令表。
