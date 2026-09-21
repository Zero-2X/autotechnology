# TOPIC-003 — 建立 `TopicOpportunity` 和可解释评分：需求、相关性、证据可得性、差异化、时效，扣除成本和风险。

状态：`done`  
阶段：2（Topic Intelligence（选题智能））  
Owner：`team/topic`  
优先级：`critical` / `P0`

## 目标

建立 `TopicOpportunity` 和可解释评分：需求、相关性、证据可得性、差异化、时效，扣除成本和风险。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `FOUND-011`
- `TOPIC-002`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `TOPIC-003.implementation`
- `TOPIC-003.tests`
- `audit_evidence`

## 实现规格

`TopicOpportunity`：`id`、`org_id`、`signal_ids[]`、`canonical_topic`、`score_total`、`score_breakdown{demand,relevance,evidence_availability,differentiation,timeliness,cost,risk}`、`scoring_version`、`status=proposed|shortlisted|rejected|expired`、`decision_reason`、`expires_at`。评分统一 0–100：`score_total = weighted_positive - weighted_cost - weighted_risk`，权重配置必须随 `scoring_version` 固化并可重算；同一 `org_id+canonical_topic` 在有效期内只保留一个 active opportunity。

接口：`POST /internal/topic-opportunities:score`、`POST /internal/topic-opportunities/{id}:shortlist`。评分结果必须能反向列出每个 signal 和扣分原因，不得由模型直接写入 shortlist 状态。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/topic-opportunity.schema.json`
- `packages/contracts/jsonschema/topic-score-snapshot.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_topic_003.py`
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

- `执行 TOPIC-003 的公开用例或内部命令`

Then：

- `建立 `TopicOpportunity` 和可解释评分：需求、相关性、证据可得性、差异化、时效，扣除成本和风险。`
- `输出契约、审计事件和指定测试结果可复现`

## 补充场景

- 缺少 evidence 或 rights=restricted 的 signal 时，`evidence_availability=0`，总分不得进入 shortlist。
- 使用同一 scoring_version 重算得到相同 score_breakdown 和 content_hash。
- 过期 opportunity 不得创建 TopicBrief，返回 `TOPIC_OPPORTUNITY_EXPIRED`。


## 回滚与运行说明

- 暂停评分与 shortlist 路由即可停止新命令；已提交的评分快照和事件保留供审计。
- `20260918_found_topic_003` 为增量建表；正式记录存在时先留存数据库快照，不执行破坏性降级。
- 确定性校验与授权拒绝不重试；使用原租户和幂等键可重放已提交命令结果。

## 验证

```text
python -m pytest tests/unit/topic tests/integration --maxfail=1
```

Gate：`topic_003_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。

## Implementation Evidence

- `modules/topic/opportunity.py`：逐信号权利核验、七分项定量评分、固定版本权重、快照哈希重算及人工 shortlist 命令。
- `modules/topic/infrastructure/opportunity_schema.py` 与 `20260918_topic_003.py`：不可变权重配置、租户级机会、评分快照、幂等命令和评分事件持久化。
- `tests/unit/topic/test_opportunity.py` 与 `tests/integration/test_topic_opportunity.py`：评分解释、拒绝、过期、重启与 API 验证。
- `docs/foundation/TOPIC-003-EVIDENCE.yaml`：专项门禁结果。
