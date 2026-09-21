# APPROVAL-001 — 实现人工审批台：版本 diff、证据面板、风险原因、批注、任务分派、审批期限和 override 过期时间。

状态：`done`  
阶段：4（Production、Localization、QA、Policy 和 Approval）  
Owner：`team/approval`  
优先级：`critical` / `P0`

## 目标

实现人工审批台：版本 diff、证据面板、风险原因、批注、任务分派、审批期限和 override 过期时间。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `IAM-CORE-001`
- `WORKFLOW-CORE-002`
- `CANON-002`
- `POLICY-001`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `APPROVAL-001.implementation`
- `APPROVAL-001.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/approval.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_approval_001.py`

## 实现规格

- `ApprovalDeskService.request` 按租户创建不可变 Approval 投影，冻结 aggregate type/id/version、PolicySnapshot、证据 refs、风险原因、输入快照哈希、版本 diff、批注、分派人、审批期限和 quorum；同幂等键重放原申请。
- `assign`、`comment` 和 `decide` 均校验租户与 expected version；审批决策追加 `ApprovalDecision`，同一 reviewer 不得重复决策，rejected/withdrawn 立即终止，approved 只有达到 quorum 才将 Approval 标记 approved。
- `expire` 在 expires_at 到期或 override_expires_at 到期后将 pending/approved 结果切换为 expired/revoked，后续分发不可继续；override 只能设置未来时间并保留原审批证据。
- `view` 返回稳定的 diff、证据面板、风险原因、批注、分派和期限视图，不修改业务事实；所有 Approval/Decision 输出通过对应 Schema，审计记录 actor、trace、输入/输出哈希和拒绝原因。

补充场景：

- Given pending Approval、单人 quorum 和匹配 expected version，When reviewer approved，Then 追加 ApprovalDecision 并标记 approved。
- Given quorum=2，When 第一位 reviewer approved，Then 保持 pending；第二位不同 reviewer approved 后才完成。
- Given reviewer rejected、审批过期或 expected version 过期，When 决策，Then 阻断并返回稳定错误/状态，不写入重复事实。
- Given 输入含版本差异、Evidence 和风险原因，When 打开审批台，Then view 返回确定性 diff、证据 refs、风险原因、批注和截止时间。
- Given 其他租户 Approval，When 查询或决策，Then 返回 `TENANT_SCOPE_VIOLATION`，不泄漏内容。

## 回滚

- 停止新的 Approval 命令并保留已经追加的 ApprovalDecision、批注和审计记录；不删除历史批准证据。
- 迁移为无业务表修订，后续持久化使用追加兼容迁移。
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

- `执行 APPROVAL-001 的公开用例或内部命令`

Then：

- `实现人工审批台：版本 diff、证据面板、风险原因、批注、任务分派、审批期限和 override 过期时间。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/approval tests/integration --maxfail=1
```

Gate：`approval_001_acceptance`

## 外部依赖

- 无

## 开工前细化

已按 Approval/Decision 追加状态、diff/证据/risk view、批注分派、quorum、期限、override、expected version、幂等和租户失败路径细化并完成实现；状态为 `done`。
