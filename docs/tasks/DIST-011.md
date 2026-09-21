# DIST-011 — 定义 `WebhookPort` 和 `WebhookReceipt`：验签、外部事件去重、Schema 校验、回放和死信；M1 只实现 Fake/fixture ingress，不接真实平台 Webhook。

状态：`done`  
阶段：7（Distribution 抽象、Manual Export 和 Fake Adapter）  
Owner：`team/distribution`  
优先级：`critical` / `P0`

## 目标

定义 `WebhookPort` 和 `WebhookReceipt`：验签、外部事件去重、Schema 校验、回放和死信；M1 只实现 Fake/fixture ingress，不接真实平台 Webhook。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `POLICY-001`
- `DIST-010`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `DIST-011.implementation`
- `DIST-011.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/webhook-receipt.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_dist_011.py`

## 实现规格

- 在 `modules/distribution/ports.py` 定义独立 `WebhookPort` Protocol；`FakeWebhookPort` 只接受内存 fixture 事件和测试密钥，不使用平台 SDK、HTTP、真实账号或生产凭证。
- ingress 使用规范 JSON 的 HMAC-SHA256 fixture 签名，先验签，再校验 EventEnvelope Schema 和 `payload.org_id == TenantContext.org_id`；原始载荷仅以 `private://webhook/...` 引用出现在 `WebhookReceipt`。
- 以 `(org_id, platform_id, external_event_id)` 去重；相同外部事件与不同 payload hash 冲突，重复事件输出 `webhook.deduplicated` 且不再次调用 handler。
- handler 失败保留已验签 payload；达到 `max_attempts` 后进入 `dead_letter` 并输出 `webhook.dead_lettered`。只有已验签且通过 Schema 的处理失败/死信收据可在显式人工确认后重放。
- 每个 WebhookReceipt 和控制事件均经过现有 JSON Schema 校验；命令按租户、幂等键和输入哈希去重，审计只保留输入/输出哈希，不记录 fixture 密钥或原始内容。
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

- `执行 DIST-011 的公开用例或内部命令`

Then：

- `定义 `WebhookPort` 和 `WebhookReceipt`：验签、外部事件去重、Schema 校验、回放和死信；M1 只实现 Fake/fixture ingress，不接真实平台 Webhook。`
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- 正确 fixture 签名与合法 EventEnvelope 生成 `processed` WebhookReceipt；同一外部事件重复到达只生成去重结果，handler 仅调用一次。
- 无效签名、非法 Schema 和跨租户 EventEnvelope 生成 `rejected` 收据与 `webhook.rejected`，且不能进入重放。
- 已验签事件的 handler 连续失败达到上限后进入 `dead_letter`；显式人工重放成功后更新为 `processed`，全过程不触发平台副作用。
- 相同外部事件 ID 携带不同 payload、同一命令幂等键携带不同输入、跨租户读取或重放均拒绝。

回滚：

- 停用 Fake fixture ingress，保留既有 WebhookReceipt、去重、拒绝、死信和审计事实；不接入任何真实 Webhook endpoint。
- 本 revision 不创建业务表，回退执行 `python -m alembic downgrade 20260919_found_dist_010`；内存 fixture 状态可直接丢弃。

## 验证

```text
python -m pytest tests/unit/distribution tests/integration --maxfail=1
```

Gate：`dist_011_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
