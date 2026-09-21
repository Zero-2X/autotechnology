# TOPIC-008 — 实现 `TopicBrief` 版本锁定：批准时原子写入 `version_no`、`locked_at`、`locked_by`、`lock_hash` 和 `input_snapshot_hash`；批准/锁定后禁止原地修改，修改必须创建新版本。

状态：`done`  
阶段：2（Topic Intelligence（选题智能））  
Owner：`team/topic`  
优先级：`critical` / `P0`

## 目标

实现 `TopicBrief` 版本锁定：批准时原子写入 `version_no`、`locked_at`、`locked_by`、`lock_hash` 和 `input_snapshot_hash`；批准/锁定后禁止原地修改，修改必须创建新版本。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `FOUND-011`
- `TOPIC-004`
- `TOPIC-006`
- `TOPIC-007`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `TOPIC-008.implementation`
- `TOPIC-008.tests`
- `audit_evidence`

## 实现规格

- `TopicBriefVersion` 至少保存 `id`、`org_id`、`opportunity_id`、`version_no`、`status`、`input_snapshot_hash`、`locked_at`、`locked_by`、`lock_hash`、`supersedes_version_id`、`created_by` 和 `created_at`。
- 公开命令只有 `POST /v1/topic-briefs/{id}/approve`；该命令在一个事务中校验字段、写入 `status=approved` 和全部锁定字段，并写入 `topic.brief.approved`。不得提供可绕过批准的公开 `lock` CRUD。
- `lock_hash=sha256(canonical_json(brief_payload + input_snapshot_hash + version_no))`；同一版本重复批准返回原结果，payload 或 `If-Match` 不一致返回 `IDEMPOTENCY_KEY_REUSED` 或 `OPTIMISTIC_LOCK_CONFLICT`。
- 批准后任何字段更新均返回 `IMMUTABLE_VERSION`；修改必须创建 `version_no+1` 的 draft，并填写 `supersedes_version_id`。创建人可以编辑新 draft，但不能审批自己的版本。

补充场景：

- 缺少 audience、problem、claim_specs、evidence_plan、original_angle、locale 或 market 时返回 `TOPIC_BRIEF_INCOMPLETE`，不改变状态。
- 并发批准只有一个请求成功；另一个请求返回 `OPTIMISTIC_LOCK_CONFLICT`，不得生成第二个 approved 版本或第二个事件。
- 读取批准版本时 `lock_hash` 可重复计算且一致；审计记录包含 actor、trace_id、input_snapshot_hash 和事件 ID。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/topic-brief.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_topic_008.py`
## 目录边界

拥有目录：

- `modules/topic`

允许目录：

- `modules/topic`
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

- `执行 TOPIC-008 的公开用例或内部命令`

Then：

- `实现 `TopicBrief` 版本锁定：批准时原子写入 `version_no`、`locked_at`、`locked_by`、`lock_hash` 和 `input_snapshot_hash`；批准/锁定后禁止原地修改，修改必须创建新版本。`
- `输出契约、审计事件和指定测试结果可复现`


## 回滚与运行说明

- 通过任务级 feature flag 关闭新命令；已提交的业务事实和审计记录不删除。
- 迁移按 expand/contract 顺序执行；验证失败时停止后续任务，保留兼容字段，不执行破坏性回滚。
- 如产生可重试任务，先暂停对应队列，再按原幂等键重放；任何外部未知结果必须转人工核查。

## 验证

```text
python -m pytest tests/unit/topic tests/integration --maxfail=1
```

Gate：`topic_008_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。

## Implementation Evidence

- `modules/topic/brief.py`：`approve` 原子写入批准/锁定元数据，按 canonical payload、输入快照和版本计算 `lock_hash`，校验创建人不得批准自己的版本，并为已批准版本创建新的 draft 修订。
- `modules/topic/infrastructure/brief_schema.py` 与 `20260918_topic_008.py`：保存显式版本元数据、批准状态和数据库不变性触发器。
- `apps/api/main.py`：`/v1/topic-briefs/{id}/approve` 通过 `Idempotency-Key` 与 `If-Match` 调用批准命令；旧内部 lock 命令保留为兼容入口。
- `tests/unit/topic/test_brief.py` 与 `tests/integration/test_topic_brief.py`：批准、重放、创建人限制、篡改拒绝、draft 修订、不完整字段、租户和 API 并发版本检查。
- `docs/foundation/TOPIC-008-EVIDENCE.yaml`：专项门禁结果。
