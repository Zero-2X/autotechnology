# FEEDBACK-CORE-003 — 建立 `FeedbackItem`：观察、问题、影响、建议动作、负责人、截止时间和状态；支持 synthetic/manual Observation。

状态：`done`  
阶段：9（Analytics、Feedback Loop 和 Support）  
Owner：`team/feedback`  
优先级：`high` / `P1`

## 目标

建立 `FeedbackItem`：观察、问题、影响、建议动作、负责人、截止时间和状态；支持 synthetic/manual Observation。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `FEEDBACK-CORE-001`
- `DIST-010`
- `FEEDBACK-CORE-002`
- `ANALYTICS-002`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `FEEDBACK-CORE-003.implementation`
- `FEEDBACK-CORE-003.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/feedback-item.schema.json`

迁移：

- `packages/db/migrations/versions/20260921_feedback_core_003.py`
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

- `执行 FEEDBACK-CORE-003 的公开用例或内部命令`

Then：

- `建立 `FeedbackItem`：观察、问题、影响、建议动作、负责人、截止时间和状态；支持 synthetic/manual Observation。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/feedback tests/integration --maxfail=1
```

Gate：`feedback_core_003_acceptance`

## 外部依赖

- 无

## 实现规格

1. `FeedbackItemService` 接受同租户 Observation ID，并在提供 Observation 记录时校验 schema、租户和 account-free source。
2. 创建结果保存观察、问题、影响、建议动作、负责人、截止时间、过期时间、优先级、置信度、推理快照和 `proposed` 状态；`FeedbackItem` 事实按版本追加。
3. 状态只允许 `proposed→approved|rejected|expired`、`approved→executed|expired`；转换需要 expected version，并为批准记录 approver。
4. 同组织同幂等键同 payload 重放，payload 变化返回 `IDEMPOTENCY_KEY_REUSED`；跨租户访问返回 `TENANT_SCOPE_VIOLATION`。
5. 审计和 Outbox 只保存 ID、状态、版本和哈希，不保存原始 Observation metric value。

## 补充场景

- Observation ID 必须非空且唯一；缺少引用、重复引用、非法状态转换和乐观锁冲突均不写入新版本。
- `platform` Observation 在无账号证据的 M1 阶段拒绝；fake/manual/site/qa/geo/support Observation 可用于 synthetic/manual 反馈。

## 回滚

停止新 FeedbackItem 命令，保留历史 Observation 和已产生的审计事件；Alembic 降级到 `20260921_analytics_004` 删除本任务表，不删除 Observation。
