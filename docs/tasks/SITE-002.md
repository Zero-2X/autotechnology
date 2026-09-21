# SITE-002 — 实现 SSR/预渲染、canonical、sitemap、RSS/Atom、robots、hreflang 和 `x-default`。

状态：`done`  
阶段：5（第一方知识中心、GEO_CONTENT 和 GEO_REGION）  
Owner：`team/knowledge_site`  
优先级：`high` / `P1`

## 目标

从 SITE-001 的不可变 `SitePageVersion` 快照生成确定性的公开站点投影：页面 HTML、canonical、hreflang/`x-default`、sitemap、RSS、Atom 和 robots。生成器只读输入快照，不访问网络，不生成 SITE-003 的 JSON-LD，也不发布到外部平台。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不实现 SITE-003 的 Article/TechArticle/Organization/Person/VideoObject JSON-LD。
- 不实现 GEO_REGION-002 的区域禁用、地域删除或区域版本决策。
- 不读取账号、凭证或调用外部站点；不执行真实 HTTP 发布。
- 不把草稿、superseded 或 rolled_back 版本列入公开页面、sitemap 或 feed。
- 不把 HTML 当作输入模板执行；页面快照中的文本必须先转义后输出。

## 前置依赖

- `PROD-002`
- `SITE-001`

## 输入

- `TenantContext`：`org_id`、`actor_id`、`trace_id`。
- 一个或多个同租户 `SitePageVersion` 映射；每个版本必须包含 SITE-001 契约字段。
- `base_origin`：仅允许 `https`（本地测试允许 `http`），必须有主机、不得有查询/片段/用户信息，并规范化为无尾斜杠 origin。
- 可选 `idempotency_key`（2–200 个字符）和固定的 `generated_at` 时钟。
- 可选同页其他 locale 版本，用于 hreflang；默认语言由显式 `x_default_locale` 指定，否则按 locale 字典序选取。

## 输出

