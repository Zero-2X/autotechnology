# CANON-002 — 实现不可变 CanonicalContentVersion 和版本差异。

状态：`done`  
阶段：3（Provenance、Rights、KnowledgeCore 和 Canonical Content）  
Owner：`team/canonical_content`  
优先级：`critical` / `P0`

## 目标

实现不可变 CanonicalContentVersion 和版本差异。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `TOPIC-004`
- `CANON-001`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `CANON-002.implementation`
- `CANON-002.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/canonical-content-version.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_canon_002.py`
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

- `CanonicalContentVersion` 采用追加式写入；同一 `(org_id, canonical_content_id, version_no)` 只能有一行，不能通过更新覆盖已有内容。
- `GET /v1/canonical-contents/{id}/versions` 按 `version_no` 返回租户范围内的完整历史；传入 `from_version_no/to_version_no` 或版本 ID 时返回稳定 key/position 感知的 add/remove/replace diff。
- Diff 只比较编辑内容字段，不把生成时间和数据库身份字段当作内容变化；同一版本对重复比较返回相同 `diff_hash`。
- 跨租户、跨 Canonical 根的版本查询和比较必须拒绝；不存在的版本返回确定性错误，不产生 diff 记录。

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

- `执行 CANON-002 的公开用例或内部命令`

Then：

- `实现不可变 CanonicalContentVersion 和版本差异。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/canonical_content tests/integration --maxfail=1
```

Gate：`canon_002_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。

## Implementation Evidence

- `CanonicalContentService.list_versions` returns tenant-scoped immutable history; `diff_versions` compares stable `key`/`position` arrays and produces deterministic add/remove/replace operations and a SHA-256 diff hash.
- Version rows, Claim links and diff snapshots are append-only. Update-shaped commands return `IMMUTABLE_VERSION`, and the database trigger rejects direct mutation.
- `packages/db/migrations/versions/20260918_canon_002.py` adds the append-only `canonical_content_version_diffs` projection table after `20260918_found_canon_001`.
- `GET /internal/canonical-contents/{content_id}/versions` and `/v1/canonical-contents/{id}/versions` expose history and optional version diff parameters.
- Verification: `py -3.12 -m pytest tests/unit/canonical_content tests/integration/test_canonical_content_api.py -q` (5 passed).
