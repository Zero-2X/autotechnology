# ANALYTICS-001 — 定义内容、资产、发布、互动、GEO、客服、QA、成本和风险规范事件

状态：`done`  
阶段：9（Analytics、Feedback Loop 和 Support）  
Owner：`team/analytics`  
优先级：`high` / `P1`

## 目标

建立九类规范 Analytics 事件目录，并实现租户级或全局的版本化 `MetricDefinition`。后续 Observation 写入只接受目录内事件和已激活指标定义；M1 可以使用站点、QA、GEO、人工和 Fake 数据。

## 明确不做

- 不持久化 Observation、计算聚合指标或执行归因；这些属于 `ANALYTICS-002`/`ANALYTICS-003`。
- 不调用真实平台、OAuth 或账号接口。
- 不把 Fake、人工或模拟数据标记为真实平台数据。
- 不在事件 payload 中保存 raw token、Secret Manager 值、原始内容或未脱敏 PII。

## 前置依赖

- `FOUND-007B`
- `DIST-010`

## 输入

- `TenantContext(org_id, actor_id, trace_id)`
- `Idempotency-Key`，版本追加和状态转换使用 `expected_version`/`If-Match`
- 指标键、类型、单位、公式、维度、窗口、数据源、去重规则、质量规则和 owner
- 需要校验的规范 Analytics 事件信封

## 输出

- 九类事件目录 `docs/contracts/analytics-event-catalog-v1.yaml`
- `MetricDefinitionService` 的创建、查询、激活、替代版本和退役结果
- `metric.definition.created|activated|retired` 审计与 Outbox 事件
- `ANALYTICS-001` 测试和证据

## 契约与迁移

契约：

- `packages/contracts/jsonschema/metric-definition.schema.json`
- `packages/contracts/jsonschema/analytics-event-catalog.schema.json`

迁移：

- `packages/db/migrations/versions/20260920_analytics_001.py`

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
- `docs/contracts`
- `docs/tasks`
- `docs/foundation`

禁止目录：

- `deploy/environments/prod/secrets`
- `secrets`
- `**/*.pem`
- `**/*secret*.json`
- `**/*token*.json`

## 权限、幂等、失败和审计

- 普通创建由 `TenantContext` 注入 `org_id`；调用方给出的其他租户 ID 返回 `TENANT_SCOPE_VIOLATION`。
- 全局目录的 `org_id=null` 仅能经显式 global catalog 权限入口创建；租户可只读使用全局定义。
- 幂等范围为 `scope + command namespace + Idempotency-Key`；同键不同 payload 返回 `IDEMPOTENCY_KEY_REUSED`。
- 第二个及后续版本必须严格递增并校验当前 `version_no`；状态命令必须提供 `expected_version` 或 `If-Match`。
- 审计和 Outbox 只保存定义 ID、版本、scope、快照哈希和转换，不保存指标样本或敏感原文。

## Given–When–Then

Given：

- `FOUND-007B` 事件信封/兼容性基线和 `DIST-010` 内部发布事实已完成。
- TenantContext、trace_id 和 Idempotency-Key 可用。

When：

- 创建、激活、增加版本或退役 MetricDefinition。
- 校验 `analytics.<category>.observed` 事件。

Then：

- 目录恰好覆盖 `content|asset|publication|interaction|geo|support|qa|cost|risk` 九类事件。
- Fake/人工来源无需真实账号；`source=platform` 且没有外部账号证据时返回 `EXT_ACCOUNT_UNAVAILABLE`。
- 指标定义从 `draft` 激活为 `active`；`active` 只能在同 scope、同 key 的更高 active 版本存在时退役。
- 已产生的定义内容和 `snapshot_hash` 不因激活或退役改变。
- 重复同 payload/幂等键返回首次结果；跨租户读取或写入被拒绝。

补充场景：

- JSON/enum 指标缺少自包含的 `quality_rules.value_schema` 时确定性拒绝。
- 事件通用消费者仍可按基础 aggregate payload 解析新增事件；Analytics 摄取边界额外要求完整观察字段。
- 全局和租户同名指标使用独立 scope/version 序列，不互相覆盖。
- 退役时替代版本仍为 draft、属于其他租户或版本不更高时拒绝。

## 实现规格

1. `analytics-event-catalog-v1.yaml` 为九类事件登记事件名、Schema、允许 source/subject、账号门禁 source、去重键和排序键；Schema 为封闭对象。
2. 九个事件使用统一事件信封和 `Observation` aggregate；事件 Schema 保持通用消费者兼容，`CanonicalEventCatalog.validate_event` 执行 Analytics 完整字段及账号门禁。
3. `MetricDefinition` 内容按契约生成确定性 ID 和 SHA-256 快照；定义版本内容不可覆盖，生命周期由追加式状态事实投影。
4. 状态机仅允许 `none → draft → active → retired`。退役要求同 scope、同 key、更高版本且已 active 的替代定义。
5. `metric_definitions`、`metric_definition_state_events`、`analytics_metric_definition_commands` 均有 SQLite/PostgreSQL 校验和 UPDATE/DELETE 阻断。
6. 迁移为 `20260920_media_006 → 20260920_analytics_001` 单头链，可降级删除本任务三张表和守卫。

## 验证

```text
python -m pytest tests/unit/analytics/test_metric_definition_service.py tests/integration/test_analytics_001_migration.py tests/contract/test_analytics_001_contract.py -q
```

Gate：`analytics_001_acceptance`

## 外部依赖

- 无；真实平台来源只在运行时受 `EXT-ACCOUNT-001` 门禁，Fake/人工/站点/QA/GEO 路径不依赖真实账号。

## 回滚

先停止新 MetricDefinition 写命令，保留已发事件和导出证据；Alembic 降级到 `20260920_media_006` 删除三张 Analytics 配置表及守卫。回滚不删除上游业务事件，也不得把平台来源降级伪装为 Fake 或人工来源。
