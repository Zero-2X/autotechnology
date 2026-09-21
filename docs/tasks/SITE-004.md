# SITE-004 — 实现断链、重定向、HTTP 状态、性能、alt、字幕和动态渲染检查。

状态：`done`  
阶段：5（第一方知识中心、GEO_CONTENT 和 GEO_REGION）  
Owner：`team/knowledge_site`  
优先级：`high` / `P1`

## 目标

实现断链、重定向、HTTP 状态、性能、alt、字幕和动态渲染检查。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `PROD-002`
- `SITE-002`
- `SITE-003`
- `GEO_REGION-002`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `SITE-004.implementation`
- `SITE-004.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/site-page-version.schema.json`
- `packages/contracts/jsonschema/site-quality-report.schema.json`：闭合、追加式的质量报告，只保存检查、指标、哈希和稳定错误码，不保存原始 HTML 或动态 DOM。

迁移计划：

- `packages/db/migrations/versions/20260920_site_004.py`
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

## 权限、幂等、失败和审计

- 由 `TenantContext` 注入 `org_id` 和 actor；跨租户访问必须拒绝。
- 写命令使用 `Idempotency-Key` 和 payload hash；状态修改使用 `If-Match` 或 expected version。
- 确定性校验失败不重试；临时失败按任务卡与策略退避；未知外部结果转人工核查。
- 记录 `trace_id`、actor、输入/输出版本、Policy 快照、拒绝原因、耗时和成本。

## 实现规格

### 输入与副作用边界

`SiteQualityService.audit` 接收同租户 `SitePageVersion`、SITE-002 的 SSR/预渲染 HTML、页面 HTTP 状态、链接观测、性能指标和可选的动态 DOM 快照。默认实现不得访问网络或启动浏览器；链接状态和动态快照必须由调用方提供，或通过显式注入的受控 Port 获取。Port 缺失、超时或返回未知结果时进入 `manual_review`，不得把未知状态当作通过。

报告只保留规范化 URL、计数、阈值、稳定检查码和输入/输出哈希。原始 HTML、DOM、响应正文、凭证、Cookie、请求头和带凭证 URL 不得写入报告、审计或数据库。

### 链接、重定向和 HTTP 状态

- 只检查 HTML 中的 `http/https`、相对链接、canonical、媒体和字幕资源；`mailto`/`tel` 记录为跳过，`javascript`、带凭证 URL和不受支持 scheme 直接失败。
- 相对 URL 按页面 canonical origin 规范化，去除 fragment 后去重排序；同页 fragment 必须能解析到已存在的 `id`。
- 页面公开状态必须返回 HTTP 200。链接 2xx 通过，3xx 必须提供 `final_url` 与完整 `redirect_chain`；循环、缺目标或超过 `max_redirects=1` 失败。4xx/5xx 和探测错误记为断链，缺少观测进入人工复核。
- 所有结果由传入观测或 Fake Port 决定，不发起真实 HTTP 请求。

### 性能预算

默认确定性阈值为：`LCP <= 2500ms`、`CLS <= 0.1`、`INP <= 200ms`、`TTFB <= 800ms`、压缩后页面总字节数 `<= 1,500,000`。调用方可传入闭合的版本化阈值快照；缺指标进入人工复核，非有限数、负值或未知阈值字段拒绝输入，超过阈值失败。

### alt、字幕和动态渲染

- 非装饰性 `<img>` 必须有非空 `alt`；只有 `role=presentation`、`aria-hidden=true` 或 `data-decorative=true` 的图片允许空 alt。
- 每个 `<video>`/`<audio>` 必须存在 `kind=captions` 且带 `src`、`srclang` 的 `<track>`；字幕资源同样进入链接状态检查。
- SSR/静态 HTML 必须包含唯一 canonical、可见标题和非空 `<main>`。若提供动态 DOM 快照，其 canonical、标题和 main 可见文本必须保留；若页面声明 `dynamic_required=true` 而缺少快照则进入人工复核。动态快照不得引入不同 canonical 或丢失关键内容。

### 决策、幂等与持久化

检查顺序固定为 tenant/页面引用、页面 HTTP、链接与重定向、性能、alt、字幕、动态渲染。任一确定性失败使报告 `status=blocked`；无失败但存在未知项时为 `manual_review`；其余为 `passed`。相同租户、幂等键和输入哈希返回相同报告，不同输入返回 `IDEMPOTENCY_KEY_REUSED`；actor、trace 和输入排列不改变请求/报告哈希。

`site_quality_reports` 仅保存追加式投影，并通过 `(org_id, site_page_version_id)` 复合外键绑定页面事实。数据库拒绝 update/delete/replace、跨租户页面、非法 JSON/哈希和原始正文。降级仅删除本任务表、索引和触发器。

## Given–When–Then

Given：

- `所有前置任务已完成`
- `TenantContext、trace_id 和 Idempotency-Key 可用`

When：

- `执行 SITE-004 的公开用例或内部命令`

Then：

- `实现断链、重定向、HTTP 状态、性能、alt、字幕和动态渲染检查。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/knowledge_site/test_site_quality.py tests/accessibility/test_site_004.py tests/integration/test_site_004_quality.py tests/integration/test_site_004_migration.py tests/contract/test_site_004_contract.py -q
```

Gate：`site_004_acceptance`

## 外部依赖

- 无

## 补充场景

- 输入 HTML、链接观测和动态快照顺序变化不改变检查排序或报告哈希。
- 重定向环、相对/绝对 URL 指向同一资源、带 fragment 链接和重复媒体引用均有确定性结果。
- 装饰图允许空 alt；缺失 alt 与 `alt=""` 的非装饰图都失败。
- 页面没有音视频时字幕检查通过；存在任一音视频时逐项要求 captions track。
- Port 抛出的异常只留下稳定错误码，不把异常正文或凭证写入证据。
- 跨租户 PageVersion、前置工件、链接观测或阈值快照统一拒绝。

## 回滚

- 停止新质量审计，导出报告哈希、检查码、指标和审计引用；原始 HTML/DOM 不在持久层，无需导出。
- 降级到 `20260920_geo_region_002`，仅移除 `site_quality_reports`、相关索引与触发器；SitePageVersion、SitePublication、Region 决策和其他历史事实保留。
