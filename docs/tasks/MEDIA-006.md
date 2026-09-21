# MEDIA-006 — 实现 AssetVersion 与 Variant、Claim、RightsRecordVersion 的 lineage。

状态：`done`  
阶段：6（Media 和 Asset）  
Owner：`team/media`  
优先级：`high` / `P1`

## 目标

实现 AssetVersion 与 Variant、Claim、RightsRecordVersion 的 lineage。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `CANON-006`
- `PROD-002`
- `MEDIA-005B`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `MEDIA-006.implementation`
- `MEDIA-006.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/asset-version.schema.json`
- `packages/contracts/jsonschema/media-asset-lineage.schema.json`

迁移：

- `packages/db/migrations/versions/20260920_media_006.py`
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

- `MediaAssetLineageService.create_asset_version` 接收同租户 AssetVersion、已批准 VariantVersion、Claims、RightsRecordVersions 和 TenantContext

Then：

- `AssetVersion 保存 Variant snapshot hash、Claim id/hash 和 RightsRecordVersion id/hash；lineage edges 追加写入并按 source type 稳定排序`
- `Variant 必须 approved；Claim 必须 verified/fresh 且适用当前 Canonical/Variant；RightsRecordVersion 必须 verified/current、未过期并覆盖地区、语言、媒体和用途`
- `check_lineage` 在依赖撤回/过期后返回 blocked 或 withdrawn；`propagate_dependency_change` 只更新当前投影状态，不改写历史边和历史 AssetVersion`
- `同租户同幂等键按 payload hash 重放；expected_version、跨租户依赖和快照不一致在写入前拒绝；成功/拒绝记录 audit/outbox envelope`

## 实现规格

- `MediaAssetLineageService`（别名 `AssetLineageService`、`MediaAssetVersionService`）只依赖投影对象和内存 Store，不导入 ORM、FastAPI、供应商 SDK 或网络客户端。
- AssetVersion schema 的 lineage 字段为可选扩展，保持旧版本读取兼容；新增 `lineage_status`、`lineage_checked_at` 只作为当前状态投影，边和决策表是追加式事实。
- 迁移 `20260920_media_006` 新增 `media_asset_lineage_edges`、`media_asset_lineage_checks`、`media_asset_lineage_commands`，以 source_org_id 复合租户门禁、SHA-256/关系类型检查和 SQLite/PostgreSQL append-only 触发器保护。

## 补充场景

1. Variant snapshot hash 变化、Variant withdrawn 或未 approved：决策为 `blocked`，不覆盖原 AssetVersion。
2. Claim stale/withdrawn/不适用，或 Claim snapshot hash 变化：决策为 `blocked`，输出对应原因。
3. RightsRecordVersion 过期、撤回、地域/语言/媒体/用途不符或 hash 变化：决策为 `withdrawn`，输出 `asset.withdrawn` 事件。
4. source_org_id 与 org_id 不同或依赖投影属于另一租户：返回 `TENANT_SCOPE_VIOLATION`，不写边、决策或命令。
5. 同一 AssetVersion 同一 lineage source 重复提交：按自然键重放或返回 `ASSET_VERSION_IMMUTABLE`，禁止覆盖历史边。

## 回滚

- downgrade 只移除 MEDIA-006 的三张 lineage 表、索引和触发器，保留 MEDIA-005B 的 QA 报告/内容证据及既有资产投影。

## 验证

```text
python -m pytest tests/unit/media tests/integration --maxfail=1
```

Gate：`media_006_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
