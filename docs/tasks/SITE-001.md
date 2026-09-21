# SITE-001 — 实现规范 URL、版本页、作者、审校者、更新时间、方法、证据、限制和 FAQ。

状态：`done`  
阶段：5（第一方知识中心、GEO_CONTENT 和 GEO_REGION）  
Owner：`team/knowledge_site`  
优先级：`high` / `P1`

## 目标

建立租户隔离的 `SitePage` 稳定根与不可变 `SitePageVersion` 投影。每个版本保存规范 URL 路径、来源 Canonical/Variant/Region 版本、作者、审校者、更新时间、方法、证据、限制、FAQ 和可见内容快照，供后续 SSR、结构化数据和抓取检查读取。

## 明确不做

- 不实现 SITE-002 的 SSR、预渲染、sitemap、feed、robots 或 hreflang。
- 不实现 SITE-003 的 JSON-LD，也不把未实现的媒体资产投影为 `VideoObject`。
- 不直接从知识站应用写 Canonical、Variant 或 Region 领域表；数据库适配器通过公开 Repository Port 接入。
- 不发布页面、不调用外部站点、不读取账号或平台凭证。

## 前置依赖

- `CANON-006`
- `PROD-002`

## 输入

- `TenantContext(org_id, actor_id)`、`trace_id`、`Idempotency-Key`
- `page_key`、`version_no`、`expected_previous_version`、规范 `url_path`、locale 和 render mode
- Canonical、可选 Variant 与 Region 的具体版本 ID
- 标题、摘要、作者、可选审校者、更新时间、方法步骤、证据引用、限制、FAQ 和可见内容块

## 输出

- 稳定 `SitePage` 根和不可变 `SitePageVersion` 读取投影
- 版本 `snapshot_hash`、幂等命令响应和不含正文的审计摘要
- 按租户读取单版本、页面及有序版本历史的公开用例

## 契约与迁移

契约：

- `packages/contracts/jsonschema/site-page-version.schema.json`

迁移：

- `packages/db/migrations/versions/20260919_site_001.py`

迁移新增 `site_pages`、`site_page_versions` 和 `site_page_commands`。版本与命令由数据库触发器保护为追加式；根对象只允许刷新当前版本指针和更新时间，稳定身份不可更改。

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
- `docs/foundation`
- `docs/tasks`
- `scripts`

禁止目录：

- `adapters/platforms`
- `deploy/environments/prod`
- `deploy/environments/prod/secrets`
- `secrets`
- `**/*.pem`
- `**/*secret*.json`
- `**/*token*.json`

## 实现规格

1. `SitePageService.create_version` 以 `(org_id, page_key)` 解析稳定根，以 `(org_id, site_page_id, version_no)` 追加版本。首版要求 expected previous version 为 0，后续版本必须连续递增；旧版不提供更新或删除入口。
2. `url_path` 必须是无 query、fragment、重复斜线和 dot segment 的绝对路径，去掉非根路径末尾斜线；应用保留 `/api`、`/internal`、`/admin`、健康检查和站点系统文件路径。`canonical_url` 在 SITE-001 中保存同一规范路径，绝对 origin 留给 SITE-002 配置。
3. locale 归一为稳定 BCP-47 形式。已有页面的 locale 与规范路径属于稳定身份，变更时必须创建新页面根，不能静默改写历史版本。
4. 版本必须保存作者；审校者可以为 `null`，以明确区分尚未审校。方法至少有一个步骤，证据至少有一个唯一引用；限制和 FAQ 使用稳定排序输入，重复 FAQ 问题、重复证据或无效哈希被拒绝。
5. 可选 Canonical、Variant 和 Region 只读 Port 接入后，必须验证版本 ID、租户和可用状态；跨租户、撤回或未批准来源拒绝。未接 Port 的本地构建只接受上游已校验的具体版本 ID，不读取领域私有存储。
6. 每个版本通过 JSON Schema 校验，`snapshot_hash` 由全部不可变输入确定性计算。公开读取返回深拷贝，调用方不能改写仓库内历史。
7. 同租户同 `Idempotency-Key` 和相同 payload 返回首次响应；payload 变化返回 `IDEMPOTENCY_KEY_REUSED`。审计只保存 ID、版本、trace、请求/快照哈希，不保存正文、FAQ 回答或证据摘录。
8. 知识站代码只使用 Repository Port，不包含直接 SQL；Alembic 迁移负责同租户复合外键、版本唯一约束和数据库不可变保护。

## Given–When–Then

补充场景：

- Given 合法来源版本和完整页面元数据，When 创建 v1，Then URL 与 locale 被规范化，版本通过契约校验并可按租户读取。
- Given 同一命令重复提交，When payload 相同，Then 返回同一页面与版本且只写一个版本；payload 不同返回 `IDEMPOTENCY_KEY_REUSED`。
- Given 页面已有 v1，When 以 expected previous version 1 创建 v2，Then 历史为 `[1, 2]` 且 v1 内容不变；跳号或 stale expected version 被拒绝。
- Given URL 含 query、fragment、重复斜线、dot segment 或使用保留应用路径，When 创建版本，Then 返回 `INVALID_CANONICAL_URL` 且不写版本。
- Given 方法为空、证据为空、证据哈希非法或 FAQ 问题重复，When 创建版本，Then 确定性拒绝且不生成审计成功事件。
- Given 来源 Port 返回其他租户、未批准 Variant 或未激活 Region，When 创建版本，Then 返回租户或来源状态错误，不泄漏其他租户内容。
- Given 其他租户读取页面或版本 ID，When 查询，Then 返回 `TENANT_SCOPE_VIOLATION`；相同 page key 可在不同租户独立存在。
- Given 调用方修改已返回的页面对象，When 再次读取，Then 仓库中的不可变快照保持原值。

## 权限、幂等、失败和审计

- 所有写命令要求 UUID 格式的 `org_id`、`actor_id`、非空 trace 和 8–200 字符的 Idempotency-Key。
- 版本冲突、URL、Schema、租户和来源状态错误属于确定性失败，不重试。
- 审计仅保留 `site_page_id`、version ID/no、actor、trace、request hash 和 snapshot hash。

## 回滚

停止创建新站点版本，保留已经生成的页面根、版本快照和命令证据只读。降级到 `20260919_found_model_003` 前先导出站点版本与审计摘要；不要改写已经接受的页面版本。

## 验证

```text
python -m pytest tests/unit/knowledge_site tests/integration --maxfail=1 -q
python scripts/check_task_card_precision.py --task SITE-001 --strict
python scripts/check_json_schemas.py
python scripts/check_architecture.py
python scripts/check_migrations.py --strict
```

Gate：`site_001_acceptance`

## 外部依赖

- 无；所有版本与迁移验证使用本地 Repository fixture 和 SQLite，不调用网络或真实发布服务。

## 开工前细化

已按规范 URL、不可变版本、Repository Port、幂等、租户隔离和失败路径细化并实现；证据见 `SITE-001-EVIDENCE.yaml`。
