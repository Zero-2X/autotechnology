# FOUND-004B — 实现业务状态与 Outbox 同事务提交及 OutboxDispatcher。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/foundation`  
优先级：`critical` / `P0`

## 目标

实现业务状态与 Outbox 同事务提交及 OutboxDispatcher。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-004A`

## 输入

- `packages/contracts/jsonschema/outbox-event.schema.json`：Outbox 持久化对象契约。
- `packages/contracts/events/event-envelope.schema.json`：发布给下游的不可变事件 envelope 契约。
- `packages/db/migrations/versions/20260916_found_004a_migration_baseline.py`：Alembic 基线和 expand/contract 入口。
- `TenantContext` 等价输入：`org_id`、`actor_type`、`actor_id`、`trace_id`、`Idempotency-Key`。

## 输出

- `infra/foundation/outbox.py`：事件 envelope、同事务状态写入、幂等和租约 Dispatcher。
- `packages/db/migrations/versions/20260916_found_004b_outbox.py`：真实 Alembic revision。
- `tests/contract/test_found_004b_outbox.py`、`tests/integration/test_found_004b_outbox.py`。
- `docs/foundation/FOUND-004B-EVIDENCE.yaml`：验证与副作用证据。

## 实现规格

`OutboxEvent(event_id, event_type, event_schema_version, occurred_at, org_id, trace_id, aggregate_type, aggregate_id, aggregate_version, actor_type, actor_id, idempotency_key, payload, payload_hash, published_at, attempt_count, last_error, status=pending|publishing|published|failed|dead_letter, available_at, lease_until, locked_by)`；`event_id` 全局唯一，组织内相同幂等键和相同 payload hash 重放返回原事件，不同 payload hash 返回 `IDEMPOTENCY_KEY_REUSED`。业务状态回调和 Outbox 插入必须由同一个 `BEGIN/COMMIT` 边界提交，任一失败整体回滚。Dispatcher 在 PostgreSQL 使用 `FOR UPDATE SKIP LOCKED` 领取，在 SQLite fixture 使用等价的短事务锁；成功标记 `published`，临时错误按指数退避写入 `failed`，达到最大尝试次数转 `dead_letter`。

实现约束：

- `payload_hash` 由规范化 JSON 计算，持久化 payload 不得包含凭证或 raw token。
- `dispatch_once(org_id=...)` 必须按租户过滤；发现事件存在但不属于当前租户时返回 `TENANT_SCOPE_VIOLATION`。
- publisher 只接收完整 envelope 和 `event_id`，不得由 Dispatcher 重新生成事件 ID；下游按 `event_id` 去重以满足 at-least-once。
- retry 使用 `available_at`、`attempt_count` 和有限最大退避；lease 到期的 `publishing` 事件可再次领取。

内部命令：`POST /internal/outbox/dispatch`（worker-only）。事件 envelope 必须含 `event_id、event_type、event_schema_version、trace_id、org_id、occurred_at、aggregate_type、aggregate_id、aggregate_version、payload_hash`。错误码：`OUTBOX_DUPLICATE`、`OUTBOX_PUBLISH_RETRYABLE`、`OUTBOX_DEAD_LETTER`、`IDEMPOTENCY_KEY_REUSED`、`INVALID_EVENT_ENVELOPE`、`TENANT_SCOPE_VIOLATION`。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/outbox-event.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移 revision：

- `packages/db/migrations/versions/20260916_found_004b_outbox.py`
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

- `执行 FOUND-004B 的公开用例或内部命令`

Then：

- `实现业务状态与 Outbox 同事务提交及 OutboxDispatcher。`
- `同一事务内业务状态和 outbox_events 同时提交；状态写失败或事件校验失败时两者均不可见。`
- `相同 org_id/idempotency_key/payload_hash 返回原 event_id；hash 不同返回 IDEMPOTENCY_KEY_REUSED；重复 event_id 返回 OUTBOX_DUPLICATE。`
- `Dispatcher 成功发布只标记一次 published；publisher 临时失败进入 failed 并指数退避，超过上限进入 dead_letter。`
- `租约到期后 publishing 事件可被另一个 worker 重新领取；跨 org_id 不能领取或发布。`
- `输出契约、审计事件和指定测试结果可复现。`

补充场景：

- 业务事务回滚时不得残留 outbox；重复 dispatch 同一 event_id 下游只收到一次语义事件。
- Dispatcher 崩溃后 `publishing` 事件在 `lease_until` 到期后可重新领取。
- 跨 org_id 查询或发布返回 `TENANT_SCOPE_VIOLATION`。
- 非法 event type、UUID、版本、时间戳、payload 或 hash 返回 `INVALID_EVENT_ENVELOPE`，不进入重试。
- publisher 抛出临时错误返回 `OUTBOX_PUBLISH_RETRYABLE`；达到上限返回 `OUTBOX_DEAD_LETTER`。

回滚：关闭 dispatcher feature flag；保留 pending 事件，恢复后从上次 lease 继续，不直接删除事件。

## 回滚与运行说明

- 关闭 dispatcher feature flag 后保留 `pending|failed|publishing` 事件；不得删除历史事件。
- 通过 `python -m alembic downgrade 20260916_found_004a` 回滚本任务新增表；已接受的旧 SQL baseline 不改写。
- synthetic SQLite fixture 不代表已连接真实 PostgreSQL；真实连接池、生产锁超时和平台发布由后续任务负责。

六类 GWT 必须覆盖：成功发布、重复 event_id、非法 envelope、权限/跨租户、下游不可用、lease 恢复与未知结果。

## 验证

```text
python -m pytest tests/contract tests/integration --maxfail=1
```

Gate：`found_004b_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡已完成：事务一致性、幂等、envelope 校验、租约恢复、重试/DLQ、未知结果保留租约、租户隔离和 worker-only dispatch 命令均已通过 synthetic SQLite 与 FastAPI 契约测试；未调用真实外部服务。
