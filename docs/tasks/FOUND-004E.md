# FOUND-004E — 实现单任务重放命令；重放必须复用原输入版本并生成新执行记录。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/foundation`  
优先级：`critical` / `P0`

## 目标

实现单任务重放命令；重放必须复用原输入版本并生成新执行记录。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-004D`

## 输入

- `packages/contracts/jsonschema/task-job.schema.json`：TaskJob 输入版本、状态和 replay 字段契约。
- `packages/db/migrations/versions/20260916_found_004d_failure_retry.py`：失败与未知结果事实，用于来源资格检查。
- `TenantContext` 等价输入：`org_id`、`worker_id`、`trace_id` 和幂等上下文；所有读取和写入按 `org_id` 限定。

## 输出

- `infra/foundation/task_replay.py`：来源校验、secret 阻断、policy hook 和新 TaskJob 创建。
- `apps/api/main.py`：worker-only `replay` 内部命令。
- `packages/db/migrations/versions/20260916_found_004e_replay.py`：无新增表的可逆迁移检查点。
- `tests/contract/test_found_004e_replay.py`、`tests/integration/test_found_004e_replay_integration.py`。
- `docs/foundation/FOUND-004E-EVIDENCE.yaml`：验证与副作用证据。

## 实现规格

命令 `POST /internal/task-jobs/{job_id}:replay` 请求 `{source_job_id, source_attempt_count, reason, idempotency_key}`，复制原 `payload_ref`、`payload_hash` 和输入/aggregate 版本，生成新 `TaskJob`，字段 `replayed_from_job_id`、`replayed_from_attempt_count`、`replay_reason`。禁止复制 secret、token、credential、password、OAuth 或平台外部引用；replay 只能指向 `failed|dead_letter` 任务，`unknown` 结果还必须存在状态为 `submitted|completed` 的人工复核任务，并重新执行注入的 policy/kill-switch 检查。

错误码：`REPLAY_SOURCE_NOT_FOUND`、`REPLAY_NOT_ALLOWED`、`REPLAY_SECRET_INPUT`、`REPLAY_VERSION_CONFLICT`、`TENANT_SCOPE_VIOLATION`。同一租户、job type 和幂等键返回原新 job_id；幂等键指向不同来源时拒绝。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/task-job.schema.json`

迁移 revision：

- `packages/db/migrations/versions/20260916_found_004e_replay.py`
## 目录边界

拥有目录：

- `infra/foundation`

允许目录：

- `infra/foundation`
- `apps`
- `packages`
- `infra`
- `deploy/environments/dev`
- `deploy/environments/staging`
- `scripts`
- `docs`
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

- `执行 FOUND-004E 的公开用例或内部命令`

Then：

- `实现单任务重放命令；重放必须复用原输入版本并生成新执行记录。`
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- replay 使用原输入 hash 但创建不同 job_id，审计含 source_job_id。
- source 正在 running 或 succeeded 时返回 `REPLAY_NOT_ALLOWED`。
- 检测到 secret 引用时拒绝复制并记录脱敏审计。
- `source_attempt_count 与当前 source job attempt_count 不一致时返回 REPLAY_VERSION_CONFLICT，原 job 不变。`
- `同一幂等键重复调用返回同一新 job；跨租户调用返回 TENANT_SCOPE_VIOLATION。`

回滚：取消新 replay job 即可；原 job、attempt、失败事实和输入版本不修改；no-op revision 可回退到 `20260916_found_004d`。

六类 GWT 必须覆盖：成功重放、重复幂等键、非法来源、权限/跨租户、依赖缺失、secret 阻断与未知结果。

## 验证

```text
python -m pytest tests/contract tests/integration --maxfail=1
```

Gate：`found_004e_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡已完成：来源状态/attempt/version 校验、secret 与平台引用阻断、unknown 人工确认门槛、租户隔离、幂等新 job 创建和 worker-only replay 命令均已通过 synthetic SQLite 测试；原 task job 与失败事实保持不可变。
