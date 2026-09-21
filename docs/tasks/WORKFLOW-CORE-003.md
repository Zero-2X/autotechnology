# WORKFLOW-CORE-003 — 实现 `OutboxDispatcher`、任务租约、死信和重放命令；所有命令都有幂等键。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/workflow`  
优先级：`critical` / `P0`

## 目标

实现 `OutboxDispatcher`、任务租约、死信和重放命令；所有命令都有幂等键。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-004B`
- `WORKFLOW-CORE-002`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `WORKFLOW-CORE-003.implementation`
- `WORKFLOW-CORE-003.tests`
- `audit_evidence`

## 实现规格

Dispatcher 消费 `OutboxEvent(status=pending|publishing|published|failed|dead_letter)` 并创建/更新 `TaskJob`。领取采用 `locked_by`/`lease_until` 短租约，发布成功写 `published_at`；失败按 error_class 决定 retry/dead_letter。所有内部命令必须带 Idempotency-Key，事件 envelope 的 `event_id` 去重。

接口：`POST /internal/workflow/outbox:dispatch`、`POST /internal/task-jobs/{id}:claim`、`/{id}:retry`、`/{id}:replay`。错误码：`OUTBOX_ALREADY_PUBLISHED`、`JOB_LEASE_EXPIRED`、`REPLAY_NOT_ALLOWED`、`IDEMPOTENCY_KEY_REUSED`。每次 dispatch 记录 `DispatchAttempt` 与 trace_id。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/outbox-event.schema.json`
- `packages/contracts/jsonschema/task-job.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_workflow_core_003.py`
## 目录边界

拥有目录：

- `modules/workflow`

允许目录：

- `modules/workflow`
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

- `执行 WORKFLOW-CORE-003 的公开用例或内部命令`

Then：

- `实现 `OutboxDispatcher`、任务租约、死信和重放命令；所有命令都有幂等键。`
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- Dispatcher 重启后 processing 事件 lease 到期可安全重领，event_id 不重复下游副作用。
- dead_letter 任务 requeue/replay 均生成新 attempt/job，旧记录不可变。
- 跨租户 outbox 或 task job 访问返回 `TENANT_SCOPE_VIOLATION`。

回滚：停止 dispatcher 与新任务领取；pending/failed 事件保留，恢复后继续处理，不直接清空队列。

六类 GWT 必须覆盖：成功 dispatch、重复幂等键、非法命令、权限/跨租户、依赖缺失、重试/死信/重放与未知结果。

## 验证

```text
python -m pytest tests/unit/workflow tests/integration --maxfail=1
```

Gate：`workflow_core_003_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。

## Implementation Evidence

- Implementation: modules/workflow/dispatcher.py provides tenant-scoped outbox dispatch, event-id and command idempotency, task-job creation, short leases, retry/dead-letter transitions, and immutable replay.
- API: /internal/workflow/outbox:dispatch requires X-Worker-Id and Idempotency-Key.
- Tests: 	ests/unit/workflow/test_dispatcher.py and 	ests/integration/test_workflow_core_002_api.py.
- Migration: packages/db/migrations/versions/20260918_workflow_core_003.py.
