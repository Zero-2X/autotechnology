# DIST-006C — 实现未知结果、重试上限、死信和单任务重放；未知结果禁止自动副作用重试。

状态：`done`  
阶段：7（Distribution 抽象、Manual Export 和 Fake Adapter）  
Owner：`team/distribution`  
优先级：`critical` / `P0`

## 目标

实现未知结果、重试上限、死信和单任务重放；未知结果禁止自动副作用重试。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `FOUND-004D`
- `FOUND-004E`
- `POLICY-001`
- `DIST-006B`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `DIST-006C.implementation`
- `DIST-006C.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/publication-record.schema.json`
- `packages/contracts/jsonschema/human-task.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_dist_006c.py`

## 实现规格

- `DeliveryDeadLetterService.mark_unknown` 只接受同租户且符合 DeliveryAttempt 契约的输入；将 attempt 置为 `unknown`、`retryable=false`，创建唯一 `HumanTask(task_type=unknown_result)`，记录 `delivery.unknown` 事件和审计摘要。unknown 不进入自动重试队列。
- `DeliveryDeadLetterService.dead_letter` 仅在 `retryable=false` 或 `attempt_no >= max_attempts` 时允许；将 attempt 置为 `dead_letter`，创建 `support_escalation` HumanTask，记录 `delivery.dead_lettered`，不得改写已成功记录。
- `resolve_unknown` 要求人工 outcome、resolution reason 和 evidence ref；只允许 `succeeded|failed`，关闭原 HumanTask，更新 PublicationRecord/DeliveryAttempt，并记录 `delivery.unknown_resolved`。
- `replay_one` 要求显式 `manual_confirmation=true`，且命令使用原 `idempotency_key`；只生成新的 attempt-shaped replay plan（保留 provider idempotency key 和 parent attempt），返回 `side_effect_triggered=false`，绝不调用 Publisher/Adapter。
- 所有命令按租户和 payload hash 幂等，支持 `expected_version`，跨租户、状态冲突、重试上限未到和幂等键复用均拒绝；所有输出通过 DeliveryAttempt、PublicationRecord、HumanTask 和 EventEnvelope 契约校验。
## 目录边界

拥有目录：

- `modules/distribution`

允许目录：

- `modules/distribution`
- `adapters/contract`
- `adapters/manual`
- `adapters/fake`
- `tests/replay`
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

- `执行 DIST-006C 的公开用例或内部命令`

Then：

- `实现未知结果、重试上限、死信和单任务重放；未知结果禁止自动副作用重试。`
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- 相同未知/死信命令重放返回同一 attempt、PublicationRecord 和 HumanTask，不重复创建人工任务或事件。
- `retryable=true` 且 `attempt_no < max_attempts` 不得进入死信；达到上限后进入 `dead_letter`。
- unknown 只能由人工携带证据解析为 succeeded/failed；解析前的 replay 只生成计划，不执行副作用。
- 跨租户 attempt、错误的 expected version、错误的原始幂等键和成功状态回退均为确定性拒绝，事务不产生部分写入。

回滚：

- 关闭 unknown/dead-letter/replay 命令入口，保留已写入的 attempt、PublicationRecord、HumanTask、事件和审计事实。
- 本 revision 不创建业务表，投影使用内存服务；若需要回退迁移，执行 `python -m alembic downgrade 20260919_found_dist_006b`，不删除既有失败事实。

## 验证

```text
python -m pytest tests/unit/distribution tests/integration --maxfail=1
```

Gate：`dist_006c_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
