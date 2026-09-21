# FEEDBACK-CORE-001 — 定义 `Observation`、`FeedbackItem`、推荐动作和评分版本 Schema；本任务只定义契约，不生成真实平台数据。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/feedback`  
优先级：`critical` / `P0`

## 目标

定义 `Observation`、`FeedbackItem`、推荐动作和评分版本 Schema；本任务只定义契约，不生成真实平台数据。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-004A`
- `FOUND-007B`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `FEEDBACK-CORE-001.implementation`
- `FEEDBACK-CORE-001.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/observation.schema.json`
- `packages/contracts/jsonschema/feedback-item.schema.json`
- `packages/contracts/jsonschema/feedback-scoring-version.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_feedback_core_001.py`
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

- `执行 FEEDBACK-CORE-001 的公开用例或内部命令`

Then：

- `定义 `Observation`、`FeedbackItem`、推荐动作和评分版本 Schema；本任务只定义契约，不生成真实平台数据。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/feedback tests/integration --maxfail=1
```

Gate：`feedback_core_001_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。

## Implementation Evidence

- Contracts: modules/feedback/core/contracts.py provides schema-backed Observation, FeedbackItem, RefreshRecommendation and FeedbackScoringVersion records.
- Schemas: packages/contracts/jsonschema/observation.schema.json, 
eedback-item.schema.json, and 
eedback-scoring-version.schema.json.
- Tests: 	ests/unit/feedback/test_contracts.py.
- Migration: packages/db/migrations/versions/20260918_feedback_core_001.py.

## 实现规格

Observation、FeedbackItem、推荐动作和 FeedbackScoringVersion 使用 JSON Schema 作为唯一契约；所有标识符带 org_id 作用域，Observation 的 metric_type 与 metric_value 必须匹配。此任务只验证和构造 account-free 合同对象，不写入真实平台数据。

## 补充场景

- 非法 UUID、未知来源、指标类型不匹配和未知字段必须拒绝。
- 同一租户的 Observation 可引用不同来源，但不得把 fake/manual 数据标记为 platform。

## 回滚

移除反馈合同适配器与迁移引用即可；保留 JSON Schema 版本和审计证据，不删除既有观察数据。
