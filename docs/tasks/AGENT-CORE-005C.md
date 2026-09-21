# AGENT-CORE-005C — 基于 AgentRunner 实现 Rights/Provenance Agent；只抽取许可证线索、范围和缺口，最终权利判断必须由规则或人工完成。

状态：`done`  
阶段：4（Production、Localization、QA、Policy 和 Approval）  
Owner：`team/agent`  
优先级：`high` / `P1`

## 目标

基于 AgentRunner 实现 Rights/Provenance Agent；只抽取许可证线索、范围和缺口，最终权利判断必须由规则或人工完成。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `AGENT-CORE-002`
- `PROV-002`
- `CANON-002`
- `AGENT-CORE-005B`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `AGENT-CORE-005C.implementation`
- `AGENT-CORE-005C.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/agent-run.schema.json`
- `packages/contracts/jsonschema/rights-provenance-input.schema.json`
- `packages/contracts/jsonschema/rights-provenance-output.schema.json`
- `packages/contracts/jsonschema/rights-record-version.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_agent_core_005c.py`

## 实现规格

- `RightsProvenanceAgent.analyze` 复用 AgentRegistry、AgentRunner、ModelPort 和 AgentRunLedger；注册 `rights-provenance-input/v1` 与 `rights-provenance-output/v1`，tool allowlist 和 permissions 必须为空。
- `RightsProvenancePort` 只读装载指定租户的不可变 RightsRecordVersion；模型输入固定为版本身份、snapshot hash、既有范围、policy rule version，以及引用该版本 source/license/contract/evidence ref 的受控摘录。
- 输出只允许 permission clues、scope candidates、gaps、confidence、固定 `needs_review=true` 和 `final_rights_decision=deferred`；每条许可线索的 evidence_ref/locator/quote 必须逐项精确匹配输入摘录。
- clue/scope/gap key 必须唯一，候选范围和缺口只能引用本次许可线索；rights status、verification、authorization decision、写命令或其他额外字段由闭合 Schema 拒绝。
- 成功结果写入 AgentRun/ModelCall 哈希账本、`agent_run.completed` EventEnvelope 和包含 Policy 快照、耗时及成本的审计摘要；幂等重放不再次调用模型，并始终声明 RightsRecord、状态与授权决定零写入。
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

- `执行 AGENT-CORE-005C 的公开用例或内部命令`

Then：

- `基于 AgentRunner 实现 Rights/Provenance Agent；只抽取许可证线索、范围和缺口，最终权利判断必须由规则或人工完成。`
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- 同租户 RightsRecordVersion 与受控许可摘录可生成可追溯线索、候选范围和证据缺口；输出必须进入 needs_review，最终权利结论固定 deferred。
- 外租户、版本身份不匹配、非法版本契约、未知 evidence ref 和重复输入摘录必须在模型调用前拒绝。
- 伪造 quote/locator/evidence ref、重复 clue/scope/gap key、引用未知 clue，以及任何 verified/authorized/write 字段均拒绝并记录失败 AgentRun。
- 相同幂等键重放返回首次提取结果且不重复读取版本、调用模型或写账本；输入变化返回 `IDEMPOTENCY_KEY_REUSED`。

回滚：

- 停用 rights-provenance AgentDefinition，保留 AgentRun、ModelCall、提取输出、事件和审计证据；不存在需要撤销的 RightsRecordVersion 或 authorization decision 写入。
- 本 revision 不创建业务表，回退执行 `python -m alembic downgrade 20260919_found_agent_core_005b`。

## 验证

```text
python -m pytest tests/unit/agent tests/integration --maxfail=1
```

Gate：`agent_core_005c_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
