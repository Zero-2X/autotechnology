# PROD-002 — 实现 `ContentVariant` 和 `VariantVersion`，字段包含 locale、market、audience、tone、disclosure 和来源版本。

状态：`done`  
阶段：4（Production、Localization、QA、Policy 和 Approval）  
Owner：`team/production`  
优先级：`critical` / `P0`

## 目标

实现 `ContentVariant` 和 `VariantVersion`，字段包含 locale、market、audience、tone、disclosure 和来源版本。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GEO_REGION-CORE-001`
- `CANON-002`
- `PROD-001`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `PROD-002.implementation`
- `PROD-002.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/content-variant.schema.json`
- `packages/contracts/jsonschema/variant-version.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_prod_002.py`
## 实现规格

- `VariantStore.save_draft` 接收 `PROD-001` 的已校验草稿，按只读 Canonical Version Port 核验来源版本、内容哈希、租户与撤回状态；按只读 Region Version Port 核验区域版本同租户、有效、支持 locale 与 market。
- 在 `content_variants` 中以 `(org_id, canonical_content_id, locale, market, audience)` 唯一定位稳定根；首次创建 root，之后用 expected version 追加 `variant_versions` 并更新当前指针，不覆盖历史版本。
- `VariantVersion` 保存来源 Canonical 版本、地区版本、tone、disclosure、term memory 状态、正文块与 snapshot hash。M1 的 `rule_copy` 草稿保持 `draft`，不冒充已本地化或已批准。
- 本阶段未建立术语记忆库时，`term_memory_version` 明确记录为 `pending`；披露缺失用 `null` 表示，后续 QA/Policy 任务负责判断是否允许进入更高状态。
- `variant_versions`、命令和事件为追加式；同租户同幂等键同请求重放首个响应，参数不同拒绝。跨租户根、来源或 Region 投影必须拒绝。
- 提供租户范围的 get/list_versions 与按 Canonical 版本读取的只读 lineage Port，供 `CANON-006` 后续接入。不得修改 Canonical 或 Region 事实。

补充场景：

- Given 合法规则草稿与 Region 版本，When 保存，Then 创建根和 v1，正文块、来源版本、披露和地区字段符合契约。
- Given 同一稳定根有新草稿，When expected version 匹配，Then 追加 v2，v1 不可更新或删除；expected version 不匹配拒绝。
- Given 相同幂等键和参数，When 重放，Then 只返回首次结果；不同参数拒绝。
- Given 来源或地区版本属于其他租户，或 locale 不被允许，When 保存，Then 拒绝且不写入 Variant 事实。
- Given 已存储版本，When 通过 lineage Port 查询，Then 仅返回同租户指定 Canonical 版本的映射。

## 回滚

- 停止新建版本，保留根、历史版本、命令和审计事件；后续修订使用追加迁移，不改写已接受历史。
## 目录边界

拥有目录：

- `modules/production`

允许目录：

- `modules/production`
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

- `执行 PROD-002 的公开用例或内部命令`

Then：

- `实现 `ContentVariant` 和 `VariantVersion`，字段包含 locale、market、audience、tone、disclosure 和来源版本。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/production tests/integration --maxfail=1
```

Gate：`prod_002_acceptance`

## 外部依赖

- 无

## 开工前细化

已按稳定根、不可变版本、只读 Port 和失败路径实现；证据见 `PROD-002-EVIDENCE.yaml`。
