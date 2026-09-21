# DIST-006A — 实现 Intent/Delivery 的幂等键和重复消费保护。

状态：`done`  
阶段：7（Distribution 抽象、Manual Export 和 Fake Adapter）  
Owner：`team/distribution`  
优先级：`critical` / `P0`

## 目标

实现 PublicationIntent/DeliveryAttempt 的幂等键和重复消费保护。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `FOUND-004B`
- `POLICY-001`
- `DIST-001`
- `DIST-005B`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `DIST-006A.implementation`
- `DIST-006A.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/publication-intent.schema.json`
- `packages/contracts/jsonschema/delivery-attempt.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_dist_006a.py`

## 实现规格

- `DeliveryIdempotencyService.accept_intent` 先校验 PublicationIntent Schema，再按 `(org_id, idempotency_key)` 和 intent id 的 payload hash 幂等；已接受 intent 不可被另一 payload 覆盖。
- `accept_attempt` 先要求同租户 intent 已接受，再按 `(org_id, intent_id, attempt_no)` 防止重复投递事实；相同 payload 可重放，不同状态/哈希返回 `DUPLICATE_DELIVERY_ATTEMPT`。
- `consume_event` 校验 EventEnvelope，按 event_id 和 tenant-scoped Idempotency-Key 去重；重复消费直接返回首次 handler 结果，不再次执行 handler，跨租户和冲突 payload 拒绝。
- 所有接受/消费动作保留 trace、actor、输入/输出哈希审计，不调用平台或网络。
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

- `重复提交同一 PublicationIntent、DeliveryAttempt 和 EventEnvelope`

Then：

- `相同 payload 重放原投影；同 intent/attempt_no 的不同 payload 和重复 event handler 被阻断`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/distribution tests/integration --maxfail=1
```

Gate：`dist_006a_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
