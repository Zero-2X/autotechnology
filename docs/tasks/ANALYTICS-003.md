# ANALYTICS-003 — 建立七类运营 KPI 与 account-free 线索归因

状态：`done`  
阶段：9（Analytics、Feedback Loop 和 Support）  
Owner：`team/analytics`  
优先级：`high` / `P1`

## 目标

从同租户、已验证的最新 Observation 版本生成不可变 KPI 快照，覆盖发布成功率、人工介入率、版权拒绝率、翻译通过率、误答率、成本和线索归因。M1 只声明 Fake、人工、站点、QA、GEO 和其他内部事实的结果。

## 明确不做

- 不抓取真实平台指标，不把 Fake/人工发布结果表述为真实发布成功率。
- 不保存个人线索、邮箱、电话、Cookie、Token 或原始评论；线索归因只使用聚合 channel/qualified/value 事实。
- 不修改 MetricDefinition 公式，不自动执行 FeedbackAction 或改变 Topic/Variant/Channel。
- 不创建 M2 的真实 `attribution_events`；本任务只保存可重建的聚合快照。

## 前置依赖

- `DIST-010`
- `ANALYTICS-002`

## 输入

- `TenantContext(org_id, actor_id, trace_id)` 和 `Idempotency-Key`
- Observation 列表、UTC 半开时间窗 `[window_start, window_end)`
- 可选 region/locale 过滤与真实平台账号证据状态
- `analytics-003.v1` 固定指标规则

## 输出

- `AnalyticsKpiSnapshot`：七类指标、输入 Observation ID/hash、数据质量问题和状态
- `analytics.kpi_snapshot.created` Outbox 事件和脱敏审计事实
- 追加式快照与幂等命令记录

## 契约与迁移

契约：

- `packages/contracts/jsonschema/observation.schema.json`
- `packages/contracts/jsonschema/analytics-kpi-snapshot.schema.json`

迁移：

- `packages/db/migrations/versions/20260920_analytics_003.py`

## 目录边界

拥有目录：

- `modules/analytics`

允许目录：

- `modules/analytics`
- `packages/contracts`
- `packages/db/migrations`
- `tests/unit`
- `tests/integration`
- `tests/contract`
- `docs/tasks`
- `docs/foundation`

禁止目录：

- `deploy/environments/prod/secrets`
- `secrets`
- `**/*.pem`
- `**/*secret*.json`
- `**/*token*.json`

## 指标规则

- 发布成功率：`publication.outcome|publication.status|publication.success`；published/succeeded/true 为分子，published/succeeded/failed/blocked/cancelled 或 bool 为分母，unknown 排除并登记质量问题。
- 人工介入率：`workflow.manual_intervention|manual.intervention|human.intervention_required` 的 true 数 / 样本数。
- 版权拒绝率：`rights.rejected|copyright.rejected|rights.decision` 的 rejected/true 数 / 样本数。
- 翻译通过率：`translation.qa_passed|translation.passed` 的 passed/true 数 / 样本数。
- 误答率：`support.answer_incorrect|answer.incorrect|support.answer_error` 的 incorrect/error/true 数 / 样本数。
- 成本：`cost.amount_cents|cost.cents|operation.cost_cents` 的非负数总和、样本数和均值。
- 线索归因：`lead.attribution|lead.attributed` 的去标识化 `{channel, attributed, qualified, value_cents}` 或 bool；输出总量、已归因、合格数、归因率、价值总额和 channel 计数。

## 权限、幂等、失败和审计

- 所有 Observation 必须属于 TenantContext；同 dedupe_key 只取最高 `observation_version`，同版本冲突快照拒绝。
- 默认只接受 account-free source；存在 `source=platform` 时必须显式提供已验证账号状态，否则返回 `EXT_ACCOUNT_UNAVAILABLE`。
- 同组织、命令和 Idempotency-Key 的同 payload 返回原快照；不同 payload 返回 `IDEMPOTENCY_KEY_REUSED`。
- 快照、输入 ID 和事件均不可覆盖；新 Observation 到达后重新计算会创建新的 snapshot ID/hash。
- 审计/Outbox 不包含输入 metric value 或线索原文，只保存窗口、状态、输入哈希和快照哈希。

## Given–When–Then

Given：

- ANALYTICS-002 已产生 schema-valid、同租户且来源可证明的 Observation。
- UTC 时间窗有效，TenantContext、trace_id 和 Idempotency-Key 可用。

When：

- 按窗口及可选 region/locale 计算 KPI 快照。

Then：

- 七个指标都返回 numerator/denominator/value 或相应成本/归因结构，零分母返回 null 并登记 `INSUFFICIENT_*`。
- 输入先按 dedupe_key 选择最新版本，再应用时间/地区/语言过滤，修订不会重复计数。
- unknown 发布结果不进入成功率分母并产生质量问题；非法语义值确定性拒绝。
- 有平台数据但无账号证据时不生成快照；纯 Fake/人工/内部数据的 `source_scope=account_free`。

补充场景：

- raw/estimated 输入可以计算，但在质量问题中显式计数；不能悄悄等同 validated。
- 未识别指标 Observation 被排除并计数；若没有任何受支持输入则拒绝。
- 线索 channel 必须是去标识化 slug，qualified 不能在 attributed=false 时为 true，价值必须非负。
- 时间窗使用 `[start,end)`，时区缺失、start>=end 或跨租户输入全部拒绝。

## 实现规格

1. `AnalyticsKpiService` 校验 Observation v1、租户和时间，按 dedupe_key 取最新版本并按窗口/region/locale 筛选。
2. 七类规则固定为 `analytics-003.v1`，比率最多保留 6 位小数；零分母返回 null，不伪造 0% 或 100%。
3. `AnalyticsKpiSnapshot` 是封闭契约，保存输入 ID/hash、指标、质量问题、状态、规则版本和自身快照哈希。
4. account-free 输入产生 `source_scope=account_free`；只有全部平台输入已通过账号证据门禁时才允许 `all_verified`。
5. `analytics_kpi_snapshots` 和 `analytics_kpi_snapshot_commands` 的 SQLite/PostgreSQL 守卫验证 JSON、哈希、输入租户和 append-only。
6. 迁移为 `20260920_analytics_002 → 20260920_analytics_003` 单头链，可降级只删除本任务表和守卫。

## 验证

```text
python -m pytest tests/unit/analytics/test_kpi_service.py tests/integration/test_analytics_003_migration.py tests/contract/test_analytics_003_contract.py -q
```

Gate：`analytics_003_acceptance`

## 外部依赖

- 无；当前验收使用 Fake/人工/站点/QA/GEO Observation。真实平台指标和真实线索质量在 `FEEDBACK-LIVE-001` 且 `EXT-ACCOUNT-001` 满足后验收。

## 回滚

停止新 KPI 快照计算，保留 Observation、MetricDefinition 和已发事件；Alembic 降级到 `20260920_analytics_002` 删除快照/命令表。回滚不删除输入 Observation，也不重标任何 source。

