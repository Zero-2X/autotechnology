# media

## 职责

Scripts, storyboards, subtitles, rendering and asset references.

## 固定布局

- domain/：实体、值对象、状态机和纯规则。
- application/：公开用例、命令、事务边界和权限检查。
- ports/：外部接口抽象和 DTO。
- infrastructure/：本地实现、仓储和事件发布器。
- projections/：可重建的只读投影。

## 表

MEDIA-001 由 `20260920_media_001` 创建 `media_scripts`、`media_script_versions`、`media_script_claim_refs` 和 `media_script_commands`。脚本版本与 Claim 引用追加保存，脚本根只推进当前版本指针。

MEDIA-002 由 `20260920_media_002` 创建 `media_storyboards`、`media_storyboard_versions`、`media_storyboard_shots`、`media_storyboard_asset_refs` 和 `media_storyboard_commands`。`MediaStoryboardService` 只接受精确的同租户 MediaScriptVersion；镜头时间线必须连续覆盖脚本时长，素材引用只保存已批准 AssetVersion 的非敏感快照，并为每项引用绑定当前、适用且允许 derivative/commercial 的 RightsRecordVersion。版本、镜头、引用和命令均追加保存。

MEDIA-003A 由 `20260920_media_003a` 创建 `media_subtitles`、`media_subtitle_versions`、`media_subtitle_tracks`、`media_subtitle_cues` 和 `media_subtitle_commands`。`MediaSubtitleService` 只接受精确的 MediaScriptVersion（可选锁定同脚本 StoryboardVersion），保存单语或多语 locale track、cue 时间轴、文本版本和可访问性 profile；输入只做确定性校验，不翻译、不渲染、不保存音视频二进制。

MEDIA-003B 由 `20260920_media_003b` 创建 `media_visual_asset_sets`、`media_visual_asset_set_versions`、`media_visual_asset_items` 和 `media_visual_asset_commands`。`MediaVisualAssetSetService` 只保存 cover/thumbnail/keyframe 对已批准 AssetVersion 的非敏感引用；每项引用都绑定适用且当前的 RightsRecordVersion，并保留文件 snapshot hash 和 alt text。输出规格校验与渲染由后续任务负责。

## 公开接口

MEDIA-003C：`MediaOutputSpecService` 为指定视觉素材集合版本保存 9:16、1:1、16:9 输出规格，校验偶数尺寸、精确比例、帧率和音频参数。`create_output_spec` 和 `revise_output_spec` 使用不可变来源快照、幂等键和 expected version；本服务不执行渲染。迁移 `20260920_media_003c` 创建 output spec root/version/item/command 四张表。

MEDIA-004A：`MediaRenderService` 在同租户范围内锁定脚本、分镜、字幕、视觉素材集合和输出规格的具体版本及 snapshot hash，保存选定 profile、目标 AssetVersion 版本号和输入哈希。Worker 入口通过可替换 `RendererPort` 生成 bytes，再由私有 `StoragePort` 写入并用 `head/get` 核验 SHA-256、大小和 content type；任务仅保存 private object ref 与产物事实。`20260920_media_004a` 创建 render job、锁定输入、产物和命令四张追加式表，失败的外部结果进入 `unknown` 供 MEDIA-004B 处理。

MEDIA-004B：`MediaRenderRetryService` 记录脱敏的 deterministic/transient/unknown 失败事实，按有上限的指数退避创建同租户 retry schedule，并在到期时原子领取任务。达到上限进入 `dead_letter`，未知结果只创建 `unknown_result` 人工任务。`rerender_shot` 按 `(job, stage, shot_sequence, profile)` 稳定自然键重渲染；已确认的 private object 先执行 head/get 恢复并直接重放，不覆盖对象或再次调用 Renderer。`20260920_media_004b` 创建失败、schedule、命令和单镜头目标四张表，追加式事实与可审计状态推进由 SQLite/PostgreSQL 触发器保护。

MEDIA-005A：`MediaAssetQAService` 对 RenderJob 的 private artifacts 执行四组确定性检查：文件 `head/get` 的租户、private ref、SHA-256、大小和 content type；MediaProbePort 返回的容器、尺寸、比例、帧率、视频编码、像素格式、时长、音频编码/采样率/声道；锁定 SubtitleVersion 的 track/cue 顺序、边界和重叠；以及 profile 与输入哈希一致性。探针或存储暂时不可确认时报告 `needs_review`，确定性不匹配为 `failed`，报告只保存脱敏事实和哈希，不保存媒体字节。`20260920_media_005a` 创建 `media_qa_reports`、`media_qa_findings` 和 `media_qa_commands` 三张追加式表。

MEDIA-005B：`MediaContentRightsQAService` 对锁定来源与 OCR/转写投影比较数字、代码和版本 token，检查 AI/广告披露，并验证 AssetVersion 的 RightsRecordVersion 在状态、期限、地区、语言、媒体和用途上的覆盖。文本探针未知结果为 `needs_review`，确定性 token/披露/权利问题为 `failed`；报告和 content evaluation 只保存哈希、短 finding 和脱敏权利事实。`20260920_media_005b` 创建追加式 `media_qa_content_evaluations` 投影。

MEDIA-006：`MediaAssetLineageService` 为 AssetVersion 保存 Variant snapshot、Claim 快照和 RightsRecordVersion 快照，按 source type 追加 lineage edge；`check_lineage` 和 `propagate_dependency_change` 在 Variant/Claim/Rights 撤回、过期或范围变化时返回 blocked/withdrawn，并只推进当前状态投影。`20260920_media_006` 创建 lineage edge、decision、command 三类追加式表。

`MediaScriptService.create_script` 从调用方指定的 approved VariantVersion 生成确定性的 30/60/90 秒 hook/body/CTA；`edit_script` 只接受人工文本并追加新版本。`VariantVersionPort` 与 `ClaimPort` 可替换，默认实现不访问网络、模型或平台。

`MediaStoryboardService.create_storyboard` 和 `revise_storyboard` 只编排分镜、镜头和权利引用；不生成字幕、不渲染、不调用模型或平台。输入重排不改变 snapshot hash，`expected_version_no` 保护并发修订。

`MediaSubtitleService.create_subtitle` 和 `revise_subtitle` 对每个 track 检查 cue 不重叠、segment 来源、字幕/副字幕 kind、locale 唯一和可访问性字段；tracks/cues 重排不改变 snapshot hash，旧字幕版本与 cue 投影保持不可变。

`MediaVisualAssetSetService.create_asset_set` 和 `revise_asset_set` 检查角色、media type、时间点、Variant/Region/Policy lineage 和 Rights 范围；items 重排不改变 snapshot hash，旧视觉引用版本保持不可变，不执行关键帧生成或渲染。

## 事件

事件类型和 Schema 由 `packages/contracts/events/` 登记。

## 权限

所有租户业务调用必须经过 TenantContext 和授权检查。

## 公开边界

接口、事件和权限由对应任务卡与 JSON Schema 登记；本目录不得直接依赖其他模块的 infrastructure、FastAPI、ORM 或供应商 SDK。

## 禁止事项

不得保存 Token、完整 PII、模型原始输出或二进制；无账号阶段不得调用真实平台。脚本版本只保存经验证的文本、Claim 快照哈希和不可变来源字段。
