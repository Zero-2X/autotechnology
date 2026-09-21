# PROD-004 — 实现 `GEO_REGION` 前置规则：语言、单位、货币、时区、法规、披露和市场限制。

状态：`done`  
阶段：4（Production、Localization、QA、Policy 和 Approval）  
Owner：`team/production`  
优先级：`critical` / `P0`

## 目标

实现 `GEO_REGION` 前置规则：语言、单位、货币、时区、法规、披露和市场限制。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GEO_REGION-CORE-001`
- `CANON-002`
- `PROD-002`
- `PROD-003`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `PROD-004.implementation`
- `PROD-004.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/variant-version.schema.json`
- `packages/contracts/jsonschema/region-profile-version.schema.json`
- `packages/contracts/jsonschema/region-rule-decision.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_prod_004.py`
## 实现规格

- `RegionRuleService.evaluate` 只读 RegionProfileVersion 与 VariantVersion/草稿投影，先校验 `org_id`、Region 版本状态和有效期，再检查 locale、market、单位、货币、时区、数据地域和平台资格。
- `restricted_topics` 命中内容或主题时返回阻断；`disclosure_rules` 中标记为必需的披露必须在变体披露或正文中出现。规则结果包含每项检查、阻断原因、所需披露和匹配限制，输出通过 `region-rule-decision.schema.json`。
- 同租户同幂等键和输入参数重放相同决策，参数不同返回 `IDEMPOTENCY_KEY_REUSED`；失败不写 Variant/Canonical/Region 事实，不调用模型或平台。
- `VariantStore` 可注入 `RegionRuleService`，在写入 `content_variants` 前执行 preflight；未注入时保留 PROD-002 的基础 Region Port 校验，以支持旧调用方逐步接入。

补充场景：

- Given active Region 版本允许 `en-US`、`US`、`USD` 和 `imperial`，When 评估匹配 Variant，Then 返回 `eligible`。
- Given locale、market、单位、货币或时区不匹配，When 评估，Then 返回 `blocked` 并指出对应字段。
- Given 内容命中 restricted topic 或缺少必需披露，When 评估，Then 返回 `blocked`，不写 VariantVersion。
- Given Region 版本过期、未激活、跨租户或平台不在资格列表，When 评估，Then 拒绝并不泄漏其他租户数据。
- Given 同一幂等键重复提交，When 参数相同，Then 返回相同 decision_hash；参数不同拒绝。

## 回滚

- 停止 Variant preflight 接入并保留历史决策审计；不删除已有 Variant 或 Region 事实。
- 本任务迁移为无业务表修订，规则字段变化使用后续兼容迁移。
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

- `执行 PROD-004 的公开用例或内部命令`

Then：

- `实现 `GEO_REGION` 前置规则：语言、单位、货币、时区、法规、披露和市场限制。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/production tests/integration --maxfail=1
```

Gate：`prod_004_acceptance`

## 外部依赖

- 无

## 开工前细化

已按区域规则输入、阻断原因、幂等和 Variant preflight 边界实现；证据见 `PROD-004-EVIDENCE.yaml`。
