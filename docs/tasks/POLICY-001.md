# POLICY-001 — 实现确定性 Policy Gate：风险等级、来源权利、区域规则、审批要求和发布模式。

状态：`done`  
阶段：4（Production、Localization、QA、Policy 和 Approval）  
Owner：`team/policy`  
优先级：`critical` / `P0`

## 目标

实现确定性 Policy Gate：风险等级、来源权利、区域规则、审批要求和发布模式。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-004`
- `GOV-005`
- `GEO_REGION-CORE-001`
- `CANON-002`
- `QA-001`
- `QA-002`
- `QA-003`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `POLICY-001.implementation`
- `POLICY-001.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/policy-snapshot.schema.json`
- `packages/contracts/jsonschema/policy-decision.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_policy_001.py`

## 实现规格

- `PolicyGateService.evaluate` 只读取同租户或全局的 `PolicySnapshot` 和调用方提供的事实投影，输出符合 `policy-decision.schema.json` 的确定性 `PolicyDecision`；不修改 QA、Rights、Region、Approval 或 Distribution 事实，不调用网络、模型或平台。
- 先校验 PolicySnapshot Schema、租户范围、subject、active 状态、effective/expires/review_due 时间和 `snapshot_hash`；过期/撤回直接 deny，到期复核切换 manual_review。输入的 `risk_level` 按 R0–R4 最高等级聚合，R3/R4 阻断副作用，未知风险至少按 R2 并人工复核。
- `qa_status`、`rights_allowed`、`region_decision`、`approval_quorum/approvals`、`release_level/release_mode`、`account_state`、`data_processing_allowed` 和 `model_allowed` 分别映射到 content/region/distribution/account/data_processing/model policy；deny 优先于 manual_review，manual_review 优先于 allow。
- 发布模式遵循 release-level 投影：`architecture_mvp` 仅允许 `manual_export`/`simulation`，`distribution_pilot` 允许 `manual_export`/`simulation`/`draft_only`，`scale` 才允许 `authorized_api`。账号未知、外部结果未知或审批不足不得自动放行。
- 决策包含稳定 reasons、Policy snapshot/version、evaluated/expires 时间和 `decision_hash`；同租户同幂等键重放原决策，输入不同返回 `IDEMPOTENCY_KEY_REUSED`，审计记录 actor、trace、输入/输出哈希。

补充场景：

- Given active tenant PolicySnapshot、QA passed、Rights/Region 允许、审批满足且发布模式在 release-level 白名单内，When 评估，Then 返回 `allow`。
- Given QA failed、Rights/Region deny、过期 Snapshot、R3/R4 风险或架构 MVP 请求真实平台模式，When 评估，Then 返回 `deny` 并列出稳定拒绝原因。
- Given 风险/账号/外部结果未知、Snapshot 到 review_due 或审批不足，When 评估，Then 返回 `manual_review`，不得创建副作用。
- Given 其他租户 Snapshot 或 subject 不匹配，When 评估，Then 返回 `TENANT_SCOPE_VIOLATION`，不泄漏 Snapshot 内容。

## 回滚

- 停止新的 Policy Gate 评估并保留已经产生的 PolicyDecision 审计；不删除或修改历史 PolicySnapshot。
- 迁移为无业务表修订，后续决策持久化使用追加兼容迁移。
## 目录边界

拥有目录：

- `modules/policy`

允许目录：

- `modules/policy`
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

- `执行 POLICY-001 的公开用例或内部命令`

Then：

- `实现确定性 Policy Gate：风险等级、来源权利、区域规则、审批要求和发布模式。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/policy tests/integration --maxfail=1
```

Gate：`policy_001_acceptance`

## 外部依赖

- 无

## 开工前细化

已按版本快照、风险聚合、QA/Rights/Region/Approval/Release/Account/Data/Model 门禁、拒绝优先级、幂等和租户失败路径细化并完成实现；状态为 `done`。
