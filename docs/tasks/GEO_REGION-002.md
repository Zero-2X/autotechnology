# GEO_REGION-002 — 实现区域版本检查、hreflang、地区禁用内容和地域数据删除规则。

状态：`done`  
阶段：5（第一方知识中心、GEO_CONTENT 和 GEO_REGION）  
Owner：`team/geo_region`  
优先级：`high` / `P1`

## 目标

实现区域版本检查、hreflang、地区禁用内容和地域数据删除规则。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `PROD-002`
- `SITE-002`
- `GEO_REGION-001`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `GEO_REGION-002.implementation`
- `GEO_REGION-002.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/region-profile-version.schema.json`

需要在实现前补齐的新增契约（不能把这些结果塞进
`region-profile-version.schema.json`，该契约是 GEO_REGION-001 的不可变事实）：

- `packages/contracts/jsonschema/region-check-decision.schema.json`：区域版本、页面 locale/market、
  有效期和内容限制的逐项检查结果；顶层 `decision=eligible|deny|manual_review`，deny 优先于
  manual_review，必须带 `org_id`、`region_profile_version_id`、`page_version_id`（若有）、
  `input_snapshot_hash`、`checks[]`、`reasons[]` 和 `evaluated_at`。
- `packages/contracts/jsonschema/region-deletion-policy.schema.json`：按区域版本计算的
  `retention_days`、`deletion_sla_hours`、`data_residency`、`due_at`、`legal_hold` 和五类传播目标；
  这是删除命令的输入/证据投影，不是对历史 RegionProfileVersion 的更新。
- 若 SITE-002 继续直接接收渲染输入，应在 `site-page-version.schema.json` 增加可选的
  `market`、`permitted_regions`、`blocked_regions`/`region_policy` 字段；否则由 GEO_REGION-002
  的页面投影适配器接收这些字段，避免修改 SITE-001 的追加式页面事实。

迁移计划：

- `packages/db/migrations/versions/20260920_geo_region_002.py`

迁移新增租户复合键、追加式的 `region_policy_decisions` 投影，同时保存页面检查与删除计划的
非敏感字段和哈希；区域 Profile/Version 事实仍由 `20260920_geo_region_001` 所有，历史版本
不可更新/删除。迁移不得保存原始页面正文、答案或凭证，也不得改写现有区域、页面和删除事实。
## 目录边界

拥有目录：

- `modules/geo_region`

允许目录：

- `modules/geo_region`
- `apps/knowledge-site`
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

### 区域版本检查

`RegionEligibilityService.check_page` 只接受同一 `TenantContext` 的页面快照、具体
`region_profile_version_id` 和可选的 `market`；不得按可变 `RegionProfile.current_version_id`
偷偷替换输入版本。检查顺序固定为：租户/引用存在、Profile 与 Version 状态为 active、
`valid_from <= evaluated_at < valid_to`（空边界表示无界）、页面 locale 在 Version 的
`locales`、market/region_code 匹配、数据地域和平台资格、受限主题与必需披露。返回逐项
结果和稳定错误码：`TENANT_SCOPE_VIOLATION`、`REGION_VERSION_NOT_FOUND`、
`REGION_VERSION_INACTIVE`、`REGION_VERSION_EXPIRED`、`LOCALE_NOT_ALLOWED`、
`MARKET_NOT_ALLOWED`、`REGION_CONTENT_BLOCKED`、`DISCLOSURE_REQUIRED`。

### hreflang 与地区禁用

`filter_hreflang` 只保留同租户、同 `page_key`/canonical identity、状态为 `ready|published`、
且通过上述区域检查的页面；按规范化 BCP-47 locale 和 canonical URL 排序、去重，并最多添加
一个 `x-default`。被区域规则阻断、过期或缺少有效 RegionVersion 的页面不得出现在
alternate、sitemap、RSS 或 Atom。x-default 必须指向显式默认 locale 的合格页面，否则指向
排序最小的合格 locale；没有合格页面时不输出 alternate。

### 地域数据删除

`RegionDeletionService.plan` 从不可变 RegionProfileVersion 生成删除策略和 `due_at`（UTC），
校验 `retention_days`/`deletion_sla_hours` 与 `data_residency`，并将请求交给现有五阶段
`DeletionPropagationService`（关系库、对象、向量、缓存、导出包）。每阶段只有独立
`absent()` 验证和 evidence ref 后才算完成；失败进入人工队列。legal hold 或缺失策略只能
返回 `manual_review`，不得自动删除。相同租户、相同幂等键和 payload 必须重放同一计划/请求，
不同 payload 返回 `IDEMPOTENCY_KEY_REUSED`；跨租户引用统一拒绝。该任务不物理删除
RegionProfileVersion、SitePageVersion 或审计事实。

### 现有模块接入点

- `modules.geo_region.service.InMemoryRegionService.get_version/list_versions` 是只读版本来源；
  `RegionEligibilityService` 应作为同模块新增服务，保持离线、确定性和无网络副作用。
- `apps/knowledge-site/scripts/site_render.py` 的 `_alternates`、sitemap/feed 生成前必须接收
  一个可选的 eligibility/filter port；未注入时保留 SITE-002 行为以兼容既有调用方。
- `apps/knowledge-site/scripts/site_page.py` 已在创建版本时通过 `region_version_port` 校验
  同租户和 active；GEO_REGION-002 不得绕过该 Port 或回写页面事实。
- `modules.audit.deletion.DeletionPropagationService` 已提供五阶段、租户隔离、幂等、版本和
  manual-review 语义；复用它，避免新建第二套删除状态机。

## Given–When–Then

Given：

- `所有前置任务已完成`
- `TenantContext、trace_id 和 Idempotency-Key 可用`

When：

- `执行 GEO_REGION-002 的公开用例或内部命令`

Then：

- `实现区域版本检查、hreflang、地区禁用内容和地域数据删除规则。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/geo_region tests/unit/knowledge_site/test_site_render.py tests/integration/test_geo_region_001.py tests/integration/test_geo_region_002_migration.py tests/integration/test_geo_region_002_site_render.py tests/contract/test_geo_region_001_contract.py tests/contract/test_geo_region_002_contract.py -q
```

Gate：`geo_region_002_acceptance`

## 外部依赖

- 无

## 补充场景

- 当前 RegionProfile 指针发生变化后，显式传入的历史 RegionProfileVersion 仍按自身快照检查，不得替换为当前版本。
- `valid_to` 为排他边界；未生效、已过期、draft、retired 或 Profile 非 active 均不能进入公开页面。
- 输入顺序、actor 和 trace 变化不改变公开工件、请求哈希或策略结果哈希。
- 明确的地区拒绝优先于人工复核；过滤 Port 异常时渲染器失败闭合，不公开该页面。
- 缺少地域、保留期或删除 SLA 的旧版本只生成 `manual_review`；命令参数不得补写或覆盖不可变版本策略。
- legal hold 不创建传播请求；已删除和明确保留是无副作用完成态。
- 降级只删除 GEO_REGION-002 决策投影，保留 RegionProfileVersion、SitePageVersion 与既有审计/删除事实。

## 回滚

- 停止新区域检查和删除计划命令，导出 `region_policy_decisions`、决策/计划哈希及审计引用。
- 从站点渲染器撤下注入式 eligibility Port 即恢复 SITE-002 兼容行为，不修改任何页面或区域事实。
- 数据库降级到 `20260920_geo_region_001`；仅移除 GEO_REGION-002 的投影表、索引和触发器。
