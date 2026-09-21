# TOPIC-004 — 建立 `TopicBrief`：目标受众、问题、核心 Claim、证据计划、原创角度、语言/市场和预期渠道。

状态：`done`  
阶段：2（Topic Intelligence（选题智能））  
Owner：`team/topic`  
优先级：`critical` / `P0`

## 目标

建立 `TopicBrief`：目标受众、问题、核心 Claim、证据计划、原创角度、语言/市场和预期渠道。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `FOUND-011`
- `TOPIC-003`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `TOPIC-004.implementation`
- `TOPIC-004.tests`
- `audit_evidence`

## 实现规格

`TopicBrief`：`id`、`org_id`、`opportunity_id`、`version_no`、`status=draft|locked|superseded|cancelled`、`audience{role,experience_level,job_to_be_done}`、`problem_statement`、`core_claims[]`、`evidence_plan[]`、`original_angle`、`locales[]`、`markets[]`、`expected_channels[]`、`owner_id`、`lock_hash`、`created_at`、`locked_at`。`core_claims` 每项需关联 evidence_plan key；`status=locked` 后不可更新，修改必须复制为新 version 并将旧版标记 superseded。

接口：`POST /internal/topic-briefs`、`POST /internal/topic-briefs/{id}:lock`、`POST /internal/topic-briefs/{id}:supersede`。锁定要求 opportunity 为 shortlisted、所有必需 evidence_plan 已填、Policy 通过。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/topic-brief.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_topic_004.py`
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

- `执行 TOPIC-004 的公开用例或内部命令`

Then：

- `建立 `TopicBrief`：目标受众、问题、核心 Claim、证据计划、原创角度、语言/市场和预期渠道。`
- `输出契约、审计事件和指定测试结果可复现`

## 补充场景

- opportunity 非 shortlisted 或已过期时锁定返回 `TOPIC_BRIEF_NOT_ELIGIBLE`。
- lock 请求重复提交相同 payload 返回原 lock_hash；不同 payload 返回 `BRIEF_ALREADY_LOCKED`。
- supersede 必须保留 `supersedes_version_id`，下游 Canonical 只能引用最新 locked 版本。


## 回滚与运行说明

- 暂停 brief 创建、锁定和 supersede 路由即可停止新命令；已提交版本和事件保留供审计。
- `20260918_found_topic_004` 为增量建表；存在正式 brief 时先保留数据库快照，不执行破坏性降级。
- 确定性校验、证据缺失和 Policy 拒绝不重试；相同租户与幂等键可安全重放命令结果。

## 验证

```text
python -m pytest tests/unit/topic tests/integration --maxfail=1
```

Gate：`topic_004_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。

## Implementation Evidence

- `modules/topic/brief.py`：TopicBrief 草稿、证据计划与 claim 关联、shortlisted/Policy 门禁锁定、版本 supersede 和租户隔离。
- `modules/topic/infrastructure/brief_schema.py` 与 `20260918_topic_004.py`：版本唯一约束、幂等命令、Brief 事件追加存储和 SQLite 外键。
- `tests/unit/topic/test_brief.py` 与 `tests/integration/test_topic_brief.py`：证据校验、锁定幂等、Policy、跨租户、版本替换和 API 测试。
- `docs/foundation/TOPIC-004-EVIDENCE.yaml`：专项门禁结果。
