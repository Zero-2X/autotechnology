# FOUND-003C — 配置 Redis，仅用于缓存、短锁和速率限制；Redis 不承担事实数据。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/foundation`  
优先级：`high` / `P1`

## 目标

配置 Redis，仅用于缓存、短锁和速率限制；Redis 不承担事实数据。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-013`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `FOUND-003C.implementation`
- `FOUND-003C.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/foundation.schema.json`
- `packages/contracts/jsonschema/redis-config.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_found_003c_redis.py`
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

- `执行 FOUND-003C 的公开用例或内部命令`

Then：

- `配置 Redis，仅用于缓存、短锁和速率限制；Redis 不承担事实数据。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/contract tests/integration --maxfail=1
```

Gate：`found_003c_acceptance`

## 外部依赖

- 无

## 实现规格

1. Redis 只提供可替换的缓存、短锁和速率限制 Port；不得成为任务、业务状态、审计或对象正文的唯一事实源。
2. Redis 配置必须使用非秘密环境变量快照；连接器、真实网络探测和生产凭证由本任务之外的部署/适配器流程负责。
3. Redis 不得作为 `FOUND-003D` PostgreSQL polling 队列的前置依赖；首个纵向切片在 Redis 缺失时仍必须可启动、可测试和可回放。
4. 本任务的迁移只记录 Redis 能力/策略基线，不创建业务事实表，不复制 `task_jobs`、Outbox 或审计事实。
5. 测试只允许使用 Fake Redis 或内存替身，必须覆盖配置缺失、租户隔离、TTL/锁释放和限流拒绝；不得调用真实 Redis。

## 实施证据

- 本卡保持 `planned`，直到 Redis Port、Fake 实现、配置基线、迁移和专项测试由本卡单独交付。
- `FOUND-003D` 不等待本卡；其 PostgreSQL `task_jobs` 队列和 polling 配置独立验收。

## 回滚与运行说明

- Redis 未配置时，调用方必须使用本地替身或明确的 no-op 策略；不得把 Redis 不可用误报为 PostgreSQL 队列不可用。
- 迁移和配置回滚不得删除 `task_jobs`、业务状态、Outbox 或审计数据。

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。

## 验收证据

- `infra/foundation/redis.py` 提供 `CachePort`、`LockPort`、`RateLimitPort` 和 `FakeRedis`，不引入 Redis SDK、网络连接或事实表。
- `RedisSettings` 输出脱敏配置快照并拒绝 URL 用户信息；专项测试覆盖租户隔离、TTL、锁 token 所有权与窗口限流。
- PostgreSQL 队列、Outbox、AuditLog、对象正文和业务版本不调用 Redis；缺少 Redis 时使用 Fake 或 no-op 策略。
