# MEDIA-002 — 实现分镜、镜头时长、素材、音乐、字体、配音和授权记录。

状态：`done`  
阶段：6（Media 和 Asset）  
Owner：`team/media`  
优先级：`high` / `P1`

## 目标

实现分镜、镜头时长、素材、音乐、字体、配音和授权记录。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `PROV-002`
- `PROD-002`
- `MEDIA-001`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `MEDIA-002.implementation`
- `MEDIA-002.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/asset-version.schema.json`
- `packages/contracts/jsonschema/rights-record-version.schema.json`
- `packages/contracts/jsonschema/media-storyboard.schema.json`
- `packages/contracts/jsonschema/media-storyboard-version.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260920_media_002.py`
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

- `执行 MEDIA-002 的公开用例或内部命令`

Then：

- `实现分镜、镜头时长、素材、音乐、字体、配音和授权记录。`
- `输出契约、审计事件和指定测试结果可复现`

## 实现规格

### 输入锁定与职责边界

`MediaStoryboardService.create_storyboard` 只接受调用方明确指定的同租户 `MediaScriptVersion`。脚本版本必须来自 MEDIA-001，且其三段时间线连续覆盖 `0..duration_seconds*1000`；服务不重算脚本文本、不生成字幕、不渲染、不调用模型或平台。MEDIA-003A 负责字幕，MEDIA-004A 负责渲染任务。

每个镜头必须绑定一个脚本 segment sequence、连续的 `start_ms/end_ms` 和非空 shot purpose。镜头按 sequence 排序后必须无重叠、无空洞、覆盖脚本时长；最短镜头 500ms，镜头总时长必须等于脚本时长。输入数组重排不改变 snapshot hash。

### 素材、音乐、字体和配音引用

镜头只保存已批准 `AssetVersion` 的引用和非敏感元数据，不保存二进制、Token、供应商原始响应或完整配音音频。引用 role 只能是 `visual|music|font|voiceover`；`asset_version_id`、media type、format、可选 private storage ref 和 variant/region/policy 快照必须精确绑定当前租户。每个引用都必须有至少一个 RightsRecordVersion 引用；没有素材时可创建纯文本分镜，但任何已声明素材必须通过权利门禁。

RightsRecordVersion 必须同租户、`status=verified`、在 `valid_from <= at < valid_to`（空边界表示不限制），且 `permitted_use` 至少为 `derivative` 或 `commercial`。非空 permitted regions/locales/media 必须覆盖当前 Variant 的 market/locale 和引用 media type；`snapshot_hash`、source snapshot ids 和 policy rule version 必须有效。撤回、过期、complaint hold 或范围不匹配确定性拒绝；历史 StoryboardVersion 不被回写。

### 不可变版本、幂等和审计

同一 `MediaScriptVersion` 只有一个 storyboard root；重复创建返回 `STORYBOARD_ALREADY_EXISTS`，同租户同 namespace/idempotency key 与 payload hash 重放首次结果，冲突返回 `IDEMPOTENCY_KEY_REUSED`。root 的脚本版本、租户和时长不可变；版本、镜头和素材/权利引用追加保存，`expected_version_no` 用于乐观并发修订。

`revise_storyboard` 只接受完整的新 shot plan 和引用集合，成功追加 `version_no+1`；旧版本、镜头时间、AssetVersion 与 RightsRecordVersion 引用保持不变。snapshot hash 排除 actor、trace 和隐式时钟；审计只写输入/输出哈希、脚本版本、Policy 快照、稳定错误码、耗时和成本，不保存原始媒体或凭证。

## 验证

```text
python -m pytest tests/unit/media tests/integration/test_media_002.py tests/integration/test_media_002_migration.py tests/contract/test_media_002_contract.py -q
```

Gate：`media_002_acceptance`

## 外部依赖

- 无

## 完成门槛

- 服务、契约和迁移均已存在且由实际测试覆盖。
- 迁移升级/降级只影响 MEDIA-002 表，保留 MEDIA-001、Variant、Claim、Rights 和 Site 前置事实。
- 不允许把字幕、渲染、平台上传或二进制存储实现进本任务。

## 完成记录

- 实现：`modules/media/storyboard_service.py`、`modules/media/__init__.py`，提供同租户 MediaScriptVersion 锁定、连续镜头计划、AssetVersion/RightsRecordVersion 门禁、纯文本分镜、不可变修订、幂等和有界审计。
- 迁移：`packages/db/migrations/versions/20260920_media_002.py`，创建 storyboard root/version/shot/asset-ref/command 五类投影，并安装租户、来源、Rights、追加式和敏感字段边界。
- 契约：`media-storyboard.schema.json`、`media-storyboard-version.schema.json`。
- 测试：MEDIA-002 专项 18 项通过；完整 Alembic 链升级、约束验证和降级通过。
- 证据：`docs/foundation/MEDIA-002-EVIDENCE.yaml`。

## 补充场景

- 30、60、90 秒脚本都必须由连续镜头完整覆盖；镜头数组、素材数组和权利数组重新排序后 snapshot hash 保持一致。
- 纯文本分镜可以没有素材；一旦声明素材，visual/music/font/voiceover 的 media type、Variant/Region/Policy 快照和 RightsRecordVersion 范围必须逐项匹配。
- RightsRecordVersion 在创建后过期、撤回、进入 complaint hold 或失去市场/locale/media 覆盖时，新的创建和修订失败，历史 StoryboardVersion 不回写。
- 同一 expected version 的并发修订只允许一个推进 current pointer；失败只记录稳定错误码、哈希和 trace。

## 回滚

- 停止新的 storyboard 创建和修订，导出 storyboard/version、镜头、素材/权利引用、snapshot hash 与审计引用。
- 降级到 `20260920_media_001`，只删除 MEDIA-002 表、索引和触发器；保留 MEDIA-001、Variant、Claim、Rights 和 Site 前置事实。
