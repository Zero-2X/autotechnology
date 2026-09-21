# MEDIA-003C — 实现 9:16、1:1、16:9 输出规格校验，不在本任务执行渲染。

状态：`done`  
阶段：6（Media 和 Asset）  
Owner：`team/media`  
优先级：`high` / `P1`

## 目标

实现 9:16、1:1、16:9 输出规格校验，不在本任务执行渲染。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `PROD-002`
- `MEDIA-001`
- `MEDIA-003B`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `MEDIA-003C.implementation`
- `MEDIA-003C.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/asset-version.schema.json`
- `packages/contracts/jsonschema/media-visual-asset-set-version.schema.json`
- `packages/contracts/jsonschema/media-output-spec.schema.json`
- `packages/contracts/jsonschema/media-output-spec-version.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260920_media_003c.py`
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

- `执行 MEDIA-003C 的公开用例或内部命令`

Then：

- `实现 9:16、1:1、16:9 输出规格校验，不在本任务执行渲染。`
- `输出契约、审计事件和指定测试结果可复现`

## 实现规格

`MediaOutputSpecService` 负责把一个精确的 `MediaVisualAssetSetVersion` 锁定为一个可审阅的输出规格版本。它只做确定性输入校验和追加式版本记录，不渲染、不读取或保存二进制、不生成关键帧、不调用模型、网络、平台或编码器。

### 输入与 lineage

- `visual_asset_set_version` 必须是同租户、状态不是 `withdrawn|superseded` 的 `MediaVisualAssetSetVersion`；可通过 `MediaVisualAssetVersionPort` 按精确 id 查询，禁止用“当前版本”隐式替换调用方的 id。
- 视觉版本的 `media_script_version_id`、`duration_seconds`、`region_profile_version_id`、`policy_snapshot_id` 和 `snapshot_hash` 原样锁入输出规格；若传入 `script_version`，必须同租户、id 和 `snapshot_hash` 完全一致，且脚本状态可用。
- 可选 `storyboard_version` 必须与视觉版本和脚本的 id、时长、Region、Policy 快照一致。所有输入只保留版本 id、快照哈希和非敏感规格字段。

### 规格集合与三种比例

- 一个规格版本包含 1 至 3 个唯一 profile；每个 profile 的 `aspect_ratio` 只能是 `9:16`、`1:1` 或 `16:9`，同一版本不得重复比例。
- `width`、`height` 为正偶数且不超过 7680；宽高约分后的比例必须与 `aspect_ratio` 精确一致。未提供尺寸时分别采用 `1080x1920`、`1080x1080`、`1920x1080` 的确定性默认值。
- `frame_rate` 为 1–120 的有限数（最多三位小数）；`container_format`、`video_codec`、`pixel_format`、`audio_codec`、`audio_sample_rate_hz`、`audio_channels` 只能取契约中的白名单。字幕 track id 只保存 UUID 引用，不复制字幕文本。
- profile 的 `profile_key` 在一个版本中唯一；输入数组可以任意重排，服务按 `aspect_ratio`、`profile_key` 规范化后计算 `snapshot_hash`。可选 `require_all_ratios` 仅在调用方明确要求时开启，默认允许单一比例草稿。

### 版本、权限、幂等和失败

- 同一租户和同一视觉 AssetSetVersion 只有一个 output-spec root；首次创建为 `version_no=1`，修订必须提供 `expected_version_no` 和非空 `revision_reason`，只追加新版本，旧版本和 profile projection 不变。
- 写命令使用命名空间和 `Idempotency-Key`；相同 key 与请求哈希重放首次结果，哈希不同返回 `IDEMPOTENCY_KEY_REUSED`。跨租户、来源版本不一致、比例/尺寸/白名单无效均返回稳定错误码并写安全审计记录。
- 审计只包含 org、actor、trace、输入/输出版本 id、Policy 快照、请求/快照哈希、稳定错误码、耗时和成本；禁止写入模型、供应商、凭证、Token、原始响应和二进制。

