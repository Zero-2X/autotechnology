# GEO_CONTENT-003 — FakeGeo 离线多次采样、解析去重与置信度汇总

状态：`done`  
阶段：5（第一方知识中心、GEO_CONTENT 和 GEO_REGION）  
Owner：`team/geo_content`  
优先级：`high` / `P1`

## 目标

使用 `FakeGeo` 读取调用者提供的离线答案 fixture，对同一条已激活的 `GeoQueryFixture` 执行 2–100 次确定性解析，按原始结果哈希去重，并生成闭合的 `GeoRun` 聚合投影。M1 只验收数据契约、解析和复放稳定性；所有结果固定标记为 `data_quality=estimated`。

## 明确不做

- 不联网、不调用真实生成式搜索供应商、账号、URL 或凭证。
- 不把模拟样本解释为真实搜索可见性、排名或效果保证。
- 不修改 Fixture、PageVersion 或其他前置事实。
- 不持久化原始答案正文；内存 Port 仅保留样本结果哈希和解析摘要。
- 不修改禁止目录或顺带实现 `GEO_REGION-*`。

## 前置依赖

- `FOUND-009`
- `PROD-002`
- `GEO_CONTENT-002`

## 精确输入

- `tenant_context` 或 `org_id`，以及可选 actor；全部前置记录和嵌套租户标记必须属于同一租户。
- `trace_id` 与非空 `idempotency_key`。
- UUID 格式的 `page_version_id`、`query_fixture_id`。
- 与已激活 Fixture 完全一致的 `locale`、`region`。
- 整数 `sample_count`，范围为 2–100；布尔值、浮点值和越界值均拒绝。
- 恰好一个离线答案来源：命令级 `answer_fixture`/`answers`/`samples`/`results`/`responses`，或构造 `FakeGeo` 时绑定的默认 fixture。
- 可选 `predecessor_artifacts` 与 `policy_snapshot`；前置状态未知、失败或未就绪时失败闭合。

答案 fixture 可以是数组，或只含一个答案集合键的对象。对象可携带 `query_fixture_id`/`fixture_id`、`fixture_hash`、`locale`、`region` 绑定；绑定不一致、集合键歧义、样本不足、非有限 JSON 或非法条目均拒绝。

## 精确输出

`GeoRun` 仅包含 `packages/contracts/jsonschema/geo-run.schema.json` 声明的 17 个必填字段：

- `id`、`org_id`、`page_version_id`、`query_fixture_id`；
- `locale`、`region`、`sample_count`、`parser_version`；
- `mention_count`、`citation_count`、`position_values`、`correctness_values`、`confidence`；
- `data_quality`、`fixture_hash`、`status`、`created_at`。

服务输出始终为 `data_quality=estimated`。至少一个唯一样本能确定为 `correct` 或 `incorrect` 时状态为 `succeeded`；全部唯一样本为 `unknown`/人工复核时状态为 `failed`，并写入 `geo.run.manual_review` 审计。

## 实现规格

1. `sample_count` 表示捕获并解析的总尝试数，重复答案仍计入尝试数。
2. 用解析结果的 `result_hash` 保留首次出现的唯一观察；重复答案不增加证据计数。
3. `mention_count` 是含至少一个目标实体 mention 的唯一观察数；`citation_count` 是含至少一个 citation 的唯一观察数。
4. `position_values` 是唯一观察的正整数主位置，经过去重和升序排列。
5. `correctness_values` 按首次出现顺序记录唯一的 `correct`、`incorrect`、`unknown`。
6. 对每个唯一观察计算信号分：mention 为 0.4、存在 citation 为 0.3、correct 为 0.3；然后计算：

   `confidence = round((唯一观察数 / sample_count) × (已知正确性观察数 / 唯一观察数) × 唯一观察平均信号分, 6)`

   全部未知时置信度为 0。重复样本降低唯一比率，不能抬高置信度。

## 契约与迁移

