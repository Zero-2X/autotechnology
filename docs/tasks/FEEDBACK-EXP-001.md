# FEEDBACK-EXP-001 — 建立实验模型：假设、分组、指标、时间窗、样本、结论和回滚。

状态：`done`  
阶段：9（Analytics、Feedback Loop 和 Support）  
Owner：`team/feedback`  
优先级：`high` / `P1`

## 目标

建立实验模型：假设、分组、指标、时间窗、样本、结论和回滚。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `EVAL-001`
- `DIST-010`
- `ANALYTICS-003`
- `FEEDBACK-LIVE-001`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `FEEDBACK-EXP-001.implementation`
- `FEEDBACK-EXP-001.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/eval-run.schema.json`
- `packages/contracts/jsonschema/feedback-experiment.schema.json`

迁移：

- `packages/db/migrations/versions/20260921_feedback_exp_001.py`
## 目录边界

拥有目录：

- `modules/feedback/exp`

允许目录：

- `modules/feedback/exp`
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

- `执行 FEEDBACK-EXP-001 的公开用例或内部命令`

Then：

- `建立实验模型：假设、分组、指标、时间窗、样本、结论和回滚。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/feedback tests/integration --maxfail=1
```

Gate：`feedback_exp_001_acceptance`

## 外部依赖

- 无

## 实现规格

1. `ExperimentService` 保存假设、至少两个分组及 100% 分配、指标键、UTC 半开窗口和样本目标；实验状态为 planned/running/concluded/rolled_back。
2. 只接受 fake/manual/site/qa/geo/support 样本，按分组保存指标快照和 Observation ID；platform 样本在无账号阶段拒绝。
3. `start`、`conclude`、`rollback` 使用 expected version 和幂等键；结论保存 winner、摘要和 metric results，回滚保存原因。
4. 实验事实、样本、命令和审计事件追加式保存，不自动改变生产策略或执行发布。

## 补充场景

- 分组键必须唯一，分配总和必须为 100；未知分组、非法窗口、空指标和重复幂等键确定性拒绝。
- 已回滚实验不可重新启动；结论后仍可显式回滚，但不会删除样本。

## 回滚

停止新实验命令并保留历史样本/结论；Alembic 降级到 `20260921_feedback_core_005` 删除本任务表，不删除 Observation 或 Recommendation。
