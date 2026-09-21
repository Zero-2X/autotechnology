# PROD-001 — 通过可替换的 `TransformPort` 生成 Variant 草稿；M1 使用 Fake/规则实现，Transform Agent 接入属于后续 P1，不调用发布接口。

状态：`done`  
阶段：4（Production、Localization、QA、Policy 和 Approval）  
Owner：`team/production`  
优先级：`critical` / `P0`

## 目标

通过可替换的 `TransformPort` 生成 Variant 草稿；M1 使用 Fake/规则实现，Transform Agent 接入属于后续 P1，不调用发布接口。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `CANON-002`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `PROD-001.implementation`
- `PROD-001.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/variant-version.schema.json`
- `packages/contracts/jsonschema/variant-draft.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_prod_001.py`
## 实现规格

- `VariantDraftService.generate` 通过只读 Canonical Version Port 按 `org_id` 获取源版本，拒绝跨租户、不存在和已撤回源版本；不得访问发布或授权接口。
- `TransformPort` 只接收不可变源版本、locale、market、audience、tone，返回候选正文。M1 的 `RuleTransformPort` 原样复制文本，按稳定 section key 生成块与源映射，并标注 `needs_review=true` 和 `transform_mode=rule_copy`，不声称已本地化。
- 输出符合 `variant-draft.schema.json`，包含源版本和内容哈希、块映射、草稿哈希、actor 与 trace；本任务只生成草稿，不创建 `ContentVariant` 或 `VariantVersion` 事实，这些由 `PROD-002` 完成。
- 同租户同幂等键和参数重放首次草稿，不重复调用 TransformPort；键相同但参数不同拒绝。输入和输出哈希进入内存审计记录。

补充场景：

- Given 一个 Canonical 版本有两个有序 section，When 生成草稿，Then 输出相同顺序与文本、稳定源映射和待人工复核状态。
- Given 源版本属于另一个租户或 freshness 为 withdrawn，When 生成草稿，Then 拒绝且不调用 TransformPort。
- Given TransformPort 试图改变租户、源 ID 或返回不合 Schema 的块，When 生成草稿，Then 拒绝该结果，不写业务事实。
- Given 重复幂等键，When 输入相同，Then 返回首次草稿；输入不同则拒绝。

## 回滚

- 停止新的草稿生成调用；现有内存审计和已返回草稿保持可复核。生产存储由后续任务追加迁移。
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

- `执行 PROD-001 的公开用例或内部命令`

Then：

- `通过可替换的 TransformPort 生成 Variant 草稿；M1 使用 Fake/规则实现，不调用发布接口。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/production tests/integration --maxfail=1
```

Gate：`prod_001_acceptance`

## 外部依赖

- 无

## 开工前细化

已按 M1 的规则变换边界实现；证据见 `PROD-001-EVIDENCE.yaml`。
