# WORKFLOW-CORE-001 — 定义 `WorkflowPort`、持久化状态机、人工任务、暂停、恢复、重试和重放接口。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/workflow`  
优先级：`critical` / `P0`

## 目标

定义 `WorkflowPort`、持久化状态机、人工任务、暂停、恢复、重试和重放接口。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-004B`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `WORKFLOW-CORE-001.implementation`
- `WORKFLOW-CORE-001.tests`
- `audit_evidence`

## 实现规格

定义 `WorkflowPort.start/resume/pause/retry/replay` 与持久化状态：`WorkflowRun(status=pending|running|paused|waiting_human|succeeded|failed|cancelled)`、`WorkflowStep(status=pending|running|succeeded|failed|skipped)`、`HumanTask(status=open|claimed|resolved|cancelled)`。状态转换采用白名单；非法转换返回 `INVALID_STATE_TRANSITION`。每次命令要求 `expected_version`，成功后 version+1，并写入 outbox 事件。`retry` 仅允许 transient failure，`replay` 必须引用原 run/step 版本且生成新 run。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/workflow-run.schema.json`
- `packages/contracts/jsonschema/human-task.schema.json`
- `packages/contracts/jsonschema/task-job.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_workflow_core_001.py`

## 实现规格

1. `WorkflowService` 实现 pending/running/paused/waiting_human/succeeded/failed/cancelled 状态和 WorkflowPort start/resume/pause/retry/replay。
2. 每次命令要求 expected_version，成功递增 version 并写入 outbox；非法转换、跨租户、版本冲突和非 transient retry 明确拒绝。
3. replay 只复制输入 hash，生成新 run 并记录来源；暂停和人工等待不会被自动推进。

## 验收证据

- `modules/workflow/service.py` 提供租户范围状态机、WorkflowStep/HumanTask 模型、重试和重放接口。
- 单元测试覆盖并发版本冲突、暂停恢复、transient retry、terminal replay、outbox 和跨租户拒绝。
- 迁移为无业务表 no-op。
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

- `执行 WORKFLOW-CORE-001 的公开用例或内部命令`

Then：

- `定义 `WorkflowPort`、持久化状态机、人工任务、暂停、恢复、重试和重放接口。`
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- 两个并发 resume 只有一个成功，另一个返回 `VERSION_CONFLICT`。
- paused/waiting_human 状态不得被 scheduler 自动推进。
- replay 复制输入快照但不复制 secret/token；审计中记录 `replayed_from_run_id`。


## 回滚与运行说明

- 通过任务级 feature flag 关闭新命令；已提交的业务事实和审计记录不删除。
- 迁移按 expand/contract 顺序执行；验证失败时停止后续任务，保留兼容字段，不执行破坏性回滚。
- 如产生可重试任务，先暂停对应队列，再按原幂等键重放；任何外部未知结果必须转人工核查。

## 验证

```text
python -m pytest tests/unit/workflow tests/integration --maxfail=1
```

Gate：`workflow_core_001_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
