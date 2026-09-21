# DIST-005B — 实现配额、Retry-After、错误分类和人工升级策略。

状态：`done`  
阶段：7（Distribution 抽象、Manual Export 和 Fake Adapter）  
Owner：`team/distribution`  
优先级：`critical` / `P0`

## 目标

实现租户范围的配额、Retry-After、错误分类和人工升级信号；策略本身不执行重试副作用。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `FOUND-004D`
- `POLICY-001`
- `DIST-005A`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `DIST-005B.implementation`
- `DIST-005B.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/delivery-attempt.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_dist_005b.py`

## 实现规格

- `RetryPolicyService.reserve` 按租户时间窗限制投递单位，返回剩余配额、窗口结束时间和 Retry-After；同一幂等键重放不重复消耗。
- `classify` 将固定错误码区分为 transient、exhausted、deterministic、unknown；仅 transient 且未达到 max_attempts 时给出可重试信号，未知结果和耗尽结果给出人工升级信号。
- 所有判断记录稳定审计摘要；人工升级追加 `distribution.delivery.manual_escalation` EventEnvelope，不创建隐式重试任务或调用平台。
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

- `为租户预留投递配额并分类一次 DeliveryAttempt 错误`

Then：

- `配额超限返回 Retry-After，错误分类和 max_attempts 决定是否可重试`
- `未知结果/耗尽结果输出人工升级信号；重复消费、跨租户和无效输入被拒绝`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/distribution tests/integration --maxfail=1
```

Gate：`dist_005b_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
