# TOPIC-007 — 实现机会评分的输入快照，保证分数可以复算。

状态：`done`  
阶段：2（Topic Intelligence（选题智能））  
Owner：`team/topic`  
优先级：`critical` / `P0`

## 目标

实现机会评分的输入快照，保证分数可以复算。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `FOUND-011`
- `TOPIC-003`
- `TOPIC-006`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `TOPIC-007.implementation`
- `TOPIC-007.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/topic-score-snapshot.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_topic_007.py`
## 目录边界

拥有目录：

- `modules/topic`

允许目录：

- `modules/topic`
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

- `执行 TOPIC-007 的公开用例或内部命令`

Then：

- `实现机会评分的输入快照，保证分数可以复算。`
- `输出契约、审计事件和指定测试结果可复现`

## 实现规格

- `TopicOpportunityService.score` 将每个参与评分的 `TopicSignal` 固化为输入摘要，保存逐信号 `input_hash`、聚合 `input_snapshot_hash`、评分公式、权重、分项、扣分和 `content_hash`；写入契约前完成闭合 Schema 校验。
- `recompute_snapshot` 只读取不可变快照，校验内容摘要、输入聚合摘要和加权总分；任一字段被篡改时返回 `SCORING_SNAPSHOT_MISMATCH`，不把当前可变信号覆盖历史事实。
- `verify_snapshot` 在租户上下文中重新读取当前信号并生成 drift 报告；结果按 `(org_id, snapshot_id, idempotency_key)` 持久化，重复请求返回首次结果，核验结果表和评分事实均禁止 UPDATE/DELETE。
- API 内部命令 `/internal/topic-score-snapshots/{snapshot_id}:verify` 强制要求租户、actor、trace 和 `Idempotency-Key`，跨租户快照访问统一拒绝。

## 补充场景

- 首次核验返回 `verified=true` 和空 drift；上游信号改变后使用新幂等键核验会返回 `verified=false`，并指出 `<signal_id>:changed` 或 `<signal_id>:missing`。
- 同一租户、快照和幂等键重放返回原始 actor/trace 及结果，不重新写入事实；另一租户即使知道快照 ID 也只能收到 `TENANT_SCOPE_VIOLATION`。
- 直接篡改快照 payload、输入哈希或总分会在核验前被内容/算术校验拦截；核验记录不能被更新或删除。

## 验证

```text
python -m pytest tests/unit/topic/test_opportunity.py tests/integration/test_topic_opportunity.py --maxfail=1
```

Gate：`topic_007_acceptance`

## 外部依赖

- 无

## 回滚与运行说明

- 暂停核验路由即可停止新的验证命令；已保存的评分快照、输入哈希和核验结果继续作为审计事实保留。
- `20260918_found_topic_007` 只新增核验结果表和追加式约束；降级前先导出核验结果，生产环境不对已有评分事实做破坏性回写。
- 内容摘要、输入摘要、信号漂移和租户边界属于确定性结果，不重试；原幂等键可安全重放首次核验结果。

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。

## Implementation Evidence

- `modules/topic/opportunity.py`：逐信号输入哈希、聚合输入快照哈希、内容/算术复算和租户级核验报告。
- `modules/topic/infrastructure/opportunity_schema.py` 与 `20260918_topic_007.py`：核验结果持久化、哈希检查、外键和追加式数据库触发器。
- `apps/api/main.py`：内部快照核验路由及统一租户/错误映射。
- `tests/unit/topic/test_opportunity.py` 与 `tests/integration/test_topic_opportunity.py`：幂等、漂移、篡改、跨租户、API 和不可变记录验证。
- `docs/foundation/TOPIC-007-EVIDENCE.yaml`：专项门禁结果。