### 数据库投影

`20260920_media_003c.py` 只创建 `media_output_specs`、`media_output_spec_versions`、`media_output_spec_items`、`media_output_spec_commands`。版本、profile 和 command 表安装追加式保护；来源、租户、哈希、比例、尺寸、敏感字段和幂等引用由 SQLite/PostgreSQL guard 校验。降级只删除这四张表及其触发器/函数。

## Given–When–Then

### 场景 1：三种比例的合法草稿

Given：同租户且可用的视觉 AssetSetVersion 和有效 TenantContext。  
When：提交 `9:16`、`1:1`、`16:9` 三个 profile。  
Then：创建一个 `version_no=1` 的 closed-contract 版本，比例、尺寸、来源快照和 profile_count 可复现。

### 场景 2：尺寸和比例确定性拒绝

Given：其它 lineage 输入均有效。  
When：提交约分比例不等于声明比例、奇数尺寸或超出 7680 的尺寸。  
Then：返回 `OUTPUT_DIMENSIONS_INVALID`，不写成功版本，不调用任何渲染或外部接口。

### 场景 3：来源版本锁定

Given：视觉版本属于租户 A。  
When：使用租户 B、withdrawn/superseded 或哈希不一致的来源。  
Then：返回 `TENANT_SCOPE_VIOLATION`、`VISUAL_ASSET_VERSION_NOT_USABLE` 或 `SOURCE_SNAPSHOT_MISMATCH`。

### 场景 4：重排、幂等和修订

Given：一个合法规格集合。  
When：重排 profile 后重放同一 key，再以 `expected_version_no` 修订。  
Then：规范化哈希不变；同哈希重放原结果；不同 payload 返回 `IDEMPOTENCY_KEY_REUSED`；成功修订追加下一个版本，旧版本保持不变。

### 场景 5：白名单和敏感输入

Given：来源和租户有效。  
When：提交未知 codec、采样率、字幕 id 格式或嵌入 `model/provider/token/raw_output`。  
Then：返回稳定校验错误或 `SENSITIVE_INPUT_REJECTED`，审计中不出现原始敏感值。

### 场景 6：迁移升级和回滚

Given：完整 Alembic 链已升级到 `20260920_media_003c`。  
When：插入合法投影、尝试修改追加表，再降级到 `20260920_media_003b`。  
Then：修改被 guard 拒绝，C 的四张表消失，003B 及其之前的表仍存在。

## 补充场景

- profile 数组按任意顺序输入，输出固定按比例和 profile_key 排序；`require_all_ratios=true` 时缺失任一比例返回 `OUTPUT_RATIO_SET_INCOMPLETE`。
- 相同视觉版本不得创建第二个 root；不同视觉版本可以独立创建规格，跨租户读取和修订始终拒绝。
- `frame_rate`、音频字段和字幕引用只做规格与引用校验，不能触发媒体探测、转码、渲染或平台上传。

## 验证

```text
python -m pytest tests/unit/media/test_media_output_spec_service.py tests/integration/test_media_003c.py tests/integration/test_media_003c_migration.py tests/contract/test_media_003c_contract.py -q
```

Gate：`media_003c_acceptance`

## 外部依赖

- 无

## 回滚

- 停止新的 output-spec 创建、修订和下游读取，导出 root/version/profile projection、来源快照哈希和审计引用。
- 将迁移降级到 `20260920_media_003b`，只删除 MEDIA-003C 四张表、索引和 guard；保留视觉素材、字幕、storyboard、脚本、Variant、Claim 和 Rights 历史事实。

## 开工前细化

本卡已完成实现与验收：专项 13 项通过，全量 955 项通过。SQLite 完整迁移链升级、反例约束和降级均实际执行；PostgreSQL 验证限于离线 SQL 生成和 guard 删除顺序，未声明实机验收。证据见 `docs/foundation/MEDIA-003C-EVIDENCE.yaml`。
