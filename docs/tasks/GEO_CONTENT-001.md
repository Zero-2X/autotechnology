# GEO_CONTENT-001 — 建立实体一致性、Claim/Evidence 可追溯、引用就绪、内容新鲜度和抓取性规则

状态：`done`  
阶段：5（第一方知识中心、GEO_CONTENT 和 GEO_REGION）  
Owner：`team/geo_content`  
优先级：`high` / `P1`

## 目标

在不改变实体、Claim、Evidence、Source 或 Rights 事实的前提下，提供一个离线、确定性、租户隔离的只读评估器。评估器把页面可见内容和前置事实投影为五个维度：实体一致性、Claim/Evidence 可追溯、引用就绪、内容新鲜度和抓取性。评估结果只表示当前输入快照是否满足规则，不表示搜索排名、生成式搜索效果或事实真实性保证。

## 明确不做

- 不实现 GEO_CONTENT-002 的 Prompt 测试采样、提及/位置解析或外部搜索调用。
- 不实现 GEO_CONTENT-003 的多次采样、去重、置信度汇总或 FakeGeo 运行记录。
- 不创建、更新或删除 Entity、Claim、Evidence、Source、Rights、Canonical 或 SitePage 事实。
- 不调用真实网络、供应商、账号、对象存储或生产凭证。
- 不修改已完成 SITE-001、SITE-002、SITE-003 的文件和行为。

## 前置依赖

- `CANON-006`：提供租户范围的 Canonical lineage 查询边界。
- `PROD-002`：提供变体来源与版本语义。
- `SITE-001`：提供页面、locale、可见正文和 canonical 页面快照。

## 实现规格

### 输入边界

`GeoContentRuleService.assess` 接受显式 `TenantContext`（`org_id`、`actor_id`）、`trace_id`、`idempotency_key`、固定 `assessed_at`，以及页面/站点版本、canonical、Entity、Claim、Evidence、SourceSnapshot、RightsRecordVersion 和可选 PolicySnapshot。所有嵌套记录的 `org_id` 必须与租户一致；缺失或越界记录确定性拒绝并写入拒绝审计。输入按稳定 JSON 序列化后计算 `input_hash`，并将 `assessed_at` 纳入幂等请求边界。`sources`、`source_id`、`snapshot_id` 和 `rights_id` 等别名不会被当作引用链字段；Evidence 必须使用 `source_snapshot_id` 与 `rights_record_version_id`。

SourceSnapshot 用于引用前必须具备 `source_id`、`captured_at`、`content_hash`、`storage_object_ref` 和合法状态；RightsRecordVersion 必须具备来源快照列表、权利主体、策略版本、快照哈希和允许用途，已验证版本还必须有验证人和验证时间。若输入携带 Source 根对象，服务会核对 `current_snapshot_id` 与 Snapshot 的 `source_id`；Evidence、Rights 和页面的 locale/region/version 作用域不一致或无法确定时不能进入引用就绪。

### 五个规则维度

1. **实体一致性**：页面声明的实体 ID 必须存在且属于同一租户；声明的 `canonical_name` 和 aliases 至少有一个在可见文本中出现，声明引用与实体实际名称/别名不一致时产生 finding。实体缺失状态按 review 处理，不默认视为可信。
2. **Claim/Evidence 可追溯**：每个 Claim 必须有同租户 Evidence，Evidence 的 `claim_id` 反向指回 Claim，引用必须有 quote/locator/source_snapshot；双向关系不一致、孤儿 Evidence、缺少状态或缺少证据均产生稳定 finding。
3. **引用就绪**：Claim、Evidence、SourceSnapshot、RightsRecordVersion 的状态、有效期、允许用途、quote/locator 和来源链必须满足引用门禁。缺少 Claim/Evidence、来源或权利，或者过期、撤回、未验证状态时，输出 `eligible_for_citation=false`；空知识输入不能宣称 citation-ready。
4. **内容新鲜度**：页面、Claim、SourceSnapshot、RightsRecordVersion 的状态和 freshness/expiry/review_due 按 `assessed_at` 校验；过期、撤回、缺失状态或未来/非法日期产生 review 或 fail finding。
5. **抓取性**：页面必须有合法同源 canonical、有效 locale/title/body，且不能被 robots `noindex`、不允许索引状态或无效 URL 阻断。canonical 与 `url_path` 规范化后必须一致；绝对 URL 必须与 `base_origin`/`site_origin`/`origin` 同源，只有相对路径而没有 origin 时拒绝。canonical 拒绝反斜杠、双斜线、`.`/`..` dot segment、编码分隔符、控制字符和 malformed percent escape。

### 输出、哈希和幂等

输出符合 `geo-content-001.v1` 闭合 JSON Schema，包含五个维度、稳定排序的 findings、`eligible_for_crawl`、`eligible_for_citation`、`source_refs` 和审计证据。`output_hash` 是对去除 `output_hash` 与 `audit_evidence` 字段的规范化结果计算的 SHA-256，避免循环哈希；审计证据随后写入同一结果。相同租户、幂等键和 request hash 重放首次结果；同键不同 hash 确定性返回冲突并不重复写入。成功和拒绝路径都保留 actor、trace、policy hash、输入/输出 hash、版本和原因。

