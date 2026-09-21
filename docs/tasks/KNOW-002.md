# KNOW-002 — 实现 `KnowledgeCore`，保存结构化事实、证据关系、冲突和新鲜度。

状态：`done`  
阶段：3（Provenance、Rights、KnowledgeCore 和 Canonical Content）  
Owner：`team/knowledge`  
优先级：`critical` / `P0`

## 目标

实现 `KnowledgeCore`，保存结构化事实、证据关系、冲突和新鲜度。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `TOPIC-004`
- `PROV-002`
- `KNOW-001`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `KNOW-002.implementation`
- `KNOW-002.tests`
- `audit_evidence`

## 实现规格

`KnowledgeCore` 聚合字段：`id`、`org_id`、`topic_brief_id`、`version_no`、`status=draft|validated|stale|archived`、`entity_ids[]`、`claim_ids[]`、`evidence_ids[]`、`conflict_set_ids[]`、`freshness_checked_at`、`content_hash`。Claim 必须引用至少一条 Evidence；Evidence 必须指向 `SourceSnapshot` 与 `RightsRecordVersion`。冲突不能静默覆盖，需生成 `ConflictSet` 并将聚合标记 `needs_review=true`。版本不可变，刷新创建新 version。

接口：`POST /internal/knowledge-cores`、`POST /internal/knowledge-cores/{id}:validate`、`POST /internal/knowledge-cores/{id}:refresh`。validate 仅在所有 Claim 有有效 Evidence 且 rights=verified/permitted_use 足够时通过。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/knowledge-core.schema.json`
- `packages/contracts/jsonschema/knowledge-core-version.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_know_002.py`
## 目录边界

拥有目录：

- `modules/knowledge`

允许目录：

- `modules/knowledge`
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

- `执行 KNOW-002 的公开用例或内部命令`

Then：

- `实现 `KnowledgeCore`，保存结构化事实、证据关系、冲突和新鲜度。`
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- 任一 Claim 缺 evidence 或 evidence rights 过期时返回 `KNOWLEDGE_EVIDENCE_INSUFFICIENT`，状态保持 draft。
- 检测到互相冲突的 Claim 时状态为 `needs_review`，不得自动生成 approved Canonical。
- refresh 失败保留旧 current version，并创建可重试任务和审计事件。


## 回滚与运行说明

- 通过任务级 feature flag 关闭新命令；已提交的业务事实和审计记录不删除。
- 迁移按 expand/contract 顺序执行；验证失败时停止后续任务，保留兼容字段，不执行破坏性回滚。
- 如产生可重试任务，先暂停对应队列，再按原幂等键重放；任何外部未知结果必须转人工核查。

## 验证

```text
py -3.12 -m pytest tests/unit/knowledge/test_core_service.py tests/integration/test_knowledge_core_api.py --maxfail=1
py -3.12 scripts/check_json_schemas.py
py -3.12 scripts/check_architecture.py
py -3.12 scripts/check_migrations.py --strict --json
```

Gate：`know_002_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。

## Implementation Evidence

- `modules/knowledge/core_service.py`：KnowledgeCore 创建、验证、刷新、冲突集检测、权利/来源门禁、租户隔离、幂等命令和版本事件。
- `modules/knowledge/infrastructure/knowledge_schema.py` 与 `packages/db/migrations/versions/20260918_know_002.py`：Core、不可变 Version、ConflictSet、Core 命令表、复合租户约束和追加式触发器。
- `apps/api/main.py`：`/internal/knowledge-cores` 创建、`:validate`、`:refresh`、查询入口与 expected version/If-Match 解析。
- `tests/unit/knowledge/test_core_service.py` 与 `tests/integration/test_knowledge_core_api.py`：有效权利链验证、证据不足拒绝、冲突需复核、版本不可变、刷新回滚语义、API 和租户隔离。
- `docs/foundation/KNOW-002-EVIDENCE.yaml`：专项门禁、Schema、架构和迁移验证结果。
