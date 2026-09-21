# AGENT-CORE-005B — 基于 AgentRunner 实现 Research Agent；只输出带来源引用的候选事实和待核查项，不把模型判断直接写入 KnowledgeCore。

状态：`done`  
阶段：4（Production、Localization、QA、Policy 和 Approval）  
Owner：`team/agent`  
优先级：`high` / `P1`

## 目标

基于 AgentRunner 实现 Research Agent；只输出带来源引用的候选事实和待核查项，不把模型判断直接写入 KnowledgeCore。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `AGENT-CORE-002`
- `PROV-001`
- `KNOW-001`
- `CANON-002`
- `AGENT-CORE-005A`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `AGENT-CORE-005B.implementation`
- `AGENT-CORE-005B.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/agent-run.schema.json`
- `packages/contracts/jsonschema/research-input.schema.json`
- `packages/contracts/jsonschema/research-output.schema.json`
- `packages/contracts/jsonschema/source-snapshot.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_agent_core_005b.py`

## 实现规格

- `ResearchAgent.research` 基于既有 AgentRegistry、AgentRunner、ModelPort 和 AgentRunLedger；注册 `research-input/v1` 与 `research-output/v1`，AgentDefinition 的 tool allowlist 和 permissions 必须为空。
- ResearchSourcePort 只读装载同租户、状态为 usable 的不可变 SourceSnapshot 及其受控摘录；模型输入仅包含 snapshot id、content hash、locator 和 quote，不读取私有对象或调用网络。
- 输出只允许 `candidate_facts`、`verification_items`、confidence 和固定 `needs_review=true`；候选引用的 source_snapshot_id/locator/quote 必须逐项精确匹配输入摘录。
- candidate/item key 必须唯一，核查项只能引用本次候选；Claim/KnowledgeCore id、verified 状态、写命令或其他额外字段由闭合 Schema 拒绝。
- 成功结果写入 AgentRun/ModelCall 哈希账本、`agent_run.completed` EventEnvelope 和审计摘要；幂等重放不再次调用模型，并始终声明 `claims_created=false`、`knowledge_core_mutated=false`。
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

- `执行 AGENT-CORE-005B 的公开用例或内部命令`

Then：

- `基于 AgentRunner 实现 Research Agent；只输出带来源引用的候选事实和待核查项，不把模型判断直接写入 KnowledgeCore。`
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- usable SourceSnapshot 的受控摘录可生成带精确引用的候选事实和待核查项，结果必须进入 needs_review，不得成为 verified Claim。
- 外租户、captured/quarantined/expired/revoked/blocked 快照、缺少摘录或非法 content hash 在模型调用前拒绝。
- 伪造 quote/locator/snapshot 引用、重复 candidate/item key、核查项引用未知候选和任何 KnowledgeCore 写字段均拒绝并记录失败 AgentRun。
- 相同幂等键重放返回首次候选且不重复模型调用或账本写入；输入变化返回 `IDEMPOTENCY_KEY_REUSED`。

回滚：

- 停用 research AgentDefinition，保留 AgentRun、ModelCall、候选输出、事件和审计证据；不存在需要撤销的 Claim 或 KnowledgeCore 写入。
- 本 revision 不创建业务表，回退执行 `python -m alembic downgrade 20260919_found_feedback_core_002`。

## 验证

```text
python -m pytest tests/unit/agent tests/integration --maxfail=1
```

Gate：`agent_core_005b_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
