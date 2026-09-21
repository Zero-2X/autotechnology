# SITE-003 — 实现与可见内容一致的 Article、TechArticle、Organization、Person JSON-LD；仅在阶段 6 存在已批准视频资产时生成对应的 VideoObject。

状态：`done`  
阶段：5（第一方知识中心、GEO_CONTENT 和 GEO_REGION）  
Owner：`team/knowledge_site`  
优先级：`high` / `P1`

## 目标

从 SITE-001 的不可变 `SitePageVersion` 快照生成确定性的 JSON-LD 和可插入 HTML 的 `application/ld+json` 脚本。结构化数据只能描述页面已经可见的标题、摘要、正文、方法、限制、FAQ、作者、审校者和更新时间；不调用网络、不读取凭证、不写入内容事实，也不把结构化数据当作排名或授权保证。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不实现 GEO_CONTENT 采样、排名指标或外部搜索接口。
- 不实现阶段 6 以前的 `VideoObject`；没有阶段 6 且已批准的视频资产时绝不生成视频节点。
- 不生成 SITE-004 的可访问性、性能或 HTTP 状态检查。
- 不把正文、FAQ 或来源摘录写入审计；审计只保存哈希、ID 和决策字段。

## 前置依赖

- `PROD-002`
- `SITE-001`
- `SITE-002`

## 输入

- `SitePageVersion` 映射，或包含该映射的 `predecessor_artifacts`；页面必须属于当前租户且状态为 `ready` 或 `published`。
- `TenantContext`：`org_id`，可选 `actor_id`、`trace_id`；也支持对应的显式参数。
- `base_origin` 和页面相对 `canonical_url`/`url_path`；绝对 URL 必须与 origin 相同。
- 可选 `organization`/`site_identity`（名称、URL、logo、sameAs）；缺省使用站点 origin 和稳定的默认名称。
- 可选 `article_type`（`Article` 或 `TechArticle`）；未指定时按页面 `is_technical`/`content_type` 推断，缺省为 `Article`。
- 可选阶段号、已批准视频资产、Policy snapshot 和 2–200 字符 `idempotency_key`。

## 输出

