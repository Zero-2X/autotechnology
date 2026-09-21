# FEEDBACK-CORE-002 — 写入 fake/manual `Observation`，生成可解释的 Refresh 或 Reprioritize 推荐；不修改生产规则。

状态：`done`  
阶段：7（Distribution 抽象、Manual Export 和 Fake Adapter）  
Owner：`team/feedback`  
优先级：`critical` / `P0`

## 目标

写入 fake/manual `Observation`，生成可解释的 Refresh 或 Reprioritize 推荐；不修改生产规则。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `FEEDBACK-CORE-001`
- `CANON-005`
- `POLICY-001`
- `DIST-010`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `FEEDBACK-CORE-002.implementation`
- `FEEDBACK-CORE-002.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/observation.schema.json`
- `packages/contracts/jsonschema/feedback-item.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_feedback_core_002.py`

## 实现规格

- `FeedbackRecommendationService.record_and_recommend` 仅接受同租户 `source=fake|manual` 的 Observation 和 active FeedbackScoringVersion；Observation、评分版本、FeedbackItem 与 RefreshRecommendation 均通过现有 JSON Schema 校验。
- 版本化阈值规则支持 `stale_days`、`freshness_score`、`refresh_required` 生成 refresh，支持 `priority_score_delta`、`opportunity_score`、`reprioritize_required` 生成 reprioritize；raw 或未触发数据只记录 Observation。
- FeedbackItem 的 `reasoning_snapshot` 固化 rule/scoring version、来源、指标值、比较方式、阈值、目标和人可读证据；estimated 数据降低置信度，所有推荐初始状态均为 `proposed`。
- Observation 按 `(org_id, dedupe_key)` 不可变去重，命令按租户、幂等键和输入哈希重放；冲突 payload、跨租户输入、platform/site 来源和 inactive 评分版本拒绝。
- 服务只输出建议与 `observation.recorded` / `feedback.recommendation_created` 事件，不创建 FeedbackAction、不执行刷新/改优先级，也不写入或修改生产规则。
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

- `执行 FEEDBACK-CORE-002 的公开用例或内部命令`

Then：

- `写入 fake/manual `Observation`，生成可解释的 Refresh 或 Reprioritize 推荐；不修改生产规则。`
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- validated manual stale 指标超过版本阈值时生成可解释 refresh；fake priority/opportunity 指标达到阈值时生成 reprioritize。
- estimated Observation 可生成较低置信度建议；raw、未知指标或未达到阈值的 Observation 只记录事实，不生成推荐。
- 相同命令和相同 Observation dedupe key 重放不重复写入；同键不同输入、跨租户 Observation/评分版本、非 fake/manual 来源和 inactive 评分版本均拒绝。
- Fake publication 可作为 Observation subject 进入反馈链路，但生成建议后 PublicationRecord、评分版本和生产规则保持不变。

回滚：

- 停用 Observation 推荐入口，保留既有 Observation、FeedbackItem、推荐、事件和审计事实；不回滚或删除任何发布事实。
- 本 revision 不创建业务表，回退执行 `python -m alembic downgrade 20260919_found_dist_011`；当前实现使用内存投影且不产生 FeedbackAction。

## 验证

```text
python -m pytest tests/unit/feedback tests/integration --maxfail=1
```

Gate：`feedback_core_002_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
