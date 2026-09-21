# GEO_CONTENT-002 — 建立 Prompt 测试集和合规采样接口，记录提及、引用、位置和正确性。

状态：`done`  
阶段：5（第一方知识中心、GEO_CONTENT 和 GEO_REGION）  
Owner：`team/geo_content`  
优先级：`high` / `P1`

## 目标

建立 Prompt 测试集和合规采样接口，记录提及、引用、位置和正确性。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `PROD-002`
- `SITE-002`
- `GEO_CONTENT-001`

## 输入

- `predecessor_artifacts`：可选的 SITE-002 / PROD-002 / GEO_CONTENT-001 快照映射；若提供，所有嵌套 `org_id`/`tenant_id` 必须等于当前租户，显式 `ready=false`、`eligible_for_citation=false` 或失败/过期状态拒绝。
- `tenant_context`：至少包含 `org_id`（可含 `tenant_id`、`actor_id`、`trace_id`）；重复租户标记必须一致。
- `idempotency_key`：创建、状态迁移和采样命令均必填，按租户隔离并绑定规范化 payload hash。
- 创建命令还接收 `query`（`prompt` 为兼容别名）、`locale`、`region`、`expected_entities`、`expected_claim_ids`、可选 `policy_snapshot` 与 `metadata`。
- 采样命令接收已捕获的 `result`/`answer`/`raw_result`；服务不从 URL 或供应商读取答案。

## 输出

- `GEO_CONTENT-002.implementation`：租户隔离的 `GeoQueryFixtureService` 与 `GeoComplianceSamplingService`。
- `GEO_CONTENT-002.tests`：契约、幂等/版本、迁移和离线采样测试。
- `audit_evidence`：输入/输出 hash、trace、actor、版本、Policy 快照 hash、状态、拒绝原因、耗时和成本。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/geo-query-fixture.schema.json`（闭合对象；所有声明字段都必须存在，暂无值的审计关联字段显式为 `null`）。

迁移计划：

- `packages/db/migrations/versions/20260919_geo_content_002.py`（仅 `geo_query_fixtures`；命令、事件和采样结果使用可替换的内存 Port，不提前创建 GEO-003 的 `geo_runs`）。
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

- 由 `TenantContext` 注入 `org_id` 和 actor；跨租户访问必须拒绝。
- 写命令使用 `Idempotency-Key` 和 payload hash；状态修改使用 `If-Match` 或 expected version。
- 确定性校验失败不重试；临时失败按任务卡与策略退避；未知外部结果转人工核查。
- 记录 `trace_id`、actor、输入/输出版本、Policy 快照、拒绝原因、耗时和成本。

## 实现规格

### Fixture 聚合

- `GeoQueryFixtureService.create_fixture`（别名 `create`、`register`、`create_query_fixture`）生成状态为 `created`、版本为 `1` 的不可变 Fixture。`fixture_hash` 只覆盖规范化业务输入，不覆盖时钟、trace 或生成的 ID；同租户同幂等键同 hash 重放原结果，hash 不同返回 `IDEMPOTENCY_KEY_REUSED`。
- `activate_fixture`（别名 `activate`）只允许 `created → active`；`retire_fixture`（别名 `retire`）只允许 `active → retired`。两者必须提供 `expected_version` 或 `If-Match`，每次迁移追加新版本和 `geo.fixture.activated`/`geo.fixture.retired` 事件，不覆盖历史版本。
- `get_fixture`/`list_fixtures` 只返回当前租户的投影；跨租户 ID、嵌套前置快照和双租户标记统一返回 `TENANT_SCOPE_VIOLATION`。

### 合规采样 Port

- `ComplianceSamplingPort` 的默认实现 `DeterministicComplianceSampler` 只解析调用者提供的离线结果；不发起网络、供应商、账号或凭证访问。`GeoComplianceSamplingService.sample`（别名 `sample_fixture`、`collect`、`evaluate`、`run`）把采样绑定到 Fixture、租户、可选 `page_version_id` 和 Policy 快照。
- 输出至少包含 `mentioned`/`mention_count`、`mentions`、`citations`/`citation_count`、`position`/`positions`、`correctness`/`correctness_score`、`status`、`fixture_hash`、`input_hash`、`output_hash`、`parser_version`、`trace_id`、`actor_id`、版本、耗时和成本。引用只记录传入的 URL/ref，不访问其内容。
- 缺少结果、结果状态为 `unknown`/`pending`/`error`、或显式要求人工核查时，输出 `status=manual_review`、`review_required=true`、`unknown_external_result=true`，并追加 `geo.sample.manual_review` 审计事件；不把未知值转为通过。

### 边界

- 本任务只建立单 Fixture 和单次离线观察接口；多次采样、答案 fixture、解析去重、置信度汇总和 `geo_runs` 留给 GEO_CONTENT-003。
- 迁移为 SQLite/PostgreSQL 安装 UPDATE/DELETE 阻断；应用 Port 的 `fixtures`、`fixture_versions`、`commands`、`events`、`audit` 均只追加记录。

## Given–When–Then

Given：

- `PROD-002`、`SITE-002` 和 `GEO_CONTENT-001` 的前置快照已完成或未被显式标记为不可用
- `TenantContext、trace_id 和 Idempotency-Key 可用`

When：

- `以同一租户和 payload 调用 create_fixture 两次`
- `使用 expected_version/If-Match 调用 activate_fixture 或 retire_fixture`
- `向 sample 提供离线答案、引用或 unknown/pending 结果`

Then：

- `第二次创建重放同一 Fixture；不同 payload 被拒绝并留下拒绝审计。`
- `状态迁移只接受 created→active→retired，旧版本仍可从 append-only Port 读取，错误 If-Match 被拒绝。`
- `采样确定性记录 mention、citation、position、correctness；未知/缺失外部结果为 manual_review。`
- `输出契约、审计事件和指定测试结果可复现，且跨租户前置快照始终拒绝。`

## 补充场景

- 空或非映射 `tenant_context`、不一致的 `org_id`/`tenant_id`、以及跨租户 Fixture 或前置快照必须以稳定错误码拒绝，不能泄漏其他租户数据。
- 同租户同幂等键只在规范化业务 payload 相同且请求哈希一致时重放；时钟、trace、actor 或生成的 Fixture ID 变化不得制造冲突。
- `created → active → retired` 之外的状态迁移、缺少 `expected_version`/`If-Match`、错误版本和空退役理由必须拒绝，并保留追加式拒绝审计。
- 前置快照显式 `ready=false`、`eligible_for_citation=false`、`pending`、`draft`、`failed`、`expired` 或未知状态时必须 fail closed。
- 采样缺少结果或收到 `unknown`/`pending`/`error` 时必须进入 `manual_review`，不读取 URL 内容、不访问网络，也不把未知值解释为通过。

## 回滚

- 停止新的 Fixture 创建、状态迁移和采样命令；保留已有追加式版本、事件和审计证据供查询与复核。
- 将数据库降级到 `20260919_geo_content_001`，只移除 `geo_query_fixtures` 及其索引/触发器，不修改 GEO_CONTENT-001 的评估表或前置事实。
- 恢复任务注册表、contract manifest 和 migration manifest 到降级前生成版本，并保留本证据文件记录回滚原因与操作时间。

## 验证

```text
python -m pytest tests/unit/geo_content tests/integration/test_geo_content_001.py tests/integration/test_geo_content_002.py tests/contract/test_geo_content_002_contract.py -q
```

Gate：`geo_content_002_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
