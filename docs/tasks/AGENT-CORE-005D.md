# AGENT-CORE-005D — 基于 AgentRunner 实现 Transform Agent；只生成 Variant 草稿，保留 Claim、术语、数字、代码和链接映射。

状态：`done`  
阶段：4（Production、Localization、QA、Policy 和 Approval）  
Owner：`team/agent`  
优先级：`high` / `P1`

## 目标

基于 AgentRunner 实现 Transform Agent；只生成 Variant 草稿，保留 Claim、术语、数字、代码和链接映射。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `AGENT-CORE-002`
- `KNOW-001`
- `CANON-002`
- `AGENT-CORE-005C`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `AGENT-CORE-005D.implementation`
- `AGENT-CORE-005D.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/agent-run.schema.json`
- `packages/contracts/jsonschema/transform-input.schema.json`
- `packages/contracts/jsonschema/transform-output.schema.json`
- `packages/contracts/jsonschema/variant-draft.schema.json`
- `packages/contracts/jsonschema/canonical-content-version.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_agent_core_005d.py`

## 实现规格

- `TransformAgent.generate` 复用 AgentRegistry、AgentRunner、ModelPort 和 AgentRunLedger；注册 `transform-input/v1` 与 `transform-output/v1`，tool allowlist 和 permissions 必须为空。
- `CanonicalVersionPort` 只读装载同租户、未撤回的 CanonicalContentVersion；模型输入固定为源版本、section 顺序、Claim ID、目标 locale/market/audience/tone 和受保护映射。
- 保护映射由代码从源文本确定性提取：术语使用给定目标译法，数字、代码片段和链接要求原值及出现次数；模型输出的 block/source/Claim 映射、preservation_map 和 `needs_review=true` 必须闭合匹配。
- 成功结果组装符合 `variant-draft.schema.json` 的瞬态草稿，固定 `transform_mode=agent_candidate`；不创建 ContentVariant/VariantVersion，不调用发布接口。
- 成功结果写入 AgentRun/ModelCall 哈希账本、`agent_run.completed` EventEnvelope 和包含映射数量、耗时及成本的审计摘要；幂等重放不再次调用模型。
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

- `执行 AGENT-CORE-005D 的公开用例或内部命令`

Then：

- `基于 AgentRunner 实现 Transform Agent；只生成 Variant 草稿，保留 Claim、术语、数字、代码和链接映射。`
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- 同租户 Canonical 版本含 Claim、术语、数字、代码和链接时，输出草稿保持 section 顺序、Claim ID 和全部受保护映射，并进入 needs_review。
- 外租户、withdrawn/freshness withdrawn 源、无效 content hash、空 section 或术语不在源文本中时，在模型调用前拒绝。
- 伪造 Claim、删改数字/代码/链接/术语映射、重复或新增保护映射，以及任何 ContentVariant/VariantVersion/发布字段均拒绝并记录失败 AgentRun。
- 相同幂等键重放返回首次草稿且不重复读取、调用模型或写账本；输入变化返回 `IDEMPOTENCY_KEY_REUSED`。

回滚：

- 停用 transform AgentDefinition，保留 AgentRun、ModelCall、瞬态草稿、事件和审计证据；不存在需要撤销的生产事实或发布副作用。
- 本 revision 不创建业务表，回退执行 `python -m alembic downgrade 20260919_found_agent_core_005c`。

## 验证

```text
python -m pytest tests/unit/agent tests/integration --maxfail=1
```

Gate：`agent_core_005d_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
