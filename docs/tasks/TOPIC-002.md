# TOPIC-002 — 建立 `TopicSignal`，支持人工 CSV/JSON 导入；字段必须包含 `source_type`、`source_ref`、`captured_at`、`locale`、`region`、`usage_rights_status`、`terms_snapshot_ref`、`license_ref`、`permitted_use` 和 `confidence`。

状态：`done`  
阶段：2（Topic Intelligence（选题智能））  
Owner：`team/topic`  
优先级：`critical` / `P0`

## 目标

建立 `TopicSignal`，支持人工 CSV/JSON 导入；字段必须包含 `source_type`、`source_ref`、`captured_at`、`locale`、`region`、`usage_rights_status`、`terms_snapshot_ref`、`license_ref`、`permitted_use` 和 `confidence`。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `FOUND-011`
- `TOPIC-001`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `TOPIC-002.implementation`
- `TOPIC-002.tests`
- `audit_evidence`

## 实现规格

`TopicSignal` 字段：`id`、`org_id`、`source_type`（manual|rss|api|import）、`source_ref`、`captured_at`（UTC）、`locale`、`region`、`title`、`summary`、`usage_rights_status`（unknown|verified|restricted|rejected）、`terms_snapshot_ref`、`license_ref`、`permitted_use`（research|editorial|commercial|none）、`confidence`（0..1）、`dedupe_key`、`created_by`、`created_at`。

导入接口：`POST /internal/topic-signals:import`，接受 CSV 或 JSON 数组，单批最多 1,000 条；逐行返回 `accepted|rejected`、错误码和行号。`dedupe_key=sha256(org_id|source_type|source_ref|captured_at)` 唯一；rights 为 `unknown/restricted/rejected` 的信号不得自动进入可发布流程。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/topic-signal.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_topic_002.py`
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

- `执行 TOPIC-002 的公开用例或内部命令`

Then：

- `建立 `TopicSignal`，支持人工 CSV/JSON 导入；字段必须包含 `source_type`、`source_ref`、`captured_at`、`locale`、`region`、`usage_rights_status`、`terms_snapshot_ref`、`license_ref`、`permitted_use` 和 `confidence`。`
- `输出契约、审计事件和指定测试结果可复现`

## 补充场景

- 缺少任一必填字段时仅拒绝该行，不回滚同批合法行，并发出 `topic_signal.rejected`。
- 重复 `dedupe_key` 返回既有 signal_id，结果为 `duplicate`，不得创建第二条记录。
- `captured_at` 非 UTC 或 confidence 超出 0..1 时返回确定性校验错误且不重试。


## 回滚与运行说明

- 暂停导入路由即可停止新命令；已提交的 TopicSignal 与拒绝事件保留供审计。
- `20260918_found_topic_002` 是增量建表迁移。仅在尚无正式记录时执行降级；已有记录时先保留数据库快照并停止后续迁移。
- 逐行确定性拒绝不重试；批次结果可用相同租户和幂等键安全重放。

## 验证

```text
python -m pytest tests/unit/topic tests/integration --maxfail=1
```

Gate：`topic_002_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。

## Implementation Evidence

- `modules/topic/signal.py`：CSV/JSON 批次导入、逐行校验、UTC 规范化、租户去重、授权证据与可发布查询限制。
- `modules/topic/infrastructure/signal_schema.py` 与 `20260918_topic_002.py`：租户级信号、幂等结果和追加式拒绝事件持久化。
- `tests/unit/topic/test_signal_import.py` 与 `tests/integration/test_topic_signal_import.py`：行级拒绝、重复、重启幂等、API、事件契约和租户隔离。
- `docs/foundation/TOPIC-002-EVIDENCE.yaml`：专项门禁结果。
