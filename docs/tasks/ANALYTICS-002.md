# ANALYTICS-002 — 持久化统一 Observation

状态：`done`  
阶段：9（Analytics、Feedback Loop 和 Support）  
Owner：`team/analytics`  
优先级：`high` / `P1`

## 目标

实现统一、追加式的 `Observation` 写入与查询边界。按既有 v1 契约使用 `source/observed_at/region/locale/observation_version/data_quality` 记录来源、时间、市场、语言、版本和可信度分级；M1 接受站点、QA、GEO、人工和 Fake 数据。

## 明确不做

- 不聚合 KPI、不执行归因、不自动生成或执行 FeedbackAction；这些属于后续 Analytics/Feedback 任务。
- 不抓取真实平台数据，不读取 Token、Cookie 或 Secret Manager 值。
- 不把 Fake、人工导入或模拟发布结果标记成 `source=platform`。
- 不覆盖或删除既有 Observation；修订必须追加下一 `observation_version`。

## 前置依赖

- `FEEDBACK-CORE-001`
- `DIST-010`
- `ANALYTICS-001`

## 输入

- `TenantContext(org_id, actor_id, trace_id)` 和 `Idempotency-Key`
- active 的租户或全局 `MetricDefinition` 精确版本
- source、subject、metric value、observed_at、region、locale、data_quality、dedupe_key、source_snapshot_ref
- 修订时的下一 `observation_version` 与 `expected_version`/`If-Match`

## 输出

- 关闭在 `observation.schema.json` 内的 Observation
- `observation.recorded` 与对应 `analytics.<category>.observed` Outbox 事件
- 追加式 Observation、幂等命令和脱敏审计证据

## 契约与迁移

契约：

- `packages/contracts/jsonschema/observation.schema.json`

迁移：

- `packages/db/migrations/versions/20260920_analytics_002.py`

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

## 权限、幂等、失败和审计

- `org_id` 由 TenantContext 注入；MetricDefinition 只能是同租户或 `org_id=null` 的全局 active 定义。
- 命令幂等范围为 `org_id + namespace + Idempotency-Key`；同键不同 payload 返回 `IDEMPOTENCY_KEY_REUSED`。
- 业务去重范围为 `org_id + dedupe_key + observation_version`；同版本同快照返回原记录，同版本不同快照拒绝。
- 修订必须严格追加下一版本并匹配 expected version；旧 Observation、事件和来源快照不改写。
- Outbox 和审计只携带 ID、版本、分类、来源、数据质量和快照哈希，不携带 metric value、原始内容或平台凭证。

## Given–When–Then

Given：

- MetricDefinition 为 active，ID、版本、key、type 与输入精确一致。
- TenantContext、trace_id、Idempotency-Key 和允许的来源证据可用。

When：

- 写入首个 Observation，重复写入，或按 expected version 追加修订。

Then：

- metric value 按 MetricDefinition 的 type 和 `quality_rules.value_schema` 离线验证。
- `site|qa|geo|manual|fake` 不依赖真实账号；`platform` 缺少账号证据时返回 `EXT_ACCOUNT_UNAVAILABLE`。
- source 与 Analytics category、subject type、来源快照一致，否则确定性拒绝。
- 同幂等请求和同业务版本不会产生重复 Observation 或重复事件。
- 跨租户定义、读取和修订被拒绝。

补充场景：

- `region` 作为市场/地区代码，`locale` 作为语言区域标签；允许全局指标为空，但非空值必须规范化。
- `data_quality=raw|validated|estimated` 是 v1 的可信度分级，禁止另存无法解释的隐式分数。
- `site|qa|geo|support|platform` 必须提供来源快照引用；Fake/人工允许为空但仍需稳定 dedupe_key。
- NaN/Infinity、过大 value、敏感字段名、非自包含 JSON value schema 和错误 enum 值全部拒绝且不写审计原文。

## 实现规格

1. `ObservationService` 解析并校验租户、MetricDefinition、source/subject/category、值类型、时间、locale/region、data_quality 和来源引用。
2. 未提供 ID 时由租户、dedupe_key 和 observation_version 确定性生成；显式 ID 必须是 UUID 且仍受同一业务去重约束。首版为 1，修订只能按 1 递增并要求乐观锁。
3. `MetricDefinition.status` 必须为 active；租户定义要求 org 相同，全局定义可被租户只读引用。
4. 每个写入原子产生 `observation.recorded` 和一个九类 Analytics observed 事件；事件 payload 不包含 metric value。
5. `observations` 和 `analytics_observation_commands` 使用 SQLite/PostgreSQL 约束验证版本顺序、定义绑定、来源证据、账号证据哈希、JSON 和 append-only。
6. 迁移为 `20260920_analytics_001 → 20260920_analytics_002` 单头链，可降级只删除本任务表与守卫。

## 验证

```text
python -m pytest tests/unit/analytics/test_observation_service.py tests/integration/test_analytics_002_migration.py tests/contract/test_analytics_002_contract.py -q
```

Gate：`analytics_002_acceptance`

## 外部依赖

- 无；只有未来真实 `source=platform` 写入需要 `EXT-ACCOUNT-001` 证据，当前 M1 验收使用站点、QA、GEO、人工和 Fake 数据。

## 回滚

先停止 Observation 写入，保留已发事件、上游 MetricDefinition 和证据引用；Alembic 降级到 `20260920_analytics_001` 删除 Observation 与命令表。回滚不得改写历史事件或把平台来源重新标记为 Fake/人工。
