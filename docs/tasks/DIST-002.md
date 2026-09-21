# DIST-002 — 在阶段 1 最小契约基础上补齐四个 Port：`ConnectionPort`、`PublisherPort`、`InboxPort`、`MetricsPort`；不要把授权、发布、客服混成一个适配器。

状态：`done`  
阶段：7（Distribution 抽象、Manual Export 和 Fake Adapter）  
Owner：`team/distribution`  
优先级：`critical` / `P0`

## 目标

在 FOUND-010 的最小 Port 形状上提供 Distribution 侧的独立 Port 组装和 publisher capability 快照登记；不要把授权、发布、收件箱和指标混成一个适配器。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `FOUND-010`
- `POLICY-001`
- `DIST-001`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `DIST-002.implementation`
- `DIST-002.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/publisher-capability.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_dist_002.py`

## 实现规格

- `DistributionPortSet` 接收四个独立对象，分别要求 `inspect`、`publish`、`receive`、`emit` 方法；同一对象承担多个职责时返回 `PORT_RESPONSIBILITIES_MIXED`。
- `PublisherCapabilityRegistry` 按租户登记 Schema 闭合的 capability `(id, version)`；版本事实不可覆盖，重复幂等键按 payload hash 重放，跨租户读取拒绝。
- capability 登记追加 `publisher.capability.registered` EventEnvelope 和审计摘要；registry 不加载 SDK、不读取凭证、不发起 HTTP。
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

- `使用四个独立端口构造 DistributionPortSet，并登记一个 PublisherCapability`

Then：

- `四个职责可分别注入；混合适配器和缺少方法的对象被拒绝`
- `capability 版本不可变、幂等重放稳定、事件符合 EventEnvelope 且租户隔离`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/distribution tests/integration --maxfail=1
```

Gate：`dist_002_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
