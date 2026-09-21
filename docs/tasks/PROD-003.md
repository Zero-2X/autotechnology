# PROD-003 — 实现术语表、Translation Memory、产品名锁定、数字/代码/链接保护。

状态：`done`  
阶段：4（Production、Localization、QA、Policy 和 Approval）  
Owner：`team/production`  
优先级：`critical` / `P0`

## 目标

实现术语表、Translation Memory、产品名锁定、数字/代码/链接保护。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `CANON-002`
- `PROD-002`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `PROD-003.implementation`
- `PROD-003.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/variant-version.schema.json`
- `packages/contracts/jsonschema/terminology-version.schema.json`
- `packages/contracts/jsonschema/translation-memory-entry.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_prod_003.py`
## 实现规格

- `TerminologyService` 按租户和 locale 追加不可变术语表版本，记录源术语、目标术语和锁定的产品名；同一 locale 的版本号递增，内容哈希可复算。
- Translation Memory 仅保存源文本哈希与已批准的目标文本；按租户和 locale 查询建议，不泄漏其他租户条目。写入使用幂等键，重复内容不产生重复事实。
- `check_translation` 从源文本和目标文本提取代码片段、URL 与数字词元，比较出现次数；锁定产品名必须原样保留。术语命中时检查目标术语是否出现。返回可解释问题，不自动改写译文。
- `check_draft` 依据 Canonical 源版本与 Variant 草稿的稳定块映射逐块执行检查，并返回 TM 建议。它不批准草稿、不修改 VariantVersion、不调用模型或发布接口。

补充场景：

- Given 数字、代码、URL 或锁定产品名在译文中丢失，When 检查，Then 返回对应缺失问题和块 ID。
- Given 术语表要求目标译法，When 译文缺失该译法，Then 返回术语问题。
- Given 已批准 TM 条目，When 查相同源哈希和 locale，Then 返回该租户的建议；其他租户不可读取。
- Given 同一幂等键重复提交，When 参数相同，Then 返回首次结果；参数不同拒绝。

## 回滚

- 停止写入新术语版本和 TM 条目，保留历史记录；校验服务可停用而不修改已保存 Variant 事实。
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

- `执行 PROD-003 的公开用例或内部命令`

Then：

- `实现术语表、Translation Memory、产品名锁定、数字/代码/链接保护。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/production tests/integration --maxfail=1
```

Gate：`prod_003_acceptance`

## 外部依赖

- 无

## 开工前细化

已实现租户范围的术语/TM 记录和确定性保护检查；证据见 `PROD-003-EVIDENCE.yaml`。
