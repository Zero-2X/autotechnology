# OAUTH-001B — 实现真实 OAuth 回调的 State/PKCE、redirect URI 和 CSRF 校验；不在回调中直接发布内容。

状态：`planned`  
阶段：8（真实 AccountConnection、OAuth 和首个平台连接）  
Owner：`team/distribution_oauth`  
优先级：`normal` / `M2`

## 目标

实现真实 OAuth 回调的 State/PKCE、redirect URI 和 CSRF 校验；不在回调中直接发布内容。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-009`
- `DIST-010`
- `OAUTH-001A`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `OAUTH-001B.implementation`
- `OAUTH-001B.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/oauth-authorization-session.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/planned/oauth_001b.sql`
## 目录边界

拥有目录：

- `modules/distribution/oauth`

允许目录：

- `modules/distribution/oauth`
- `apps/api`
- `adapters/contract`
- `adapters/platforms`
- `deploy/environments/staging`
- `tests/security`
- `packages/contracts`
- `packages/db/migrations`
- `tests/unit`
- `tests/integration`
- `tests/contract`

禁止目录：

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

- `执行 OAUTH-001B 的公开用例或内部命令`

Then：

- `实现真实 OAuth 回调的 State/PKCE、redirect URI 和 CSRF 校验；不在回调中直接发布内容。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/distribution_oauth tests/integration --maxfail=1
```

Gate：`oauth_001b_acceptance`

## 外部依赖

- `EXT-ACCOUNT-001`

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
