# geo_content

## 职责

## GEO_CONTENT-001 已实现边界

`GeoContentRuleService` 是一个离线、确定性、租户隔离的只读规则服务。它从页面/站点快照和前置知识事实计算五个维度：

- 实体声明、canonical name/aliases 与可见文本一致性；
- Claim 与 Evidence 的双向关联、quote/locator 和来源链可追溯性；
- SourceSnapshot、RightsRecordVersion、Claim/Evidence 状态和有效期满足引用门禁；
- 页面、来源和权利的 freshness、expiry、review_due；
- canonical、locale、title/body 与 robots/noindex 的抓取性。

空知识输入、缺失 provenance 状态、缺少 source/rights、来源链不一致或 noindex 页面不会被标记为 citation-ready。SourceSnapshot 和 RightsRecordVersion 的关键快照/权利字段会在引用门禁中检查；Evidence 只接受 `source_snapshot_id` 与 `rights_record_version_id`，不会把 Source 或兼容别名冒充 Snapshot/权利版本。所有输入记录（包括 nested PolicySnapshot）必须属于调用租户。规则失败是确定性的，不触发网络、供应商、账号或真实凭证。

公开实现位于 `service.py`，输出符合 `geo-content-001.v1` 闭合契约。`output_hash` 对去除 `output_hash` 和 `audit_evidence` 后的规范化结果计算，审计证据随后加入结果，避免循环哈希。相同租户/幂等键/请求 hash（包含固定 `assessed_at`）重放原结果，冲突请求被拒绝并记录带 input/policy hash 的审计。

## 公开边界

本模块只读取租户范围的前置快照并生成评估投影；不改变 Entity、Claim、Evidence、Source、Rights、Canonical 或 SitePage 事实。

## 表

`geo_content_checks`、`geo_content_commands`、`geo_query_fixtures` 与 `geo_runs` 是本模块按任务修订依次拥有的追加式投影；幂等命令、Fixture 转换事件和离线样本摘要由可替换的内存 Port 保存。

## 公开接口

公开入口为 `GeoContentRuleService.assess`，别名 `evaluate`、`check`、`run` 只保留确定性评估语义。

## 契约与持久化

- 输出契约：`packages/contracts/jsonschema/geo-content-assessment.schema.json`
- Fixture 契约：`packages/contracts/jsonschema/geo-query-fixture.schema.json`
- FakeGeo Run 契约：`packages/contracts/jsonschema/geo-run.schema.json`
- 模块 union：`packages/contracts/jsonschema/geo_content.schema.json`
- 前置事实契约：`entity.schema.json`、`claim.schema.json`、`evidence.schema.json`、`source-snapshot.schema.json`、`rights-record-version.schema.json`
- 迁移：`packages/db/migrations/versions/20260919_geo_content_001.py`
- Fixture 迁移：`packages/db/migrations/versions/20260919_geo_content_002.py`
- Run 迁移：`packages/db/migrations/versions/20260920_geo_content_003.py`

每个任务迁移只创建自己的追加式表，并用 SQLite/PostgreSQL 触发器阻断 UPDATE/DELETE：GEO_CONTENT-001 创建评估与命令表，GEO_CONTENT-002 创建 `geo_query_fixtures`，GEO_CONTENT-003 创建 `geo_runs`。本模块不拥有或修改前置事实表。

## 事件

成功评估和拒绝评估分别记录 `geo_content.assessed` 与 `geo_content.assessment.rejected` 审计事件；本模块不发布外部供应商事件。

## 权限

所有输入记录、嵌套 PolicySnapshot 和命令键均按 `org_id` 隔离；actor、trace 和幂等键是公开命令边界的一部分。

## 禁止事项

禁止调用真实网络、供应商、账号、ORM 或生产凭证，禁止修改前置事实表，禁止把评估结果解释为搜索排名保证。

## 固定布局

- `domain/`：纯规则和值对象预留位置。
- `application/`：公开用例与命令边界预留位置。
- `ports/`：外部接口抽象与 DTO 预留位置。
- `infrastructure/`：本地持久化/事件适配预留位置。
- `projections/`：可重建的只读投影预留位置。

当前公开入口由 `modules.geo_content.GeoContentRuleService` 提供；目录边界禁止直接依赖其他模块的 infrastructure、FastAPI、ORM 或供应商 SDK。

本模块不执行真实平台调用。

## 后续任务边界

- `GEO_CONTENT-002` 已实现 Prompt 测试集、单次合规采样和 `geo_query_fixtures`。`GeoQueryFixtureService` 负责租户范围的 Fixture 创建、`created → active → retired` 版本迁移和幂等命令；`GeoComplianceSamplingService` 通过 `ComplianceSamplingPort` 接收离线答案，确定性记录 mention、citation、position、correctness。未知或缺失外部结果进入 `manual_review`，不会被解释为通过。
- `GEO_CONTENT-003` 已实现 `FakeGeo` 离线答案、多次采样解析、按结果哈希去重和确定性置信度汇总。重复答案不增加证据计数；全部未知样本生成 `failed` Run 和人工复核审计；输出固定为 `data_quality=estimated`，不代表真实搜索效果。

公开兼容入口还包括 `create`/`register`、`activate`、`retire`、单次 `sample`/`evaluate`，以及多次采样的 `GeoRunService.run`/`execute`/`aggregate`/`query`/`collect`/`parse`。默认 `DeterministicComplianceSampler` 只解析调用者提供的结果，不读取 URL、网络、供应商或真实账号。命令、转换事件、样本哈希和审计保存在可替换的内存 Port 中。

后续任务不得把模拟搜索效果或排名结论倒灌到 GEO_CONTENT-001 的确定性规则结果；GEO_CONTENT-003 的 Run 仅是离线解析稳定性证据。

## 验证

```text
python -m pytest tests/unit/geo_content tests/integration/test_geo_content_001.py tests/integration/test_geo_content_002.py tests/integration/test_geo_content_003.py tests/contract/test_geo_content_002_contract.py tests/contract/test_geo_content_003_contract.py -q
python scripts/check_json_schemas.py
python scripts/check_migrations.py --strict --json
```
