# CANON-004 — 让每个高优先级 Claim 绑定至少一个 Evidence 和具体的 `RightsRecordVersion`。

状态：`done`  
阶段：3（Provenance、Rights、KnowledgeCore 和 Canonical Content）  
Owner：`team/canonical_content`  
优先级：`critical` / `P0`

## 目标

让每个高优先级 Claim 绑定至少一个 Evidence 和具体的 `RightsRecordVersion`。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `TOPIC-004`
- `PROV-002`
- `KNOW-001`
- `CANON-003`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `CANON-004.implementation`
- `CANON-004.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/canonical-content-version.schema.json`
- `packages/contracts/jsonschema/claim.schema.json`
- `packages/contracts/jsonschema/evidence.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_canon_004.py`
## 目录边界

拥有目录：

- `modules/canonical_content`

允许目录：

- `modules/canonical_content`
- `apps/api`
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

## 实现规格

- Claim 数组元素可声明 `priority`、`claim_id`、`evidence_ids` 和 `rights_snapshot_ids`；`high`/`urgent` Claim 必须同租户存在至少一个未失效 Evidence 和一个 `verified` 的 `RightsRecordVersion`。
- 未显式提供 Evidence 时按 Claim 关系表推导；Evidence 的权利版本会补入该 Claim 的 rights snapshot，便于复核。
- 缺少 Claim、Evidence、权利版本、跨租户引用或无效状态时返回 `CANONICAL_EVIDENCE_REQUIRED`/`CANONICAL_RIGHTS_REQUIRED`，事务不产生版本、关系或事件。

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

- `执行 CANON-004 的公开用例或内部命令`

Then：

- `让每个高优先级 Claim 绑定至少一个 Evidence 和具体的 `RightsRecordVersion`。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/canonical_content tests/integration --maxfail=1
```

Gate：`canon_004_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。

## Implementation Evidence

- `CanonicalContentService._claim_binding_refs` 对高优先级 Claim 执行租户、状态、Evidence 关系和 RightsRecordVersion 校验；绑定结果写入 `canonical_claims` 与版本 payload。
- `20260918_found_canon_004` 为关系表增加 `claim_id`、priority、evidence_ids 和 rights_snapshot_ids，并创建查询索引。
- Verification: `py -3.12 -m pytest tests/unit/canonical_content tests/integration/test_canonical_content_api.py -q` (7 passed).
