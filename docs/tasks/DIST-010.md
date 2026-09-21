# DIST-010 — 用 Fake Adapter 完成模拟发布、失败、死信、重放和重复消费测试。

状态：`done`  
阶段：7（Distribution 抽象、Manual Export 和 Fake Adapter）  
Owner：`team/distribution`  
优先级：`critical` / `P0`

## 目标

用 Fake Adapter 完成模拟发布、失败、死信、重放和重复消费测试。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `POLICY-001`
- `DIST-004`
- `DIST-006C`
- `DIST-009`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `DIST-010.implementation`
- `DIST-010.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/delivery-attempt.schema.json`
- `packages/contracts/jsonschema/publication-record.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_dist_010.py`

## 实现规格

- `FakeDeliveryWorkflowService.publish` 组合 `FakeOfficialAdapter`、`RetryPolicyService`、`DeliveryIdempotencyService` 和 `PublicationReconciler`，只使用 dev/staging/prod 的确定性内存状态，不读取凭证、不发起 HTTP 请求。
- 成功路径先接受同租户 `PublicationIntent`、创建 Fake draft，再以 Fake Adapter 发布并回查 `PublicationRecord`；输出 `provider_mode=fake`、`simulated=true`，并把同一 `EventEnvelope` 交给重复消费保护。
- Fake Adapter 的暂时错误按 `RetryPolicyService` 分类并返回可重试投影；达到 `max_attempts` 后调用 `DeliveryDeadLetterService` 生成 `dead_letter` 和唯一 `support_escalation` HumanTask。
- `replay` 仅创建带原始 `idempotency_key` 和 `provider_idempotency_key` 的人工重放计划，必须显式确认且不触发 adapter 副作用；输入变更或跨租户访问拒绝。
- 所有 `DeliveryAttempt`、`PublicationRecord`、`EventEnvelope` 输出经过现有 JSON Schema 校验，命令和事件按租户、trace、actor、输入哈希记录审计。
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

- `执行 DIST-010 的公开用例或内部命令`

Then：

- `用 Fake Adapter 完成模拟发布、失败、死信、重放和重复消费测试。`
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- Fake 发布成功必须有 `publication_record.status=published` 且 `result_snapshot.simulated=true`；同一事件重复消费只执行一次 handler。
- 429/5xx 对应的 Fake 暂时失败返回 `retry_pending`，不生成外部副作用；达到重试上限进入 `dead_letter` 并创建一条支持升级 HumanTask。
- 死信只能用原始幂等键和显式人工确认生成重放计划；重放计划必须保留 provider key，`side_effect_triggered=false`。
- 不同租户的 Intent、Attempt 或事件一律拒绝；同一幂等键的不同输入返回 `IDEMPOTENCY_KEY_REUSED`。

回滚：

- 停用 Fake workflow 入口，保留已有 Fake draft、DeliveryAttempt、PublicationRecord、HumanTask 和审计事实；不触及任何平台账号或凭证。
- 本 revision 不创建业务表，回退执行 `python -m alembic downgrade 20260919_found_dist_009`；服务对象可直接丢弃内存状态。

## 验证

```text
python -m pytest tests/unit/distribution tests/integration --maxfail=1
```

Gate：`dist_010_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
