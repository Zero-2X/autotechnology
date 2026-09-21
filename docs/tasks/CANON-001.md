# CANON-001 — 实现 CanonicalContent：渠道无关的编辑叙事、章节结构、代码、示例和限制。

状态：`done`  
阶段：3（Provenance、Rights、KnowledgeCore 和 Canonical Content）  
Owner：`team/canonical_content`  
优先级：`critical` / `P0`

## 目标

实现 CanonicalContent：渠道无关的编辑叙事、章节结构、代码、示例和限制。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `TOPIC-004`
- `KNOW-002`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `CANON-001.implementation`
- `CANON-001.tests`
- `audit_evidence`

## 实现规格

`CanonicalContent` 为根对象，字段：`id`、`org_id`、`topic_brief_id`、`status=draft|in_review|approved|archived`、`current_version_id`、`created_by`、`created_at`。版本对象 `CanonicalContentVersion(id, canonical_content_id, version_no, title, abstract, sections[], claims[], code_blocks[], examples[], limitations[], source_snapshot_refs[], knowledge_core_version, content_hash, created_at)`；数组元素必须有稳定 `key`，排序由 `position` 决定。

命令：`POST /internal/canonical-contents` 创建 draft；`POST /internal/canonical-contents/{id}/versions` 创建新版本；`POST /internal/canonical-contents/{id}:submit-review`。版本创建必须携带已锁定的 `TopicBrief` 和 `input_snapshot_hash`，旧版本只读。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/canonical-content.schema.json`
- `packages/contracts/jsonschema/canonical-content-version.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_canon_001.py`
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

- `执行 CANON-001 的公开用例或内部命令`

Then：

- `实现 CanonicalContent：渠道无关的编辑叙事、章节结构、代码、示例和限制。`
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- 未提供 locked TopicBrief 返回 `TOPIC_BRIEF_REQUIRED`；不得写入版本记录。
- 同一 `content_hash` 在同一 canonical 根下重复提交返回既有 version_id（幂等），不得产生新版本。
- 修改已审批版本返回 `IMMUTABLE_VERSION`；必须从其复制创建下一个 version_no。


## 回滚与运行说明

- 通过任务级 feature flag 关闭新命令；已提交的业务事实和审计记录不删除。
- 迁移按 expand/contract 顺序执行；验证失败时停止后续任务，保留兼容字段，不执行破坏性回滚。
- 如产生可重试任务，先暂停对应队列，再按原幂等键重放；任何外部未知结果必须转人工核查。

## 验证

```text
python -m pytest tests/unit/canonical_content tests/integration --maxfail=1
```

Gate：`canon_001_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。

## Implementation Evidence

- `modules/canonical_content/service.py` implements tenant-scoped roots, locked TopicBrief and input snapshot checks, stable-key arrays, idempotent commands, duplicate `content_hash` replay, immutable version inserts, review submission, and ordered audit events.
- `modules/canonical_content/infrastructure/canonical_schema.py` owns `canonical_contents`, `canonical_content_versions`, `canonical_claims`, `canonical_commands`, and `canonical_events`; version and audit rows are append-only.
- `packages/db/migrations/versions/20260918_canon_001.py` is the reversible Alembic revision `20260918_found_canon_001` after `20260918_found_know_002`.
- Verification: `py -3.12 -m pytest tests/unit/canonical_content tests/integration/test_canonical_content_api.py -q` (4 passed).
