# AGENT-CORE-005A — 基于 AgentRunner 实现 Planner Agent；只输出结构化 Topic/Workflow Plan，不调用发布、授权或外部副作用工具。

状态：`done`  
阶段：4（Production、Localization、QA、Policy 和 Approval）  
Owner：`team/agent`  
优先级：`critical` / `P0`

## 目标

基于 AgentRunner 实现 Planner Agent；只输出结构化 Topic/Workflow Plan，不调用发布、授权或外部副作用工具。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `AGENT-CORE-002`
- `AGENT-CORE-004`
- `WORKFLOW-CORE-001`
- `TOPIC-004`
- `CANON-002`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `AGENT-CORE-005A.implementation`
- `AGENT-CORE-005A.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/agent-run.schema.json`
- `packages/contracts/jsonschema/planner-input.schema.json`
- `packages/contracts/jsonschema/planner-output.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_agent_core_005a.py`
## 实现规格

- `PlannerAgent.plan` 从只读 TopicBrief Port 按 `org_id` 和 ID 获取已锁定或已批准的 brief，校验租户、状态与输入快照哈希格式；给 AgentRunner 的输入仅含 brief ID、哈希、目标、受众、问题和空工具请求。
- Planner AgentDefinition 的工具白名单为空，模型只返回 `planner-output.schema.json` 定义的 Topic Plan 与 Workflow Plan。Workflow 步骤仅能为 evidence review、outline、canonical draft、fact check、human review；输出是建议，不创建或推进 WorkflowRun。
- 拒绝结构不合规、brief ID 不一致、重复步骤、依赖不存在或逆序依赖的模型输出。低置信度或显式 `needs_review` 进入人工复核状态。
- 同租户同幂等键和输入哈希重放首个结果，不再调用模型；不同输入拒绝。AgentRunLedger 只记录哈希、成本和耗时等脱敏元数据，审计记录关联 actor、trace 与 AgentRun。
- 本阶段使用现有内存 AgentRunner、Ledger 与 Fake Model Port；迁移无业务表。生产持久化与真实模型接入由后续任务负责。

补充场景：

- Given 已锁定 TopicBrief 和有效模型输出，When 规划，Then 返回结构化 Topic/Workflow Plan，AgentRun 成功，WorkflowRun 未创建。
- Given 工具请求或模型输出包含发布、授权或外部动作，When 规划，Then 在模型调用前或输出校验时拒绝。
- Given brief 属于其他租户或未锁定，When 规划，Then 拒绝且不泄漏 brief 内容。
- Given 相同幂等键重放，When 输入相同，Then 返回首个结果且不重复模型调用；输入不同则拒绝。
- Given 模型输出的步骤依赖形成逆序或重复，When 规划，Then 拒绝该计划。

## 回滚

- 停止调用 PlannerAgent，保留 AgentRunLedger 与审计证据；不执行 WorkflowRun 或下游副作用。
- 若后续接入生产持久化，追加迁移，不重写本次 no-op 修订。
## 目录边界

拥有目录：

- `modules/agent`

允许目录：

- `modules/agent`
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

- `执行 AGENT-CORE-005A 的公开用例或内部命令`

Then：

- `基于 AgentRunner 实现 Planner Agent；只输出结构化 Topic/Workflow Plan，不调用发布、授权或外部副作用工具。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/agent tests/integration --maxfail=1
```

Gate：`agent_core_005a_acceptance`

## 外部依赖

- 无

## 开工前细化

已按本任务的输入、输出、拒绝路径和回滚行为细化；实现证据见 `AGENT-CORE-005A-EVIDENCE.yaml`。
