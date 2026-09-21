# analytics

## 职责

Canonical events, metric definitions, observations and attribution.

## 固定布局

- domain/：实体、值对象、状态机和纯规则。
- application/：公开用例、命令、事务边界和权限检查。
- ports/：外部接口抽象和 DTO。
- infrastructure/：本地实现、仓储和事件发布器。
- projections/：可重建的只读投影。

## 表

`ANALYTICS-001` 创建 `metric_definitions`、`metric_definition_state_events` 和
`analytics_metric_definition_commands`。定义内容、生命周期事实和幂等命令均为
追加式记录，SQLite/PostgreSQL 守卫禁止覆盖或删除历史。

## 公开接口

`MetricDefinitionService` 创建租户或全局指标定义、严格追加版本、激活和在更高
active 版本存在时退役旧版本。`CanonicalEventCatalog` 校验九类规范事件，并在
`source=platform` 时要求外部账号证据；Fake、人工、站点、QA 和 GEO 路径不要求
真实账号。

`ObservationService` 将输入绑定到 active MetricDefinition 的精确 ID/版本/key/type，
按 `org_id + dedupe_key + observation_version` 去重，并以追加下一版本的方式修订。
`region`、`locale`、`data_quality` 分别表达市场/地区、语言区域和可信度分级；
站点、QA、GEO、Support 与平台来源必须保存来源快照引用。

## 事件

`analytics.content|asset|publication|interaction|geo|support|qa|cost|risk.observed`
使用统一事件信封和 `Observation` aggregate。目录位于
`docs/contracts/analytics-event-catalog-v1.yaml`，事件 Schema 位于
`packages/contracts/events/`。MetricDefinition 生命周期发布
`metric.definition.created|activated|retired`。
每个成功 Observation 同时写出 `observation.recorded` 和所属九类事件之一；事件和
审计仅携带元数据及快照哈希，不携带 metric value。

## 权限

所有租户业务调用必须经过 TenantContext 和授权检查。`org_id=null` 只允许显式
global catalog 管理入口创建；租户可以只读引用全局定义，不能读取其他租户定义。

## 公开边界

接口、事件和权限由对应任务卡与 JSON Schema 登记；本目录不得直接依赖其他模块的 infrastructure、FastAPI、ORM 或供应商 SDK。

## 禁止事项

不得保存 Token、完整 PII 或二进制；无账号阶段不得调用真实平台。
