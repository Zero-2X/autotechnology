# CANON-003 — 创建版本时强制引用已批准的 `TopicBrief`；没有 Brief 的请求返回 `TOPIC_BRIEF_REQUIRED`，不能绕过选题流程。

状态：`done`  
阶段：3（Provenance、Rights、KnowledgeCore 和 Canonical Content）  
Owner：`team/canonical_content`  
优先级：`critical` / `P0`

## 目标

创建版本时强制引用已批准的 `TopicBrief`；没有 Brief 的请求返回 `TOPIC_BRIEF_REQUIRED`，不能绕过选题流程。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `TOPIC-004`
- `CANON-002`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `CANON-003.implementation`
- `CANON-003.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/canonical-content-version.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_canon_003.py`
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

- CanonicalContentVersion 创建前必须解析同租户 TopicBrief；状态只能为 `locked` 或 `approved`，否则返回 `TOPIC_BRIEF_REQUIRED`。
- 版本保存 `topic_brief_status`、`topic_brief_lock_hash` 和 `input_snapshot_hash`，使版本可独立复核其输入；校验失败在事务提交前终止。
- TopicBrief 缺失、跨租户或未锁定时不得插入 `canonical_content_versions`、Claim 关系或事件。

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

- `执行 CANON-003 的公开用例或内部命令`

Then：

- `创建版本时强制引用已批准的 `TopicBrief`；没有 Brief 的请求返回 `TOPIC_BRIEF_REQUIRED`，不能绕过选题流程。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/canonical_content tests/integration --maxfail=1
```

Gate：`canon_003_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。

## Implementation Evidence

- `CanonicalContentService._topic_brief` 在共享存储或 TopicBrief port 上执行租户和状态检查；`create_version` 在任何版本写入前完成校验。
- `canonical_content_versions` 增加 `topic_brief_status` 与 `topic_brief_lock_hash` 快照字段；迁移 `20260918_found_canon_003` 可回滚。
- Verification: `py -3.12 -m pytest tests/unit/canonical_content tests/integration/test_canonical_content_api.py -q` (6 passed).
