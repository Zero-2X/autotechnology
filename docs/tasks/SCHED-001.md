# SCHED-001 — （前置依赖：`GEO_REGION-CORE-001`）定义 UTC 存储、按不可变 `RegionProfileVersion` 计算时区、DB lease/advisory lock 和唯一排程幂等键；重启不重复触发，暂停后不补发旧副作用任务。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/scheduler`  
优先级：`critical` / `P0`

## 目标

（前置依赖：`GEO_REGION-CORE-001`）定义 UTC 存储、按不可变 `RegionProfileVersion` 计算时区、DB lease/advisory lock 和唯一排程幂等键；重启不重复触发，暂停后不补发旧副作用任务。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-004C`
- `GEO_REGION-CORE-001`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `SCHED-001.implementation`
- `SCHED-001.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/scheduler-job.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_sched_001.py`
## 目录边界

拥有目录：

- `apps/scheduler`

允许目录：

- `apps/scheduler`
- `apps/worker`
- `tests/integration`
- `packages/contracts`
- `packages/db/migrations`
- `tests/unit`
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

- `执行 SCHED-001 的公开用例或内部命令`

Then：

- `（前置依赖：`GEO_REGION-CORE-001`）定义 UTC 存储、按不可变 `RegionProfileVersion` 计算时区、DB lease/advisory lock 和唯一排程幂等键；重启不重复触发，暂停后不补发旧副作用任务。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/scheduler tests/integration --maxfail=1
```

Gate：`sched_001_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。

## 实现规格

SchedulerJob 以 UTC 时间戳持久化，保存不可变 RegionProfileVersion 引用；SchedulerService 只按该版本的 IANA 时区计算下一次触发。claim_due 使用短租约、租约过期可重领、组织隔离和 Idempotency-Key；pause 后不补发旧 occurrence，resume 从当前时刻重新计算。

## 补充场景

- 同一租户同一命令键重复执行返回同一结果，载荷变化返回 IDEMPOTENCY_KEY_REUSED。
- 两个 worker 不能同时持有同一 occurrence 的 lease；过期后允许新 worker 接管。

## 回滚

停止 scheduler 新领取，保留 active/paused job 和已记录 occurrence；恢复后从 UTC next_run_at 继续。

## Implementation Evidence

- Implementation: pps/scheduler/service.py provides UTC scheduling, immutable region-version timezone resolution, short leases, advisory-lock equivalent, idempotency and pause/resume semantics.
- Tests: 	ests/unit/scheduler/test_service.py.
- Migration: packages/db/migrations/versions/20260918_sched_001.py.
