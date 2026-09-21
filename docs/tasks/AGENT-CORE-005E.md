# AGENT-CORE-005E — 基于 AgentRunner 实现 QA Agent；只生成可解释检查结果和人工任务，不直接批准或发布。

状态：`done`  
阶段：4（Production、Localization、QA、Policy 和 Approval）  
Owner：`team/agent`  
优先级：`high` / `P1`

## 目标

基于 AgentRunner 实现 QA Agent；只生成可解释检查结果和人工任务，不直接批准或发布。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `AGENT-CORE-002`
- `CANON-002`
- `AGENT-CORE-005D`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `AGENT-CORE-005E.implementation`
- `AGENT-CORE-005E.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/agent-run.schema.json`
- `packages/contracts/jsonschema/qa-agent-input.schema.json`
- `packages/contracts/jsonschema/qa-agent-output.schema.json`
- `packages/contracts/jsonschema/qa-report.schema.json`
- `packages/contracts/jsonschema/human-task.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_agent_core_005e.py`

## 实现规格

- `QAAgent.review` 复用 AgentRegistry、AgentRunner、ModelPort 和 AgentRunLedger；注册 `qa-agent-input/v1` 与 `qa-agent-output/v1`，tool allowlist 和 permissions 必须为空。
- `QACheckPort` 只读运行既有 QAService，模型输入只包含同租户 Variant/Canonical 快照哈希和确定性 `qa-report` finding 投影；每个 finding 必须由模型逐项解释，不得改变 code、severity、path、observed 或 expected。
- 输出只能包含解释后的 findings、`qa_review` 人工任务、summary、固定 `needs_review=true`、`decision=review_only`、`approved=false` 和 `published=false`；任务只能引用本次 findings，passed 报告不得创建任务。
- 成功结果写入 AgentRun/ModelCall 哈希账本、`agent_run.completed` EventEnvelope 和包含规则版本、任务数、耗时及成本的审计摘要；不创建 Approval，不改变 Variant/QA 状态，不调用发布接口。
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

- `执行 AGENT-CORE-005E 的公开用例或内部命令`

Then：

- `基于 AgentRunner 实现 QA Agent；只生成可解释检查结果和人工任务，不直接批准或发布。`
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- failed/needs_review QA 报告生成完整、可解释的 finding 摘要和人工复核任务，并固定 review_only。
- passed QA 报告只能返回空人工任务集合；跨租户主体、Variant/Canonical 不匹配、哈希非法和不合法 QA 报告在模型调用前拒绝。
- 伪造 finding、遗漏 finding、改写确定性字段、任务引用未知 finding，以及任何 approve/publish/action 字段均拒绝并记录失败 AgentRun。
- 相同幂等键重放返回首次结果且不重复运行 QA 检查、调用模型或写账本；输入变化返回 `IDEMPOTENCY_KEY_REUSED`。

回滚：

- 停用 qa AgentDefinition，保留 AgentRun、ModelCall、QA 解释、人工任务提案、事件和审计证据；不存在需要撤销的批准或发布事实。
- 本 revision 不创建业务表，回退执行 `python -m alembic downgrade 20260919_found_agent_core_005d`。

## 验证

```text
python -m pytest tests/unit/agent tests/integration --maxfail=1
```

Gate：`agent_core_005e_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
