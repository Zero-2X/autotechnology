# MEDIA-004A — 实现渲染任务创建、输入版本锁定和中间产物保存。

状态：`done`  
阶段：6（Media 和 Asset）  
Owner：`team/media`  
优先级：`high` / `P1`

## 目标

实现渲染任务创建、输入版本锁定和中间产物保存。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `PROD-002`
- `MEDIA-001`
- `MEDIA-002`
- `MEDIA-003A`
- `MEDIA-003B`
- `MEDIA-003C`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `MEDIA-004A.implementation`
- `MEDIA-004A.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/render-job.schema.json`
- `packages/contracts/jsonschema/asset-version.schema.json` (锁定目标 AssetVersion 的版本与文件哈希)

迁移计划：

- `packages/db/migrations/versions/20260920_media_004a.py`
## 目录边界

拥有目录：

- `modules/media`

允许目录：

- `modules/media`
- `apps/worker`
- `adapters/fake`
- `tests/accessibility`
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

## Given–When–Then

Given：

- `所有前置任务已完成`
- `TenantContext、trace_id 和 Idempotency-Key 可用`

When：

- `执行 MEDIA-004A 的公开用例或内部命令`

Then：

- `实现渲染任务创建、输入版本锁定和中间产物保存。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/media tests/integration --maxfail=1
```

Gate：`media_004a_acceptance`

## 外部依赖

- 无

## 开工前细化

MEDIA-003C 已完成。契约、迁移和开工门禁已落地，进入实现与回归验证。

## 实现规格

创建任务时必须显式选择同租户的 MediaScriptVersion、MediaStoryboardVersion、MediaSubtitleVersion、MediaVisualAssetSetVersion 和 MediaOutputSpecVersion。保存各版本 id、snapshot hash、Policy/Region 引用及选中的输出 profile_key；逐项核对脚本、分镜、视觉集合和输出规格的来源链。禁止在执行时以各对象的 current pointer 替换已锁定版本。

每个 render job 对应一个选定的输出 profile，记录目标 AssetVersion id、输入哈希和 expected version。相同租户、幂等键与规范化输入返回同一任务；不同输入返回确定性冲突。任务创建和状态变化需有安全审计及 Outbox 记录。状态最少覆盖 planned、running、succeeded、failed，运行入口接入现有 Worker handler；重试调度、单镜头重渲染和死信属于 MEDIA-004B。

中间产物通过可替换 RendererPort 和私有 StoragePort 保存；无账号验收使用 FakeRenderer 与现有 FakeStorage。保存 bytes 的职责位于存储适配器，业务任务只保存 private object ref、文件 SHA-256、大小、content type、stage/shot 标识、输入哈希和产物序号。不得以接受任意 URL 的方式绕过存储验证。成功确认须通过 head/get 核验存储对象与登记哈希；跨租户对象拒绝。

中间产物的自然键为 org/job/stage/shot/output profile，同键同哈希重放首次结果，同键异哈希拒绝覆盖。若存储已写成功而确认失败，恢复时按稳定对象键核验并登记已有对象；结果未知时保留未知状态供 MEDIA-004B 处理，禁止再次触发未经确认的外部操作。

## 补充场景

1. 正常路径：五类版本来源一致且 profile 存在，创建 planned 任务，经 Worker 与 FakeRenderer 执行后可读取经过哈希核验的私有中间产物。
2. 租户隔离：任一输入版本或存储对象属于其他租户，拒绝并记录稳定错误码，任务及产物不写成功状态。
3. 版本锁定：来源 id/hash、Policy、Region 或 profile 不一致时拒绝；创建后来源 current pointer 改变不改变任务输入。
4. 幂等并发：重放创建或产物确认返回原结果；不同 payload 或落后的 expected version 拒绝，不重复生成已确认产物。
5. 部分失败：存储失败、存储成功后登记失败和未知 Renderer 结果分别可重现；恢复不会覆盖已确认的私有文件。
6. 迁移回滚：完整链升级后验证租户复合引用及追加式输入/产物事实，降级只移除本任务表并保留 MEDIA-003C 及之前的数据。

## 回滚

停止分派新的 render job，导出锁定输入、产物引用、状态和审计。先停用 Worker handler，再按迁移依赖降级本任务；私有对象按保存策略保留，不在数据库降级中删除文件。

## 当前实现

- `modules/media/render_service.py`：`MediaRenderService`、`FakeRenderer`、可替换 `RendererPort`/`StoragePort`、输入版本 Port、幂等创建、Worker handler、私有对象 head/get 确认、稳定失败状态和审计。
- `packages/contracts/jsonschema/render-job.schema.json`：关闭式 render job、profile 快照、输入版本哈希、AssetVersion 版本号和中间产物字段。
- `packages/db/migrations/versions/20260920_media_004a.py`：render job、锁定输入、产物事实和命令表；SQLite/PostgreSQL 租户复合引用、哈希、private ref、追加式触发器与回滚。

## 验证记录

- 专项单元、Worker、迁移和契约测试已加入 `tests/unit/media/test_media_render_service.py`、`tests/integration/test_media_004a.py`、`tests/integration/test_media_004a_migration.py`、`tests/contract/test_media_004a_contract.py` 和 `tests/contract/test_media_004a_postgres_sql.py`。
- 最终全量回归和静态门禁已通过，开发清单已勾选；后续任务为 MEDIA-004B。
