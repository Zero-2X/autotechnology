# DIST-006B — 实现上传状态、回查和 PublicationRecord 创建。

状态：`done`  
阶段：7（Distribution 抽象、Manual Export 和 Fake Adapter）  
Owner：`team/distribution`  
优先级：`critical` / `P0`

## 目标

实现上传状态回查和 PublicationRecord 创建，禁止成功状态回退。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `POLICY-001`
- `DIST-004`
- `DIST-006A`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `DIST-006B.implementation`
- `DIST-006B.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/publication-record.schema.json`
- `packages/contracts/jsonschema/delivery-attempt.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_dist_006b.py`

## 实现规格

- `PublicationReconciler.observe` 校验 DeliveryAttempt，按 uploaded/acknowledged/published/failed/unknown 生成或更新 PublicationRecord，并同步 attempt 外部引用和完成状态。
- 已发布/已移除的记录不能回退；unknown 必须携带原因并保持 unknown，不能被自动当作成功；观察来源限定 adapter/webhook/poll/manual。
- 相同回查幂等键重放原记录，跨租户 attempt、非法来源、未知原因和状态回退拒绝；每次回查追加 EventEnvelope 和审计摘要。
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

- `对同一 DeliveryAttempt 回查上传、发布或未知结果`

Then：

- `PublicationRecord/DeliveryAttempt 符合契约并同步外部引用；已发布状态不可回退`
- `未知结果保留 unknown 与原因，不伪造成功；重复回查按幂等键重放`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/distribution tests/integration --maxfail=1
```

Gate：`dist_006b_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
