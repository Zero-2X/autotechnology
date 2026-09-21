# TOPIC-001 — 建立主题分类、标签、技术版本和受众模型。

状态：`done`
阶段：2（Topic Intelligence（选题智能））  
Owner：`team/topic`  
优先级：`critical` / `P0`

## 目标

建立主题分类、标签、技术版本和受众模型。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `FOUND-007A`
- `FOUND-011`
- `IAM-CORE-001`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `TOPIC-001.implementation`
- `TOPIC-001.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/topic-taxonomy.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_topic_001.py`
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

- `执行 TOPIC-001 的公开用例或内部命令`

Then：

- `建立主题分类、标签、技术版本和受众模型。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/topic tests/integration --maxfail=1
```

Gate：`topic_001_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。

## 实现规格

- `TopicTaxonomyService` 生成符合 `topic-taxonomy.schema.json` 的租户级分类记录，保存唯一 key、标签、技术版本和受众集合。
- 创建、资料调整和状态转换使用租户内幂等键；状态只允许 draft→active/retired、active→retired。
- 所有读取和状态命令校验 `org_id` 与 expected version，契约输出不包含未登记字段。

## 补充场景

- 空 key、空标签、空技术版本或空受众会被确定性拒绝；集合值去重并保持输入顺序。
- 跨租户读取和版本冲突返回稳定错误码；同一幂等键输入变化必须拒绝。
- 记录与幂等结果可在本地 SQLite 中持久化，不调用外部平台或读取凭证。

## 回滚

撤销 `20260918_found_topic_001` 迁移即可回到 `20260918_found_obs_core_003`；服务状态可丢弃并通过契约重新构建。

## Implementation Evidence

- `modules/topic/service.py`：持久化分类、标签、技术版本、受众和生命周期状态机。
- `tests/integration/test_topic_taxonomy_persistence.py`：重启后的分类、版本与幂等命令返回。
- `tests/unit/topic/test_service.py`：契约、幂等、版本冲突和租户隔离验证。
- `docs/foundation/TOPIC-001-EVIDENCE.yaml`：测试、迁移和契约验证结果。
