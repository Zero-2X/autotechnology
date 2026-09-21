# MEDIA-005B — 实现数字、代码、版本、AI 标识和素材权利 QA。

状态：`done`  
阶段：6（Media 和 Asset）  
Owner：`team/media`  
优先级：`high` / `P1`

## 目标

实现数字、代码、版本、AI 标识和素材权利 QA。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `PROV-002`
- `PROD-002`
- `QA-001`
- `MEDIA-005A`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `MEDIA-005B.implementation`
- `MEDIA-005B.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/qa-report.schema.json`
- `packages/contracts/jsonschema/asset-version.schema.json`
- `packages/contracts/jsonschema/render-job.schema.json`

迁移：

- `packages/db/migrations/versions/20260920_media_005b.py`
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

- `MediaContentRightsQAService.run_content_qa` 接收同租户 AssetVersion/RenderJob 投影、脚本/字幕或脱敏 OCR/转写文本、Variant/Claim/Evidence/ RightsRecordVersion 快照、TenantContext、trace_id 和幂等键

Then：

- `数字检查逐 token 比较锁定来源文本与 OCR/转写文本；代码检查 fenced/inline code 的内容与顺序；版本检查版本号和版本字符串不得缺失或改写`
- `AI 生成素材必须包含可配置的 AI/人工智能披露；广告素材按 Policy 要求披露；缺失或不一致为 failed，脱敏文本探针不可用为 needs_review`
- `RightsRecordVersion 必须同租户、verified/current、在有效期内、覆盖 market/locale/media/permitted_use，并覆盖 AssetVersion 的 rights_snapshot_ids；权利撤回/过期/地域不符为 failed`
- `报告 findings 按 check、code、path、object_id 稳定排序；只保存文本/权利哈希和短的脱敏观察值，不保存原始媒体、Token 或供应商响应`
- `同租户同幂等键相同 payload 重放；payload 不同返回 IDEMPOTENCY_KEY_REUSED；expected_version、跨租户访问和敏感字段在写入前拒绝`

## 实现规格

- `MediaContentRightsQAService`（别名 `MediaAssetContentQAService`、`MediaRightsQAService`）通过 `TextExtractionPort` 获取固定 OCR/转写投影，通过 `RightsPort` 获取可替换权利检查；默认 Fake 实现只读离线输入。
- 数字 token 支持小数、百分比、带单位和带逗号数字；代码块按 fenced/inline token 保持精确字符串；版本号支持 `v1.2.3`、语义化版本和常见产品/协议版本前缀。
- 权利检查使用 `valid_from/valid_to`、`permitted_regions`、`permitted_locales`、`permitted_media`、`permitted_use` 和 `status`，并记录 policy/rights snapshot hash。
- 迁移 `20260920_media_005b` 新增 `media_qa_content_evaluations` 追加式投影，与 `media_qa_reports` 使用同租户复合外键；SQLite/PostgreSQL 触发器阻止更新、删除、跨租户引用和敏感原始文本。

## 补充场景

1. OCR/转写只改变数字或代码 token：报告 `failed`，分别输出 `MEDIA_NUMBER_MISMATCH`、`MEDIA_CODE_MISMATCH`。
2. AI 生成标记为 true 但披露为空，或广告 Policy 要求的 disclosure 缺失：报告 `failed`。
3. RightsRecordVersion 过期、withdrawn、地区/语言/媒体/用途不允许，或未覆盖 AssetVersion rights_snapshot_ids：报告 `failed`。
4. 文本探针返回未知/临时错误：报告 `needs_review`，不得把未知文本当作通过。
5. 另一租户的 Variant、Claim、Evidence 或 RightsRecordVersion：返回 `TENANT_SCOPE_VIOLATION`，不创建报告。

## 回滚

- downgrade 只移除 MEDIA-005B 的 content evaluation 表和触发器，保留 MEDIA-005A 报告、finding、command 及 RenderJob/AssetVersion 事实。

## 验证

```text
python -m pytest tests/unit/media tests/integration --maxfail=1
```

Gate：`media_005b_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
