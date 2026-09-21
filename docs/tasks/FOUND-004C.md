# FOUND-004C — 实现 task claim、租约、超时和崩溃后重新领取。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/foundation`  
优先级：`critical` / `P0`

## 目标

实现 task claim、租约、超时和崩溃后重新领取。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-003D`
- `FOUND-004B`

## 输入

- `packages/contracts/jsonschema/task-job.schema.json`：TaskJob 字段与状态契约。
- `packages/db/migrations/versions/20260916_found_003d_task_jobs.sql`：既有 task_jobs SQL baseline，不得改写。
- `packages/db/migrations/versions/20260916_found_004c_task_leases.py`：本任务新增租约表 revision。
- `TenantContext` 等价输入：`org_id`、`worker_id`、`trace_id` 和幂等上下文。

## 输出

- `infra/foundation/task_claim.py`：原子 claim、heartbeat、start、complete、fail 和租约错误码。
- `packages/db/migrations/versions/20260916_found_004c_task_leases.py`：`task_job_leases` 迁移。
- `apps/api/main.py`：worker-only internal task commands。
- `tests/contract/test_found_004c_task_claim.py`、`tests/integration/test_found_004c_task_claim_integration.py`。
- `docs/foundation/FOUND-004C-EVIDENCE.yaml`：验证与副作用证据。

## 实现规格

`TaskJob(id, org_id, job_type, queue_name, aggregate_type, aggregate_id, aggregate_version, payload_ref, status=queued|leased|running|succeeded|failed|retry_scheduled|dead_letter|cancelled, attempt_count, max_attempts, available_at, lease_until, locked_by, last_error, replayed_from_job_id, replayed_from_attempt_count, replay_reason, idempotency_key, trace_id, created_at, updated_at)`；`claim(worker_id, lease_seconds)` 原子领取 queued 或 lease 过期任务，返回短时 lease token。`heartbeat(job_id, token)` 延长租约；`start` 将有效 leased 任务转为 running；`complete/fail` 必须校验 token、`locked_by`、租约未过期和 `expected_version`。

实现约束：

- `task_jobs` 仍是任务状态事实源；`task_job_leases` 只保存当前 token、worker、租约时间和 claim version，历史 token 不可复用。
- SQLite fixture 使用 `BEGIN IMMEDIATE`；PostgreSQL 领取使用 `FOR UPDATE SKIP LOCKED`，所有状态/token 更新与租约删除在同一短事务内完成。
- claim 只按 `org_id` 和 queue 过滤；跨租户 job_id、heartbeat、complete、fail 返回 `TENANT_SCOPE_VIOLATION`。
- lease 到期时旧 token 立即失效，新 worker claim 将 `attempt_count` 加一并生成新 token；旧 worker 不得覆盖新状态。

内部命令：`POST /internal/task-jobs:claim`、`/internal/task-jobs/{id}:heartbeat`、`/{id}:complete`、`/{id}:fail`（均要求 `X-Worker-Id`，worker-only）。错误码：`JOB_NOT_CLAIMABLE`、`LEASE_TOKEN_INVALID`、`JOB_VERSION_CONFLICT`、`JOB_LEASE_EXPIRED`、`TENANT_SCOPE_VIOLATION`。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/task-job.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移 revision：

- `packages/db/migrations/versions/20260916_found_004c_task_leases.py`
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

- `执行 FOUND-004C 的公开用例或内部命令`

Then：

- `实现 task claim、租约、超时和崩溃后重新领取。`
- `queued 或已过期 leased/running 任务只能被一个 worker 原子领取；成功返回新 lease token。`
- `有效 token heartbeat 延长 lease_until；start/complete/fail 校验 worker、token、租约和 expected_version。`
- `同一 task 的旧 token 在重新领取后不可完成或失败；租约过期返回 JOB_LEASE_EXPIRED/LEASE_TOKEN_INVALID。`
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- 两个 worker 并发 claim 只有一个成功；另一个得到 `JOB_NOT_CLAIMABLE`。
- worker 崩溃后 lease_until 过期，任务可被新 worker 领取且 `attempt_count+1`。
- 过期 token complete 返回 `LEASE_TOKEN_INVALID`，不得覆盖新 worker 状态。
- 非法 org_id、worker_id、lease_seconds、limit 或 expected_version 返回确定性错误且不改变任务。

回滚：暂停领取开关；running 任务保留，lease scanner 继续回收，不强制取消。

## 回滚与运行说明

- 关闭 claim feature flag 后保留 `leased|running` 任务及当前租约；不删除任务历史。
- 通过 `python -m alembic downgrade 20260916_found_004b` 回滚 `task_job_leases` 表；既有 `task_jobs` SQL baseline 不改写。
- synthetic SQLite fixture 不代表真实 PostgreSQL；生产 lock timeout、连接池与 worker 认证由后续基础设施任务负责。

六类 GWT 必须覆盖：成功领取、重复 claim、非法 token、权限/跨租户、依赖缺失、租约过期重领与未知结果。

## 验证

```text
python -m pytest tests/contract tests/integration --maxfail=1
```

Gate：`found_004c_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡已完成：原子 claim、heartbeat、start、complete、fail、租约过期重领、旧 token 失效、版本冲突、跨租户隔离和 worker-only internal 命令均已通过 synthetic SQLite 与集成测试；既有 task_jobs SQL baseline 未改写。
