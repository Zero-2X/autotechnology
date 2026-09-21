# IAM-CORE-001 — 建立 dev identity、organization、actor context 和最小 RBAC middleware，供 synthetic 审批使用。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/iam`  
优先级：`critical` / `P0`

## 目标

建立 dev identity、organization、actor context 和最小 RBAC middleware，供 synthetic 审批使用。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-004A`
- `FOUND-005`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `IAM-CORE-001.implementation`
- `IAM-CORE-001.tests`
- `audit_evidence`

## 实现规格

数据对象：

- `DevIdentity(id, org_id, subject, display_name, status=active|disabled, created_at)`；`(org_id, subject)` 唯一。
- `Organization(id, slug, name, status=active|suspended)`；slug 全局唯一。
- `ActorContext(org_id, actor_id, roles, permissions, trace_id)`；每次请求由 middleware 注入，不允许客户端覆盖 `org_id`/`actor_id`。
- `RoleBinding(org_id, actor_id, role)`；首批角色 `owner|editor|reviewer|operator|viewer`。

公开接口：`POST /internal/dev-identities`、`GET /internal/me`、`POST /internal/role-bindings`；错误码固定为 `TENANT_CONTEXT_REQUIRED`、`FORBIDDEN`、`DUPLICATE_BINDING`。

不变量：所有查询自动附加 `org_id`；无绑定角色默认拒绝写操作；`owner` 可管理绑定，`reviewer` 不能审批自己创建的对象；角色变更写入审计日志且不可覆盖历史记录。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/internal-iam.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_iam_core_001.py`
## 目录边界

拥有目录：

- `modules/iam`

允许目录：

- `modules/iam`
- `apps/api`
- `tests/security`
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

- `执行 IAM-CORE-001 的公开用例或内部命令`

Then：

- `建立 dev identity、organization、actor context 和最小 RBAC middleware，供 synthetic 审批使用。`
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- 给定 actor 属于 org-A，读取 org-B 资源时返回 `403 TENANT_SCOPE_VIOLATION` 且不泄露资源是否存在。
- 重复提交相同 `Idempotency-Key` 和 payload 返回第一次响应；相同 key 不同 payload 返回 `409 IDEMPOTENCY_KEY_REUSED`。
- disabled identity 调用任意写接口返回 `403 ACTOR_DISABLED`。


## 验收证据

- `modules/iam` 提供无外部依赖的 Organization、DevIdentity、ActorContext、RoleBinding 和租户隔离 RBAC 服务。
- `apps/api/main.py` 注册隐藏于当前 OpenAPI 基线之外的 synthetic `/internal/dev-identities`、`/internal/me` 与 `/internal/role-bindings` 接口，缺少租户上下文显式拒绝。
- 单元与集成测试覆盖幂等键复用、跨租户访问、disabled actor、owner 授权、重复绑定和审计记录；无真实凭据或平台调用。

## 回滚与运行说明

- 通过任务级 feature flag 关闭新命令；已提交的业务事实和审计记录不删除。
- 迁移按 expand/contract 顺序执行；验证失败时停止后续任务，保留兼容字段，不执行破坏性回滚。
- 如产生可重试任务，先暂停对应队列，再按原幂等键重放；任何外部未知结果必须转人工核查。

## 验证

```text
python -m pytest tests/unit/iam tests/integration --maxfail=1
```

Gate：`iam_core_001_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
