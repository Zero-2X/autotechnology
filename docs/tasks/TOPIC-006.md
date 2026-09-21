# TOPIC-006 — 实现主题状态机和拒绝/延期原因。

状态：`done`  
阶段：2（Topic Intelligence（选题智能））  
Owner：`team/topic`  
优先级：`critical` / `P0`

## 目标

实现主题状态机和拒绝/延期原因。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `FOUND-011`
- `TOPIC-003`
- `TOPIC-004`
- `TOPIC-005`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `TOPIC-006.implementation`
- `TOPIC-006.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/topic-opportunity.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_topic_006.py`
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

- `执行 TOPIC-006 的公开用例或内部命令`

Then：

- `实现主题状态机和拒绝/延期原因。`
- `输出契约、审计事件和指定测试结果可复现`

## 实现规格

- `TopicOpportunityService.transition` 提供 `reject`、`defer`、`expire` 和 `resume` 命令；状态转换使用显式允许表和 `expected_version`，终态不可继续修改。
- `reject` 与 `defer` 必须带非空 reason；`resume` 只允许从 deferred 回到 proposed；跨租户、过期和已有 locked TopicBrief 的机会拒绝转换。
- 每个命令使用租户级 `Idempotency-Key` 与 payload hash；成功转换原子更新机会版本、保存 actor/trace，并写入不可变状态事件。

## 补充场景

- 同一幂等键重放返回原机会与事件；复用键但改变 action、reason 或 expected version 返回 `IDEMPOTENCY_KEY_REUSED`。
- `shortlisted` 可 reject/defer；`rejected` 与 `expired` 是终态；`defer` 后必须先 resume 才能再次 shortlist。
- 状态事件拒绝 UPDATE/DELETE，重启后按 sequence 保持顺序并可按租户读取。

## 回滚与运行说明

- 暂停状态命令路由即可停止新转换；已提交机会事实和状态事件保留。
- `20260918_found_topic_006` 仅新增状态事件表；已有事件时保留快照，不执行破坏性降级。
- 确定性状态冲突和缺少理由不重试；原幂等键可安全重放。

## 验证

```text
python -m pytest tests/unit/topic tests/integration --maxfail=1
```

Gate：`topic_006_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。

## Implementation Evidence

- `modules/topic/opportunity.py`：显式状态转换表、理由校验、locked brief 防护和租户幂等。
- `modules/topic/infrastructure/opportunity_schema.py` 与 `20260918_topic_006.py`：状态事件序列表及追加式数据库约束。
- `tests/unit/topic/test_state_machine.py` 与 `tests/integration/test_topic_state_machine.py`：状态路径、理由、版本、租户、API 和不可变事件验证。
- `docs/foundation/TOPIC-006-EVIDENCE.yaml`：专项门禁结果。