## 契约与迁移

- `modules/geo_content/service.py`
- `modules/geo_content/README.md`
- `packages/contracts/jsonschema/geo-content-assessment.schema.json`
- `packages/contracts/jsonschema/site-page-version.schema.json`
- `packages/contracts/jsonschema/canonical-content-version.schema.json`
- `packages/contracts/jsonschema/claim.schema.json`
- `packages/contracts/jsonschema/evidence.schema.json`
- `packages/contracts/jsonschema/source-snapshot.schema.json`
- `packages/contracts/jsonschema/rights-record-version.schema.json`

迁移：

- `packages/db/migrations/versions/20260919_geo_content_001.py`

### 数据库迁移

实现迁移 revision `20260919_geo_content_001`。

迁移只创建追加式评估投影与幂等命令表：`geo_content_checks`、`geo_content_commands`，并为 SQLite/PostgreSQL 安装 UPDATE/DELETE 阻断。它不创建 `geo_query_fixtures` 或 `geo_runs`；后两者分别由 GEO_CONTENT-002/003 负责，也不写入前置事实表。降级目标为 `20260919_found_site_003`，只删除本任务的表和索引。

## 补充场景

- 页面没有 Claim 或 Evidence：状态为 `review`，出现 `CLAIMS_MISSING`/`EVIDENCE_MISSING`，`eligible_for_citation=false`。
- 缺少 canonical 页面快照：状态至少为 `review`，抓取和引用资格均保持关闭，页面自身的 URL 不替代前置 canonical 快照。
- Claim 缺少状态、freshness、source 或 rights；Evidence 缺 quote/locator、反向 claim 关系不一致或成为孤儿：确定性 finding，不能进入 citation-ready。
- SourceSnapshot 过期/撤回、RightsRecordVersion 过期/未验证/用途不允许：引用维度阻断并保留来源引用。
- 页面 robots `noindex`、非法 canonical、跨租户页面或 nested PolicySnapshot：拒绝或抓取维度 fail，不降级为可引用。
- canonical 与 `url_path` 不一致、跨 origin、缺少相对路径 origin、canonical 快照路径/版本不一致：抓取维度 fail；抓取或 freshness 未通过时不能宣称 citation-ready。
- Entity 声明 ID 存在但 canonical_name/alias 不出现在 visible text：产生 `ENTITY_NOT_VISIBLE` finding。
- SourceSnapshot/权利版本字段不完整、来源链不一致、适用 locale/region/version 不明或不匹配：引用维度 fail 并保留 finding。
- 同一 idempotency key 重放相同 payload 返回相同 hash；payload hash 冲突返回确定性错误且不改变原结果。
- 迁移升级后 UPDATE/DELETE 被追加式触发器拒绝；降级后本任务表消失，SITE-001/002 数据仍存在。

## 目录边界

拥有目录：`modules/geo_content`  
允许目录：`modules/geo_content`、`packages/contracts`、`packages/db/migrations`、`tests/unit`、`tests/integration`、`tests/contract`  
禁止目录：`adapters/platforms`、`deploy/environments/prod`、`deploy/environments/prod/secrets`、`secrets`、`**/*.pem`、`**/*secret*.json`、`**/*token*.json`

## 权限、失败和审计

- `TenantContext` 注入 `org_id` 和 actor；任何跨租户输入、嵌套 policy 或 predecessor 记录都必须拒绝。
- 评估是只读规则计算；确定性规则失败不重试，未知外部状态只能进入 review（本任务不产生外部调用）。
- 每次成功或拒绝均记录 `trace_id`、actor、rule version、policy snapshot hash、输入/输出 hash、finding codes、耗时和幂等键。

## Given–When–Then

Given：所有前置任务已完成，`TenantContext`、`trace_id`、固定评估时间和 `Idempotency-Key` 可用，且输入快照属于同一租户。  
When：执行 `GeoContentRuleService.assess` 的公开用例或内部命令。  
Then：

- 五个规则维度按稳定顺序输出 pass/review/fail 与 finding refs。
- 缺失知识、来源、权利或抓取条件不会被宣称为 citation-ready/crawl-ready。
- 输出通过 `geo-content-001.v1`，哈希、审计和幂等重放可复现。
- 任何拒绝不修改前置事实，并留下可验证的拒绝审计。

## 验证

```text
python -m pytest tests/unit/geo_content tests/integration/test_geo_content_001.py -q
python scripts/check_json_schemas.py
python scripts/check_migrations.py --strict --json
python scripts/check_task_card_precision.py
```

专项目标结果：unit/integration `24 passed`；迁移 head 为 `20260919_geo_content_001`，revision count 为 `100`。完整回归由发布门禁统一执行。

Gate：`geo_content_001_acceptance`

## 外部依赖

无。

## 回滚

停止 GEO_CONTENT-001 评估命令并保留已有不可变评估证据；将迁移降级到 `20260919_found_site_003`，只删除 `geo_content_checks`、`geo_content_commands` 及其索引/触发器。前置 Entity、Claim、Evidence、Source、Rights、Canonical 和 Site 数据不回滚、不改写。
