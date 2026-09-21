# DIST-004 — 实现 `FakeOfficialAdapter`：能力、草稿、上传、排程、发布、指标和错误码模拟。

状态：`done`  
阶段：7（Distribution 抽象、Manual Export 和 Fake Adapter）  
Owner：`team/distribution`  
优先级：`critical` / `P0`

## 目标

实现无凭证、无网络的 `FakeOfficialAdapter`：能力、草稿、上传、排程、发布、指标和稳定错误码模拟。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `FOUND-009`
- `POLICY-001`
- `DIST-002`
- `DIST-003B`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `DIST-004.implementation`
- `DIST-004.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/publication-record.schema.json`
- `packages/contracts/jsonschema/delivery-attempt.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_dist_004.py`

## 实现规格

- `get_capability` 返回闭合 PublisherCapability；`create_draft`、`upload_media`、`schedule`、`publish` 使用 expected version 和租户范围，状态转换只在内存 fake 投影中发生。
- `publish` 生成符合 DeliveryAttempt/PublicationRecord Schema 的 `fake:official@v1` 结果、private synthetic external URL、simulated replay hash 和 publication event；不会读取 AccountConnection 或调用 HTTP。
- `get_metrics` 返回稳定的合成指标；`fail_next` 支持 `PLATFORM_RATE_LIMITED`、`PLATFORM_UNAVAILABLE` 等固定错误码，失败不写成功事实。
- 所有命令按 tenant/idempotency payload hash 重放；跨租户、过期状态和 stale version 被确定性拒绝，并保留审计摘要。
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

- `使用 FakeOfficialAdapter 读取能力并完成 draft、upload、schedule、publish、metrics 流程`

Then：

- `能力、状态转换、投递尝试、发布记录、指标和错误码可离线复现`
- `Policy/tenant/version/idempotency 边界有效，失败不会伪造发布成功`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/distribution tests/integration --maxfail=1
```

Gate：`dist_004_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