- `html`：完整、可预渲染的 UTF-8 HTML，包含 title、description、可见内容、canonical、排序稳定的 hreflang links 和 `x-default`。
- `sitemap.xml`：仅包含公开版本的绝对 canonical URL，按 URL 字典序稳定排序，使用 `updated_at` 作为 `lastmod`。
- `rss.xml` 与 `atom.xml`：仅包含公开版本，按 `updated_at` 降序、canonical URL 升序排序；所有 XML 文本正确转义。
- `robots.txt`：固定的站点 disallow 规则和绝对 sitemap URL。
- `SitePublication` manifest：`org_id`、源 `site_page_version_id`/`snapshot_hash`、canonical URL、locale、artifact hashes、`generated_at` 和审计字段；同一租户同一幂等键重放必须返回字节与 manifest 均相同的结果。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/site-page-version.schema.json`
- `packages/contracts/jsonschema/site-publication.schema.json`

迁移：

- `packages/db/migrations/versions/20260919_site_002.py`

迁移只建立 `site_publications` 读模型表。它保存源版本、canonical、locale、产物哈希和完整 manifest；表按 `(org_id, site_page_version_id)` 唯一，带到 `site_page_versions` 的复合外键和组织隔离约束。该表是可由所属用例刷新的投影，不是新的内容事实源。

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

1. `SiteRenderService` 通过纯输入/公开 Port 读取页面快照；任何输入 `org_id` 与 `TenantContext.org_id` 不一致时返回 `TENANT_SCOPE_VIOLATION`，不泄漏外租户 URL 或正文。
2. 页面只接受 `ready` 或 `published` 版本；公开选择优先 `published`，同一 page/locale 只保留最高 `version_no`，冲突版本返回 `DUPLICATE_PUBLIC_ROUTE`。`draft`、`superseded`、`rolled_back` 不进入公开产物。
3. canonical 由规范化 origin 与 SITE-001 `canonical_url`/`url_path` 拼接；拒绝绝对输入、查询串、片段、`..`、双斜杠、保留系统路径和重复尾斜杠。所有相对路径拼接必须保持同一 origin。
4. HTML 使用标准库转义 title、summary、作者、方法、限制、FAQ 和 `visible_content.blocks[*].text`；不得执行或原样插入 `<script>`、标签或属性。页面不产生 JSON-LD。
5. hreflang 只使用同一 page/同一 canonical identity 的公开 locale 版本；locale 标签规范化为 BCP-47 风格并去重，按标签排序；`x-default` 指向显式默认 locale，否则使用排序最小 locale。没有有效 variant 时不输出虚假的 alternate。
6. sitemap、RSS、Atom、robots 均为确定性 UTF-8 文本；sitemap/feed 只接收当前公开版本，URL 和时间排序规则固定，XML/文本字段必须转义；robots 的 Sitemap 行指向 `${origin}/sitemap.xml`。
7. 每次生成计算各产物 SHA-256、源 snapshot hash 和请求 hash；同租户同幂等键与相同 payload 重放原结果，payload 变化返回 `IDEMPOTENCY_KEY_REUSED`。审计至少记录 event type、org、actor、trace、source version、request hash、artifact hashes 和耗时/生成时间。
8. 生成不写入页面事实；如使用 `site_publications`，只允许所属用例在同一事务刷新投影，不能改变 `SitePageVersion` 历史。缓存失效依据是源 `snapshot_hash`、版本号和 renderer 版本的组合哈希。

## Given–When–Then

Given：

- 同一 `org_id` 下存在一组通过 SITE-001 校验的 `published`/`ready` 页面版本，其中包含至少两个 locale。
- 页面标题、正文、FAQ 和 URL 中可以出现 HTML/XML 特殊字符。
- `TenantContext`、`trace_id`、`Idempotency-Key` 和固定时钟可用。

When：

- 用相同输入调用渲染命令两次。

Then：

- 两次返回的 HTML、sitemap、RSS、Atom、robots、manifest 和哈希完全相同。
- HTML 含正确 canonical、locale alternate 和唯一 `x-default`，且正文特殊字符已转义。
- sitemap/feed 不含 draft、superseded、rolled_back 或外租户版本。

## 补充场景

- 外租户页面或版本输入被拒绝并返回 `TENANT_SCOPE_VIOLATION`，响应不包含外租户内容。
- 同一 page/locale 出现两个公开版本时返回 `DUPLICATE_PUBLIC_ROUTE`，不生成部分产物。
- origin 含 query、fragment、用户信息或非允许 scheme 时返回 `INVALID_ORIGIN`。
- 同一幂等键重放相同请求返回原结果；改变任一页面快照、origin、locale 默认值或 renderer 版本返回 `IDEMPOTENCY_KEY_REUSED`。
- 无公开版本时生成空 sitemap/feed 和仍含 Sitemap 行的 robots，不虚构页面 URL。
- RSS/Atom 标题、摘要、正文和 URL 含 `&<>"'` 时仍是可解析 XML。

## 权限、幂等、失败和审计

- 由 `TenantContext` 注入 `org_id` 和 actor；跨租户访问必须拒绝。
- 这是只读渲染命令；幂等键按租户与请求哈希去重，不执行外部副作用。
- 确定性校验失败不重试；渲染失败不写入半成品 manifest；审计记录拒绝原因和 source snapshot。
- `site_publications` 只能保存同租户源版本的投影，不能覆盖源版本或改写历史。

## 验证

```text
python -m pytest tests/unit/knowledge_site tests/integration/test_site_001.py tests/integration/test_site_002.py --maxfail=1
python scripts/check_task_card_precision.py --task SITE-002 --strict
python scripts/check_json_schemas.py
python scripts/check_migrations.py --strict --json
```

Gate：`site_002_acceptance`

## 回滚

- 应用回滚：停止新渲染命令并回退 renderer 版本；历史 `SitePageVersion` 不变，旧 manifest 可按 source snapshot 重放。
- 数据库回滚：在无 `site_publications` 依赖的情况下执行 `alembic downgrade 20260919_found_site_001`，只删除 SITE-002 投影表及其索引，不删除 SITE-001 表或页面事实。
- 任何迁移失败都不得删除或重写已有页面版本；恢复后重新运行完整迁移和契约检查。

