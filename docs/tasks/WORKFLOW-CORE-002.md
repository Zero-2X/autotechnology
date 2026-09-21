# WORKFLOW-CORE-002 — 实现 `workflow_runs`、`workflow_steps`、`human_tasks` 状态和到期扫描；人工节点必须可暂停、恢复和重放。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/workflow`  
优先级：`critical` / `P0`

## 目标

实现 `workflow_runs`、`workflow_steps`、`human_tasks` 状态和到期扫描；人工节点必须可暂停、恢复和重放。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-004A`
- `WORKFLOW-CORE-001`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `WORKFLOW-CORE-002.implementation`
- `WORKFLOW-CORE-002.tests`
- `audit_evidence`

## 实现规格

`WorkflowRun(id, org_id, workflow_key, workflow_version, status=planned|running|paused|succeeded|failed|cancelled, input_hash, created_at)`；`WorkflowStep(id, org_id, workflow_run_id, step_key, step_no, status=queued|running|waiting|succeeded|failed|cancelled, input_hash, created_at)`；人工节点使用既有 `HumanTask` 状态机（`queued|assigned|claimed|in_progress|submitted|completed|escalated|rejected|expired|cancelled`），不另建 `open/resolved` 状态。

接口：`POST /internal/workflow-runs`、`/{id}:pause`、`/{id}:resume`、`/{id}:replay`、`/human-tasks/{id}:claim`、`/{id}:start`、`/{id}:submit`、`/{id}:complete`。到期扫描每分钟处理 `due_at < now`：HumanTask 标记 `expired` 并将 WorkflowRun 置为 `paused`；不可自动跳过。每个状态修改需 expected version，人工任务写入已登记的 `human_task.*` 事件，WorkflowRun/Step 变化写追加式审计和对应 TaskJob/Outbox 控制事件。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/workflow-run.schema.json`
- `packages/contracts/jsonschema/workflow-step.schema.json`
- `packages/contracts/jsonschema/human-task.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_workflow_core_002.py`
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

- `执行 WORKFLOW-CORE-002 的公开用例或内部命令`

Then：

- `实现 `workflow_runs`、`workflow_steps`、`human_tasks` 状态和到期扫描；人工节点必须可暂停、恢复和重放。`
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- 并发 pause/resume 只有一个成功，冲突返回 `VERSION_CONFLICT`。
- queued/assigned human task 被 claim 后仅领取人或具备 reviewer 权限的操作者可 start/submit/complete；重复 complete 幂等。
- due_at 到期后 HumanTask 进入 `expired`、WorkflowRun 进入 `paused`，scheduler 不得推进后续步骤。

回滚：关闭到期 scanner；保留已暂停 run 和 human task，恢复后按 due_at 继续扫描。

六类 GWT 必须覆盖：成功推进、重复命令、非法状态、权限/跨租户、依赖缺失、到期暂停/恢复与未知结果。

## 验证

```text
python -m pytest tests/unit/workflow tests/integration --maxfail=1
```

Gate：`workflow_core_002_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
\n## Implementation Evidence\n\n- Implementation: modules/workflow/service.py adds workflow steps, human-task claim/update transitions, expiry scanning, tenant checks, expected-version guards, and outbox audit events.\n- Tests: 	ests/unit/workflow/test_service.py and 	ests/integration/test_workflow_core_002_api.py.\n- Migration: packages/db/migrations/versions/20260918_workflow_core_002.py.\n