- 契约：`packages/contracts/jsonschema/geo-run.schema.json`，闭合对象且所有声明字段必填。
- 迁移：`packages/db/migrations/versions/20260920_geo_content_003.py`。
- 迁移只创建 `geo_runs`，以复合外键绑定同租户的 `site_page_versions` 和 `geo_query_fixtures`，并为 SQLite/PostgreSQL 安装 UPDATE/DELETE 阻断；降级只回到 `20260919_geo_content_002`。

## 目录边界

拥有目录：

- `modules/geo_content`

允许目录：

- `modules/geo_content`
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

- `TenantContext` 注入 `org_id` 和 actor；Fixture、Run 与嵌套前置数据的跨租户访问必须拒绝且不泄露内容。
- 请求哈希覆盖租户、页面、Fixture ID/版本/hash、locale、region、样本数、parser 版本、答案 fixture hash、前置输入与 Policy hash，不包含时钟、actor、trace 或幂等键。
- 同租户同键同 payload 返回原结果；同键不同 payload 返回 `IDEMPOTENCY_KEY_REUSED`。相同配置即使使用不同幂等键，也复用同一确定性 Run。
- Run ID 由租户和请求哈希确定性生成；成功、人工复核和拒绝分别审计为 `geo.run.completed`、`geo.run.manual_review`、`geo.run.rejected`。
- 审计记录 trace、actor、输入/输出版本与哈希、Policy hash、拒绝原因、耗时和成本；适配器异常统一脱敏。

## Given–When–Then

Given：

- 同租户的 `SitePageVersion` 已就绪；
- `GeoQueryFixture` 已激活且 hash 完整；
- `TenantContext`、trace、幂等键和至少两条离线答案可用。

When：

- 调用 `GeoRunService.run`（或 `execute`/`aggregate`/`query`/`collect`/`parse`）。

Then：

- 每条答案由声明版本的离线解析器处理，端口输出必须绑定正确 Fixture hash、parser 版本和原始结果 hash；
- 重复结果不会抬高 mention/citation/position/correctness 证据；
- 输出通过闭合 `GeoRun` Schema，原始 Fixture hash 保留，数据质量为 `estimated`；
- 相同 Fixture、parser、配置和答案 fixture 在时钟、actor、trace 或幂等键变化时仍返回同一 Run；
- 未知结果全部失败闭合并进入人工复核审计，不会被解释为通过。

## 补充场景

- 同一答案重复 2–100 次时仍只形成一条唯一证据，`sample_count` 保留尝试次数并降低置信度。
- 答案 fixture 同时给出多个集合键、绑定其他 Fixture、声明错误内容 hash、含非有限 JSON 或样本不足时必须以稳定错误码拒绝。
- 自定义 FakeGeo/解析器返回数量错误、Fixture hash、parser 版本、input/output/result hash 不匹配或抛出异常时必须失败闭合；底层异常文本不得写入审计。
- 跨租户 Fixture、Run 或任意深度的前置租户标记必须拒绝，且不能返回其他租户的数据。
- `created` 或 `retired` Fixture、locale/region 不一致、样本数类型或范围错误均不得生成 Run。

## 回滚

- 停止新的 FakeGeo Run 命令，并在降级前把既有追加式 Run、样本摘要和审计导出到受控证据归档供复核。
- 将数据库降级到 `20260919_geo_content_002`；该操作删除数据库内的 `geo_runs`、相关索引和触发器，保留 Fixture 与 GEO_CONTENT-001 数据；复核使用前一步归档。
- 恢复任务注册表和契约/迁移清单到降级前生成版本；不删除或重写前置事实。

## 验证

```text
python -m pytest tests/unit/geo_content/test_geo_run_service.py tests/integration/test_geo_content_003.py tests/contract/test_geo_content_003_contract.py -q
python scripts/check_json_schemas.py
python scripts/check_migrations.py --strict --json
python scripts/check_task_card_precision.py --task GEO_CONTENT-003 --strict
```

Gate：`geo_content_003_acceptance`

## 外部依赖

- 无；测试与实现必须完全离线。
