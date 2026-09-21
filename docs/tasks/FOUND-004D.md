# FOUND-004D — 实现失败记录、重试上限、退避和死信队列。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/foundation`  
优先级：`critical` / `P0`

## 目标

实现失败记录、重试上限、退避和死信队列。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-004C`

## 输入

- `packages/contracts/jsonschema/task-job.schema.json`：既有 task_jobs 状态与重试字段契约。
- `packages/contracts/jsonschema/task-failure.schema.json`：追加式失败事实契约。
- `packages/contracts/jsonschema/human-task.schema.json`：未知结果人工复核任务契约。
- `packages/db/migrations/versions/20260916_found_004d_failure_retry.py`：本任务新增 `task_failures` 与 `human_tasks` 表。
- `TenantContext` 等价输入：`org_id`、`actor_id`、`trace_id` 和幂等上下文；所有读取和写入按 `org_id` 限定。

## 输出

- `infra/foundation/task_failure.py`：失败事实、错误分类、重试策略、人工复核和死信重新入队。
- `apps/api/main.py`：worker-only `retry` 与 `requeue-dead` 内部命令。
- `packages/db/migrations/versions/20260916_found_004d_failure_retry.py`：可逆且不改写既有 task_jobs baseline 的迁移。
- `tests/contract/test_found_004d_failure_retry.py`、`tests/integration/test_found_004d_failure_retry_integration.py`。
- `docs/foundation/FOUND-004D-EVIDENCE.yaml`：验证与副作用证据。

## 实现规格

`TaskFailure(id, org_id, job_id, attempt_count, error_class=deterministic|transient|unknown, error_code, message_redacted, retryable, trace_id, occurred_at)` 是追加式失败事实；失败事实以 `(job_id, attempt_count, error_code)` 唯一并幂等。重试策略由 `RetryPolicy(backoff_base_ms, backoff_cap_ms, jitter)` 计算指数退避并封顶；`TaskJob.available_at` 写入下一次可执行时间。deterministic 立即将任务置为 `failed` 且返回 `RETRY_NOT_ALLOWED`，transient 未超限置为 `retry_scheduled`，超限置为 `dead_letter` 且返回 `MAX_ATTEMPTS_EXCEEDED`，unknown 创建唯一 `HumanTask(task_type=unknown_result)`、暂停自动重试并返回 `UNKNOWN_RESULT_REQUIRES_REVIEW`。死信重新入队必须生成新的 TaskJob，保留 `replayed_from_job_id`、`replayed_from_attempt_count` 和原失败事实。

内部命令：`POST /internal/task-jobs/{id}:retry`、`/{id}:requeue-dead`，均要求 `X-Worker-Id`、`org_id`、`trace_id` 和 `Idempotency-Key`。错误码：`RETRY_NOT_ALLOWED`、`MAX_ATTEMPTS_EXCEEDED`、`UNKNOWN_RESULT_REQUIRES_REVIEW`、`TENANT_SCOPE_VIOLATION`。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/task-job.schema.json`
- `packages/contracts/jsonschema/task-failure.schema.json`
- `packages/contracts/jsonschema/human-task.schema.json`

迁移 revision：

- `packages/db/migrations/versions/20260916_found_004d_failure_retry.py`
## 目录边界

拥有目录：

- `infra/foundation`

允许目录：

- `infra/foundation`
- `apps`
- `packages`
- `infra`
- `deploy/environments/dev`
- `deploy/environments/staging`
- `scripts`
- `docs`
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

- `执行 FOUND-004D 的公开用例或内部命令`

Then：

- `相同 (job_id, attempt_count, error_code) 失败重复上报返回同一 TaskFailure，不新增事实或重复推进状态。`
- `deterministic 失败进入 failed 且不可 retry；transient 在 max_attempts 内按指数退避进入 retry_scheduled，达到上限进入 dead_letter。`
- `退避按 backoff_base_ms * 2^(attempt_count-1) 计算并受 backoff_cap_ms 约束；jitter 可控且不突破 cap。`
- `retry_scheduled 且 available_at 已到期的任务重新进入 claim/poll 候选集，未到期任务保持不可领取。`
- `unknown 失败只创建一个 unknown_result HumanTask，任务不再自动重试，并返回 UNKNOWN_RESULT_REQUIRES_REVIEW。`
- `跨租户 job_id、retry 和 requeue-dead 返回 TENANT_SCOPE_VIOLATION，不能修改任何行。`
- `dead_letter requeue 生成新 TaskJob，旧 TaskFailure 与旧 job 不可变，新 job 可追踪原 job/attempt/failure。`
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- 相同失败事件重复上报按 `(job_id,attempt_no,error_code)` 幂等。
- deterministic 错误不得重试；transient 在 cap 内按退避重试。
- dead 任务 requeue 后旧记录不可变，新 attempt 可追踪原 failure_id。
- 缺失或非法错误分类、空错误码、非法 retry policy 均为确定性校验错误，事务不产生部分写入。

回滚：关闭自动 retry flag；保留失败与 dead 记录，允许运维手工 requeue；必要时执行 `python -m alembic downgrade 20260916_found_004c` 删除本任务新增表。

六类 GWT 必须覆盖：成功分类、重复失败事件、非法错误类、权限/跨租户、策略缺失、退避/死信与未知结果。

## 验证

```text
python -m pytest tests/contract/test_found_004d_failure_retry.py tests/integration/test_found_004d_failure_retry_integration.py --maxfail=1
```

Gate：`found_004d_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡已完成：追加式失败事实、三类错误分类、幂等去重、指数退避与 cap、确定性失败、死信队列、未知结果人工任务、跨租户拒绝和 dead-letter requeue 均已通过 synthetic SQLite 与 worker-only API 测试；既有 task_jobs SQL baseline 未改写。