- `site-structured-data.schema.json` 约束的结果，包含 `jsonld`（`@context`、`@graph`）、稳定排序的 `jsonld_text`、安全的 `script`、源快照哈希、请求/结果哈希和渲染版本。
- 一个 Article 或 TechArticle 节点、一个 Organization 节点、作者 Person 节点和可选审校者 Person 节点；节点通过稳定 `@id` 互相引用。
- 只有当前阶段和资产阶段均不小于 6、资产类型为 video 且审批状态为 `approved`（或 `approved: true`）时，才附加 VideoObject。
- `audit_evidence`：事件类型、租户、actor、trace、输入版本 ID、源/请求/输出哈希、Policy snapshot、视频是否包含、生成时间、耗时和成本。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/site-page-version.schema.json`
- `packages/contracts/jsonschema/site-structured-data.schema.json`

迁移：

- `packages/db/migrations/versions/20260919_site_003.py`

SITE-003 是只读投影。迁移是可回滚的空 revision，用于把发布证据与迁移头对齐，不新增表、不改变 `site_pages`、`site_page_versions` 或 `site_publications`，也不产生新的内容事实源。

## 目录边界

拥有目录：

- `apps/knowledge-site`

允许目录：

- `apps/knowledge-site`
- `apps/api`
- `tests/accessibility`
- `tests/e2e`
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

## 实现规格

1. `SiteStructuredDataService` 只读取映射和可替换的内存命令/审计 Port；不包含 SQL、网络、账号或发布调用。页面租户与 `TenantContext.org_id` 不一致时返回 `TENANT_SCOPE_VIOLATION`，错误文本不得回显外租户正文。
2. 只接受 `ready`/`published` 页面。`draft`、`superseded`、`rolled_back` 返回 `PAGE_NOT_RENDERABLE`，不生成部分 JSON-LD。
3. origin 规范化为无尾斜杠的 `http`/`https` origin；canonical 必须同源、无凭证、query、fragment、dot segment 或反斜杠，且与 `url_path` 一致。
4. Article/TechArticle 的 `headline`、`description`、`inLanguage`、`dateModified`、`datePublished`、`articleBody`、作者、审校者和 publisher 均来自页面快照。`articleBody` 按 SITE-002 可见内容块、方法步骤、限制和 FAQ 的稳定顺序组装，不注入 HTML；组合后无任何可见正文时返回 `VISIBLE_CONTENT_REQUIRED`。
5. Organization 和 Person 节点只保留白名单字段；URL 必须是 `http(s)`，sameAs 按字典序去重。跨租户 organization、author、reviewer 或 video asset 输入必须拒绝。
6. `jsonld_text` 使用稳定 JSON 序列化；插入脚本前转义 `<`、`>`、`&`，防止正文中的 `</script>` 截断脚本。输出不包含 SITE-003 之外的 JSON-LD 类型。
7. VideoObject 的双重门禁是 `phase >= 6`、资产 `phase/stage >= 6`、类型为 video、状态为 approved；门禁不满足时忽略资产，不伪造视频节点。通过门禁的资产必须有同租户 `contentUrl` 和时间戳。
8. 每次成功生成计算源 snapshot、请求、JSON-LD/脚本结果哈希；输入显式携带的 `snapshot_hash` 必须是 64 位 SHA-256，否则返回 `INVALID_SNAPSHOT_HASH`，不得静默替换上游证据。同租户同幂等键相同 payload 返回完全相同结果，payload 或 renderer 版本变化返回 `IDEMPOTENCY_KEY_REUSED`。失败只记录拒绝码和版本 ID，不写命令结果。

## Given–When–Then

Given：

- 同一租户存在通过 SITE-001 校验的 `published` 页面，页面含特殊字符、作者、审校者、方法、限制和 FAQ。
- `TenantContext`、固定时钟和可选组织信息可用。

When：

- 以相同输入调用 SITE-003 两次，并把返回结果作为页面的结构化数据。

Then：

- 两次的 JSON-LD、脚本、manifest 和哈希完全相同；Article/Organization/Person 节点引用一致，正文特殊字符不会形成脚本标签。
- JSON-LD 中的正文和元数据与可见页面快照一致，输出通过 `site-structured-data.schema.json`。

## 补充场景

- 外租户页面、组织、作者或视频输入返回 `TENANT_SCOPE_VIOLATION`，响应和成功结果不包含外租户内容。
- `draft`、`superseded`、`rolled_back` 页面被拒绝；拒绝审计保留错误码和输入版本 ID。
- 页面缺失 origin、canonical 含 query/fragment、跨源或与 `url_path` 不一致时返回稳定 canonical/origin 错误。
- `is_technical=true` 或显式 `TechArticle` 生成 TechArticle；其他页面缺省生成 Article；非法类型被拒绝。
- 阶段 5、未批准资产或非 video 资产不生成 VideoObject；阶段 6 的同租户 approved video 只有在 contentUrl 和上传时间完整时才生成，批准资产缺少必填字段会被拒绝。
- 同一幂等键重放相同请求返回原结果；改变页面快照、origin、article type、Policy snapshot、视频输入或 renderer 版本返回 `IDEMPOTENCY_KEY_REUSED`。
- 组织缺省时仍生成确定性的默认 Organization；无 FAQ、限制或可见块时不虚构文本，且页面所有可见正文来源均为空时拒绝生成。

## 权限、幂等、失败和审计

- 所有命令按租户执行；`actor_id`、`trace_id` 只进入审计，不改变结构化数据内容。
- 确定性输入、租户、状态和 URL 错误不重试；没有外部副作用，不创建人工发布任务。
- 审计成功事件为 `site.structured_data.generated`，拒绝事件为 `site.structured_data.rejected`；正文、FAQ 答案和原始资产内容只通过哈希关联。

## 验证

```text
python -m pytest tests/unit/knowledge_site tests/integration/test_site_001.py tests/integration/test_site_002.py tests/integration/test_site_003.py --maxfail=1
python scripts/check_task_card_precision.py --task SITE-003 --strict
python scripts/check_json_schemas.py
python scripts/check_migrations.py --strict --json
```

Gate：`site_003_acceptance`

## 回滚

- 应用回滚：停止 SITE-003 生成命令并回退 renderer 版本；页面版本和已生成的只读响应不被改写，可按源 snapshot 重放。
- 数据库回滚：执行 `alembic downgrade 20260919_found_site_002` 只移除空 revision，不删除 SITE-002 投影表或 SITE-001 页面事实。
- 迁移失败不得删除或重写页面版本；恢复后重新执行 schema、迁移和站点回归门禁。
