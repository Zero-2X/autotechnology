# MEDIA-003B — 实现封面、关键帧和视觉素材引用，记录每项素材的 RightsRecordVersion。

状态：`done`  
阶段：6（Media 和 Asset）  
Owner：`team/media`  
优先级：`high` / `P1`

## 目标

实现封面、关键帧和视觉素材引用，记录每项素材的 RightsRecordVersion。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `PROV-002`
- `PROD-002`
- `MEDIA-002`
- `MEDIA-003A`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `MEDIA-003B.implementation`
- `MEDIA-003B.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/asset-version.schema.json`
- `packages/contracts/jsonschema/rights-record-version.schema.json`
- `packages/contracts/jsonschema/media-visual-asset-set.schema.json`
- `packages/contracts/jsonschema/media-visual-asset-set-version.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260920_media_003b.py`
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

- `执行 MEDIA-003B 的公开用例或内部命令`

Then：

- `实现封面、关键帧和视觉素材引用，记录每项素材的 RightsRecordVersion。`
- `输出契约、审计事件和指定测试结果可复现`

## 实现规格

### 来源与职责边界

`MediaVisualAssetSetService.create_asset_set` 只接受同租户、状态为 `approved` 的 AssetVersion 引用，可选锁定同租户的 MediaStoryboardVersion。AssetVersion 必须与 storyboard 的 MediaScript/Variant/Region/Policy 快照精确一致，媒体类型只能为 `image|video|thumbnail`；服务只保存非敏感元数据和引用，不读取或保存二进制，不生成关键帧，不渲染，也不调用模型、网络或平台。MEDIA-003C 负责输出规格校验，MEDIA-004A 负责渲染任务。

集合至少包含一个 `cover` 或 `thumbnail`，每个 item 的 role 只能为 `cover|thumbnail|keyframe`；cover/thumbnail 不带时间，keyframe 必须在 storyboard/script 时长内且不重叠同一时间点。输入 item 数组、AssetVersion 列表和 RightsRecordVersion 列表重新排序后规范化结果和 snapshot hash 不变。

### Asset 与 Rights 门禁

每个 item 必须绑定准确的 AssetVersion id、media type、format、private storage ref（可空）和文件 snapshot hash。AssetVersion 必须属于当前 Variant/Region/Policy 且 `status=approved`；跨租户、withdrawn、planned 或缺文件 hash 确定性拒绝。每个 item 必须至少引用一个 RightsRecordVersion；Rights 必须同租户、`status=verified`、在 `valid_from <= at < valid_to` 内、`permitted_use` 为 `derivative|commercial`，并覆盖当前 market、locale 和 `image|video|thumbnail` media type。历史版本不随 Rights 后续撤回而回写。

### 不可变版本、幂等和审计

同一 storyboard version（或明确的 script version）只有一个 asset-set root；同 namespace/idempotency key 与 payload hash 重放首次结果，冲突返回 `IDEMPOTENCY_KEY_REUSED`。`revise_asset_set` 要求完整 item 列表和 `expected_version_no`，成功追加 `version_no+1`；旧版本和 item 引用保持不可变。snapshot hash 排除 actor、trace 和隐式时钟；审计只记录来源版本、Policy 快照、输入/输出哈希、稳定错误码、耗时和成本。

## 验证

```text
python -m pytest tests/unit/media/test_media_visual_asset_service.py tests/integration/test_media_003b.py tests/integration/test_media_003b_migration.py tests/contract/test_media_003b_contract.py -q
```

Gate：`media_003b_acceptance`

## 外部依赖

- 无

## 完成门槛

- 服务、两个集合契约、四张 MEDIA-003B 迁移表和专项测试均已存在并由实际测试覆盖。
- 升级/降级只影响 visual asset-set root/version/item/command 表，保留 MEDIA-003A、MEDIA-002、MediaScript、Variant、Claim 和 Rights 前置事实。
- 不允许把输出规格校验、渲染、关键帧生成、平台上传或二进制存储实现进本任务。

## 补充场景

- 同一 storyboard version 的 cover、thumbnail 和多个时间点 keyframe 可在一个版本中共存；至少一个 cover/thumbnail，角色不能重复同一 AssetVersion。
- AssetVersion/rights/item 数组重排不改变 snapshot hash；keyframe 越界、AssetVersion lineage 不一致、Rights 过期或范围不匹配确定性拒绝。
- 并发修订只允许一个 expected version 推进 current pointer，失败只写稳定错误码和哈希。

## 完成记录

- 实现：`modules/media/visual_asset_service.py`、`modules/media/__init__.py`，提供 cover/thumbnail/keyframe 的 AssetVersion 与 RightsRecordVersion 门禁、确定性规范化、幂等和不可变修订。
- 迁移：`packages/db/migrations/versions/20260920_media_003b.py`，创建 visual asset-set root/version/item/command 四类追加式投影，并安装来源、Rights、敏感字段和租户边界。
- 契约：`media-visual-asset-set.schema.json`、`media-visual-asset-set-version.schema.json`。
- 测试：MEDIA-003B 专项 8 项通过；完整 Alembic 链升级、约束验证和降级通过。
- 证据：`docs/foundation/MEDIA-003B-EVIDENCE.yaml`。

## 回滚

- 停止新的 visual asset-set 创建和修订，导出 root/version/item、Rights 引用、snapshot hash 与审计引用。
- 降级到 `20260920_media_003a`，只删除 MEDIA-003B 表、索引和触发器；保留字幕、storyboard、脚本、Variant、Claim 和 Rights 历史事实。
