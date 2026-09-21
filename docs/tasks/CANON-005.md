# CANON-005 — 实现内容新鲜度、版本过期、事实冲突和刷新队列。

状态：`done`  
阶段：3（Provenance、Rights、KnowledgeCore 和 Canonical Content）  
Owner：`team/canonical_content`  
优先级：`critical` / `P0`

## 目标

实现内容新鲜度、版本过期、事实冲突和刷新队列。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `WORKFLOW-CORE-002`
- `TOPIC-004`
- `CANON-004`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `CANON-005.implementation`
- `CANON-005.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/canonical-content-version.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_canon_005.py`
## 目录边界

拥有目录：

- `modules/canonical_content`

允许目录：

- `modules/canonical_content`
- `docs/foundation`
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

## 实现规格

- 在 `canonical_freshness_checks` 中追加保存每次检查；检查状态为 `fresh`、`review_due`、`stale`、`expired`、`conflict` 或 `withdrawn`，不得更新历史 Canonical 版本。
- 版本创建时保存 `freshness_checked_at`、`freshness_expires_at`、`freshness_status`、`conflict_set_ids` 和 `refresh_required` 快照；知识版本带冲突集时默认进入 `conflict`。
- 过期、临近过期、显式 stale 和事实冲突自动生成租户范围的 `canonical_refresh_queue` 项；同一版本和原因只有一个未完成队列项。
- 刷新队列支持人工/Worker 领取租约和完成，租约过期后可被再次领取；跨租户、非当前领取人、已过期租约和已完成队列均拒绝。
- 所有检查、入队、领取和完成命令使用幂等键；检查、队列命令和事件使用同一 SQLite 事务。

补充场景：

- Given 版本的 `freshness_expires_at` 已过去，When 执行检查，Then 追加 `expired` 检查并生成一个 `expired` 队列项。
- Given 临近过期但未过期，When 执行检查，Then 状态为 `review_due`，不得误报为 `expired`。
- Given 传入冲突集或关联 KnowledgeCore 版本含冲突集，When 执行检查，Then 状态为 `conflict`、优先级高于普通刷新并保留冲突 ID。
- Given 同一租户重复提交相同幂等键，When payload 相同，Then 返回第一次结果；payload 不同返回 `IDEMPOTENCY_KEY_REUSED`。
- Given 队列已被其他 Worker 持有有效租约，When 再次领取，Then 返回 `REFRESH_QUEUE_NOT_CLAIMABLE`；租约过期后允许接管。
- Given 历史版本已经产生 freshness check，When 读取版本，Then 返回最新 freshness 投影，数据库中原检查和原版本均不可更新/删除。

## 回滚

- 停止产生新的 freshness check 和 refresh queue 命令，保留已有检查、队列事实和不可变版本。
- 不重写或删除已接受的 `20260918_found_canon_005` 迁移；若需修正，追加兼容迁移并保持历史事实可查询。

## Given–When–Then

Given：

- `所有前置任务已完成`
- `TenantContext、trace_id 和 Idempotency-Key 可用`

When：

- `执行 CANON-005 的公开用例或内部命令`

Then：

- `实现内容新鲜度、版本过期、事实冲突和刷新队列。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/canonical_content tests/integration --maxfail=1
```

Gate：`canon_005_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。

## Implementation Evidence

- `modules/canonical_content/service.py` 追加 freshness check，计算 fresh/review_due/stale/expired/conflict 状态，并从 KnowledgeCore 冲突集推导阻断原因。
- `canonical_refresh_queue` 提供幂等入队、租约领取、过期接管和完成命令；队列事实按租户隔离，历史 Canonical 版本保持不可变。
- `modules/canonical_content/infrastructure/canonical_schema.py` 建立 freshness check 与 refresh queue 本地存储；`packages/db/migrations/versions/20260918_canon_005.py` 提供可回滚 Alembic 迁移。
- `apps/api/main.py` 提供 freshness 检查、刷新入队、队列查询、领取和完成的内部命令路由。
- `tests/unit/canonical_content/test_service.py` 覆盖过期判定、队列租约和完成；专项门禁结果记录于 `docs/foundation/CANON-005-EVIDENCE.yaml`。
