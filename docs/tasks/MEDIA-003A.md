# MEDIA-003A — 实现单语和多语言字幕，保存时间轴、文本版本和可访问性字段。

状态：`done`  
阶段：6（Media 和 Asset）  
Owner：`team/media`  
优先级：`high` / `P1`

## 目标

实现单语和多语言字幕，保存时间轴、文本版本和可访问性字段。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `PROD-002`
- `MEDIA-001`
- `MEDIA-002`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `MEDIA-003A.implementation`
- `MEDIA-003A.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/media-subtitle.schema.json`
- `packages/contracts/jsonschema/media-subtitle-version.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260920_media_003a.py`
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

- `执行 MEDIA-003A 的公开用例或内部命令`

Then：

- `实现单语和多语言字幕，保存时间轴、文本版本和可访问性字段。`
- `输出契约、审计事件和指定测试结果可复现`

## 实现规格

### 输入锁定与职责边界

`MediaSubtitleService.create_subtitle` 只接受调用方明确指定的同租户 `MediaScriptVersion`，可选地锁定同脚本的 `MediaStoryboardVersion`。脚本必须仍可用、三段时间线连续覆盖整个时长；StoryboardVersion 若提供，租户、脚本版本、时长和 snapshot hash 必须逐项匹配。服务只校验调用方提供的字幕文本和时间轴，不翻译、不调用模型、网络、渲染器或平台。

一次命令至少保存一个语言 track；多个 track 可以在同一版本中保存，locale 必须唯一且有一个 default track。每个 track 明确 `kind=caption|subtitle`、文字方向、文本版本和可访问性 profile。字幕文本是调用方的事实输入，服务不从其他 locale 推导文本。

### 时间轴、文本和可访问性

每个 cue 必须绑定一个脚本 segment sequence，`0 <= start_ms < end_ms <= duration_ms`，最短 250ms，同一 track 内按时间无重叠；cue sequence 从 1 连续。输入 cues 或 tracks 重新排序后，规范化输出和 snapshot hash 不变。文本必须非空、无控制字符，单 cue 不超过 500 个字符；可选 speaker label、sound description、forced flag 和位置/对齐字段均为封闭枚举。

`accessibility` 必须保存 `captions_complete`、`speaker_labels_complete`、`sound_descriptions_complete`、`reading_order`、`max_lines` 和 `max_chars_per_line`。`kind=caption` 的 track 必须声明 `captions_complete=true`；启用 speaker/sound description 声明时，相关 cue 必须提供对应字段。缺字段、越界、重叠、语言重复或不可访问声明确定性拒绝。

### 不可变版本、幂等和审计

同一租户、脚本版本和 storyboard 锁定组合只有一个 subtitle root；同 namespace/idempotency key 与 payload hash 重放首次结果，冲突返回 `IDEMPOTENCY_KEY_REUSED`。`revise_subtitle` 要求完整 tracks 和 `expected_version_no`，成功追加 `version_no+1`，旧版本和 cue 投影不回写。snapshot hash 排除 actor、trace 和隐式时钟；审计只记录输入/输出哈希、来源版本、Policy 快照、稳定错误码、耗时和成本，不保存凭证、供应商响应或二进制。

## 验证

```text
python -m pytest tests/unit/media/test_media_subtitle_service.py tests/integration/test_media_003a.py tests/integration/test_media_003a_migration.py tests/contract/test_media_003a_contract.py -q
```

Gate：`media_003a_acceptance`

## 外部依赖

- 无

## 完成门槛

- 服务、两个契约、四张 MEDIA-003A 迁移表和测试均已存在并由实际测试覆盖。
- 升级/降级只影响字幕 root/version/track/cue/command 表，保留 MEDIA-002、MediaScript、Variant、Claim 和 Rights 前置事实。
- 不允许把翻译生成、模型调用、渲染、平台上传、二进制音频或视频存储实现进本任务。

## 补充场景

- 单语英文、CJK 和 RTL locale 均能保存；同一版本可同时保存多个 locale，默认 track 唯一。
- cue 数组和 track 数组重排不改变规范化结果；跨 segment、重叠、空洞不被误当作有效 cue 时间轴。
- 修订只替换完整字幕版本；并发 `expected_version_no` 只有一个成功，历史版本逐字段可读。
- 字幕文本中出现 token、provider、model、raw output 等敏感键时拒绝并只写稳定错误码。

## 完成记录

- 实现：`modules/media/subtitle_service.py`、`modules/media/__init__.py`，支持单语/多语 track、locale 规范化、字幕/副字幕 kind、连续且不重叠 cue 时间轴、文本版本、可访问性 profile、幂等和并发修订。
- 迁移：`packages/db/migrations/versions/20260920_media_003a.py`，创建 subtitle root/version/track/cue/command 五类追加式投影，并安装来源、时间轴、敏感字段和租户边界。
- 契约：`media-subtitle.schema.json`、`media-subtitle-version.schema.json`。
- 测试：MEDIA-003A 专项 10 项通过；完整 Alembic 链升级、约束验证和降级通过。
- 证据：`docs/foundation/MEDIA-003A-EVIDENCE.yaml`。

## 回滚

- 停止新字幕创建和修订，导出 subtitle/version/track/cue 哈希与审计引用。
- 降级到 `20260920_media_002`，只删除 MEDIA-003A 表、索引和触发器；保留 storyboard、脚本、Variant、Claim 和 Rights 历史事实。
