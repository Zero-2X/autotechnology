# TOPIC-005 — 建立编辑日历、负责人、优先级、截止时间和人工覆盖理由。

状态：`done`  
阶段：2（Topic Intelligence（选题智能））  
Owner：`team/topic`  
优先级：`critical` / `P0`

## 目标

建立编辑日历、负责人、优先级、截止时间和人工覆盖理由。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `FOUND-011`
- `TOPIC-004`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `TOPIC-005.implementation`
- `TOPIC-005.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/topic-opportunity.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_topic_005.py`
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

- `执行 TOPIC-005 的公开用例或内部命令`

Then：

- `建立编辑日历、负责人、优先级、截止时间和人工覆盖理由。`
- `输出契约、审计事件和指定测试结果可复现`

## 实现规格

- `EditorialCalendarService` 为一个 TopicOpportunity 建立版本化编辑计划，保存 `owner_id`、`priority`、UTC `due_at`、创建人、版本和状态；首次排期只能有一个 active 版本。
- `POST /internal/topic-opportunities/{id}:schedule` 使用 `expected_version` 和 `Idempotency-Key` 原子更新机会的 `owner_actor_id`、`priority`、`due_at`、`editorial_plan_id`；过期机会、跨租户机会和截止时间超出机会有效期均拒绝。
- `POST /internal/topic-opportunities/{id}:override` 必须提供非空 `manual_override_reason`；覆盖会把旧计划标为 superseded、生成新版本并保留追加式审计记录。
- 计划命令保存 actor、trace、输入/输出版本和 payload hash；相同幂等键重放原结果，复用键但 payload 改变返回 `IDEMPOTENCY_KEY_REUSED`。

## 补充场景

- 未提供负责人时使用当前 TenantContext actor；priority 只允许 low/normal/high/urgent。
- 非 UTC 截止时间、过去的截止时间或无理由人工覆盖只拒绝当前命令，不改变机会或已有计划。
- 重启后可读取 active 计划和 superseded 历史；审计表拒绝 UPDATE/DELETE。

## 回滚与运行说明

- 暂停排期和覆盖路由即可停止新命令；已提交计划与审计记录保留。
- `20260918_found_topic_005` 为增量建表；已有记录时保留数据库快照后再评估降级，不做破坏性回滚。
- 确定性校验和租户拒绝不重试；原幂等键可安全重放成功命令。

## 验证

```text
python -m pytest tests/unit/topic tests/integration --maxfail=1
```

Gate：`topic_005_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。

## Implementation Evidence

- `modules/topic/calendar.py`：编辑计划创建、人工覆盖、版本控制、UTC 截止时间与租户隔离。
- `modules/topic/infrastructure/calendar_schema.py` 与 `20260918_topic_005.py`：计划、命令和追加式审计持久化。
- `tests/unit/topic/test_calendar.py` 与 `tests/integration/test_topic_calendar.py`：幂等、版本覆盖、校验、API、重启和审计不可变验证。
- `docs/foundation/TOPIC-005-EVIDENCE.yaml`：专项门禁结果。
