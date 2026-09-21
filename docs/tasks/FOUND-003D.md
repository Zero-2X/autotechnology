# FOUND-003D — 建立 PostgreSQL `task_jobs` 队列表和 polling 配置；首个纵向切片不依赖 Redis。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/foundation`  
优先级：`critical` / `P0`

## 目标

建立 PostgreSQL `task_jobs` 队列表和 polling 配置；首个纵向切片不依赖 Redis。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-003A`
- `FOUND-003B`

## 输入

- `docs/foundation/postgresql-foundation-baseline-v1.yaml`：FOUND-003A 的 PostgreSQL 非秘密基线。
- `packages/contracts/jsonschema/task-job.schema.json`：TaskJob 对象契约。
- `TASK_QUEUE_NAME`、`TASK_QUEUE_POLL_INTERVAL_SECONDS`、`TASK_QUEUE_POLL_BATCH_SIZE`：可选运行时配置；缺失时使用确定性默认值。

## 输出

- `infra/foundation/task_queue.py`：polling 配置、TaskJob 记录和 DB-API 队列 seam。
- `docs/foundation/task-job-polling-baseline-v1.yaml`：无秘密队列/polling 基线。
- `deploy/environments/dev/task-queue.env.example`、`deploy/environments/staging/task-queue.env.example`：无凭证配置模板。
- `packages/db/migrations/versions/20260916_found_003d_task_jobs.sql`：`task_jobs` 表、唯一键和可用索引。
- `tests/contract/test_found_003d_task_jobs.py`、`tests/integration/test_found_003d_polling_config.py`：专项契约和 fixture 测试。
- `docs/foundation/FOUND-003D-EVIDENCE.yaml`：验证和副作用证据。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/task-job.schema.json`
- `packages/contracts/jsonschema/task-queue-config.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260916_found_003d_task_jobs.sql`
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

- `执行 FOUND-003D 的公开用例或内部命令`

Then：

- `task_jobs` 迁移可重复执行，且以 `(org_id, job_type, idempotency_key)` 拒绝重复事实；任务正文只保存 `private://` 引用。
- `PollingSettings` 从非秘密环境变量生成确定性配置，默认使用 PostgreSQL polling，明确 `redis_required=false`。
- `TaskJobQueue` 在 DB-API fixture 上可幂等入队并按 `available_at/created_at/id` 稳定读取 queued 任务；不执行 claim、lease、retry、DLQ 或 Outbox。
- `输出契约、审计证据和指定测试结果可复现；不打开 PostgreSQL/Redis 网络连接。`

补充场景：

- Given 未设置队列环境变量，When 解析 `PollingSettings`，Then 使用 `queue_name=default`、`poll_interval_seconds=5`、`batch_size=10`，且 `redis_required` 为 `false`。
- Given polling interval 或 batch size 为零、负数或非整数，When 解析配置，Then 确定性拒绝且不泄漏任何凭证。
- Given 同一租户以相同 `(job_type, idempotency_key)` 重复提交相同 payload，When 入队，Then 返回同一 Job，不创建副本。
- Given 同一幂等键提交不同 payload，When 入队，Then 返回冲突；跨租户相同键不冲突。
- Given 多个 queued 任务，When `poll_ready`，Then 只读取到期任务，按 `available_at`、`created_at`、`id` 稳定排序，且不改变状态。
- Given Redis 未配置，When 运行队列 fixture，Then PostgreSQL polling seam 仍可入队和读取；不得尝试 Redis 网络连接。

## 验证

```text
python -m pytest tests/contract tests/integration --maxfail=1
```

Gate：`found_003d_acceptance`

## 外部依赖

- 无

## 实现规格

1. `infra/foundation/task_queue.py` 只使用标准库和注入的 DB-API connection；`PollingSettings` 解析 `TASK_QUEUE_NAME`、`TASK_QUEUE_POLL_INTERVAL_SECONDS` 和 `TASK_QUEUE_POLL_BATCH_SIZE`，默认值分别为 `default`、`5`、`10`。
2. `PollingSettings.as_contract()` 必须声明 `backend=postgresql`、`eligible_status=queued`、`ordering=[available_at,created_at,id]`、`redis_required=false` 和 `credentials_in_repository=false`；配置哈希只基于非秘密字段。
3. `TaskJobQueue.enqueue()` 只创建 `status=queued` 的运行控制记录，要求 UUID `org_id/aggregate_id`、`private://` payload 引用、trace/idempotency key 和正数版本/尝试上限；正文不写入数据库。
4. 入队幂等键按 `(org_id, job_type, idempotency_key)` 隔离，并绑定命令 payload hash；相同命令返回原 Job，不同命令抛出 `TaskQueueConflictError`。
5. `TaskJobQueue.poll_ready()` 仅按租户、队列、`status=queued` 和 `available_at <= now` 读取，按 `available_at/created_at/id` 升序返回，不更新状态、不领取租约、不访问 Redis。
6. `20260916_found_003d_task_jobs.sql` 使用可重复执行的 `CREATE ... IF NOT EXISTS`，创建 `task_jobs`、幂等唯一键、租户/队列 polling 索引和 aggregate 查询索引；不创建 `task_failures`、Outbox 或业务事实表。
7. 基线、JSON Schema、dev/staging 模板和测试必须明确 SQLite DB-API 仅为无网络 fixture，不代表真实 PostgreSQL 已连接；真实驱动、连接池、claim/lease、重试、死信和 Outbox 由后续任务实现。

## 实施证据

- 配置实现：`infra/foundation/task_queue.py`。
- 无秘密基线：`docs/foundation/task-job-polling-baseline-v1.yaml`。
- 配置契约：`packages/contracts/jsonschema/task-queue-config.schema.json`；TaskJob 契约补充 `payload_hash` 并纳入 foundation union。
- 迁移：`packages/db/migrations/versions/20260916_found_003d_task_jobs.sql`。
- 专项契约测试：`tests/contract/test_found_003d_task_jobs.py`。
- DB-API polling 测试：`tests/integration/test_found_003d_polling_config.py`。

## 回滚与运行说明

- 本卡只新增队列表/polling 基线和无网络 fixture；回滚使用受审查的反向迁移，不删除 FOUND-003A/003B 基线，也不修改业务事实。
- 未设置队列环境变量时使用安全默认值；未配置 Redis 不影响 PostgreSQL polling seam。
- 该 fixture 不提供真实 PostgreSQL 可用性证明；真实数据库探测和连接池由后续持久化任务负责。

## 开工前细化

本卡已从 bootstrap 任务卡细化为可执行行为；`in_progress` 阶段只允许实现 PostgreSQL queue/polling seam。claim、lease、超时、失败、重试、死信、Outbox 和 Redis 属于后续精确任务。
