# APPROVAL-002 — 实现 `approval_decisions` 明细：每个审批人一条不可变投票，`(approval_id, reviewer_id)` 唯一；创建人不能审批自己的内容，R3/R4 必须由两名不同审批人达到 quorum。

状态：`done`  
阶段：4（Production、Localization、QA、Policy 和 Approval）  
Owner：`team/approval`  
优先级：`critical` / `P0`

## 目标

实现 `approval_decisions` 明细：每个审批人一条不可变投票，`(approval_id, reviewer_id)` 唯一；创建人不能审批自己的内容，R3/R4 必须由两名不同审批人达到 quorum。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `IAM-CORE-001`
- `CANON-002`
- `APPROVAL-001`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `APPROVAL-002.implementation`
- `APPROVAL-002.tests`
- `audit_evidence`

## 实现规格

`ApprovalDecision` 字段：`id`、`org_id`、`approval_id`、`reviewer_id`、`decision=approve|reject|request_changes`、`comment`、`created_at`、`evidence_refs[]`。数据库唯一约束 `(approval_id, reviewer_id)`，决策记录不可更新/删除；聚合 `Approval.status` 由明细重算。R0/R1 quorum=1，R2 quorum=1，R3/R4 quorum=2 且 reviewer_id 必须不同；创建者 reviewer_id 一律拒绝。接口 `POST /internal/approvals/{approval_id}/decisions` 要求 reviewer 角色与 `If-Match`。

- 当前公共契约以 `approval-decision.schema.json` 为准：decision 使用 `approved|rejected|withdrawn`，评论和 evidence refs 通过 ApprovalDesk 的不可变 metadata 视图返回；每个 reviewer 只允许一条 Decision。
- `ApprovalDeskService` 接收可替换 ReviewerAuthorizationPort；Port 拒绝或异常均返回 `FORBIDDEN`，创建者始终返回 `SELF_APPROVAL_FORBIDDEN`。提交 R3/R4 申请时自动将 quorum 提升为 2，不能被单人参数绕过。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/approval.schema.json`
- `packages/contracts/jsonschema/approval-decision.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_approval_002.py`
## 目录边界

拥有目录：

- `modules/approval`

允许目录：

- `modules/approval`
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

- `执行 APPROVAL-002 的公开用例或内部命令`

Then：

- `实现 `approval_decisions` 明细：每个审批人一条不可变投票，`(approval_id, reviewer_id)` 唯一；创建人不能审批自己的内容，R3/R4 必须由两名不同审批人达到 quorum。`
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- 同一 reviewer 重复投票返回 `DUPLICATE_DECISION`，原记录保持不变。
- R3/R4 只有一票 approve 时聚合状态仍为 `pending`；第二名不同 reviewer approve 后才变为 `approved`。
- 创建人或无 reviewer 权限调用返回 `SELF_APPROVAL_FORBIDDEN`/`FORBIDDEN`，不产生明细。


## 回滚与运行说明

- 通过任务级 feature flag 关闭新命令；已提交的业务事实和审计记录不删除。
- 迁移按 expand/contract 顺序执行；验证失败时停止后续任务，保留兼容字段，不执行破坏性回滚。
- 如产生可重试任务，先暂停对应队列，再按原幂等键重放；任何外部未知结果必须转人工核查。

## 验证

```text
python -m pytest tests/unit/approval tests/integration --maxfail=1
```

Gate：`approval_002_acceptance`

## 外部依赖

- 无

## 开工前细化

已按公共 Decision 契约、reviewer Port、角色拒绝、创建人隔离、R3/R4 双人 quorum、唯一 reviewer 投票和幂等路径细化并完成实现；状态为 `done`。
