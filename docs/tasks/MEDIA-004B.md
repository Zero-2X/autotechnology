# MEDIA-004B — 实现渲染失败重试、单镜头重渲染和死信；不得重复生成已确认的外部副作用。

状态：`done`  
阶段：6（Media 和 Asset）  
Owner：`team/media`  
优先级：`high` / `P1`

## 目标

实现渲染失败重试、单镜头重渲染和死信；不得重复生成已确认的外部副作用。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `FOUND-004D`
- `PROD-002`
- `MEDIA-004A`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `MEDIA-004B.implementation`
- `MEDIA-004B.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/render-job.schema.json`
- `packages/contracts/jsonschema/task-failure.schema.json`
- `packages/contracts/jsonschema/render-retry.schema.json`

迁移 revision：

- `packages/db/migrations/versions/20260920_media_004b.py`
## 目录边界

拥有目录：

- `modules/media`

允许目录：

- `modules/media`
- `apps/worker`
- `adapters/fake`
- `tests/accessibility`
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

- `记录 Renderer/Storage 的 deterministic、transient 或 unknown 失败`
- `执行已到期的 retry schedule`
- `按 stage、shot_sequence 和锁定 profile 请求单镜头重渲染`
- `执行达到上限的死信命令`

Then：

- `deterministic 失败进入 failed 且返回 RETRY_NOT_ALLOWED；transient 在 max_attempts 内按有上限的指数退避进入 retry_scheduled，达到上限进入 dead_letter；unknown 进入 unknown 并只创建一个人工核查任务。`
- `相同 (render_job_id, attempt_count, error_code) 失败事实幂等；相同命令幂等键和 payload hash 重放返回原决定，换 payload 返回 IDEMPOTENCY_KEY_REUSED。`
- `retry schedule 只有 available_at 到期且仍为 scheduled 时才能被一个 Worker 原子领取；过期、已领取或已完成的 schedule 不得再次触发 Renderer。`
- `单镜头自然键为 (org_id, render_job_id, stage, shot_sequence, output_profile_key)；已确认产物同哈希重放，异哈希拒绝，绝不覆盖 private object。`
- `004A 已写入但尚未确认的稳定 object key 必须先执行 head/get 哈希核验；核验成功登记原对象，核验失败才允许按失败分类继续处理。`
- `所有状态变化记录 tenant、actor、trace_id、expected version、输入哈希、拒绝原因和成本字段；失败、重试、死信和单镜头确认写入 Outbox。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/media tests/integration --maxfail=1
```

Gate：`media_004b_acceptance`

## 外部依赖

- 无

## 实现规格

`MediaRenderRetryService` 使用 MEDIA-004A 的 `MediaRenderService`、`RendererPort` 和 `StoragePort`，不直接依赖 `infra`。失败事实使用 `task-failure.schema.json` 的三类错误；错误消息只保留脱敏文本。`RenderRetryPolicy(backoff_base_ms, backoff_cap_ms, max_attempts, jitter)` 计算 `base * 2^(attempt-1)` 并封顶，默认无抖动以便 fixture 可重放。

每个 render job 保存 `max_attempts`、`failure_count`、`last_failure_id`、`next_retry_at` 和死信原因。失败事实、retry command、retry schedule 和 shot target 分别投影到 MEDIA-004B 的追加式表。schedule 的身份字段不可变，只允许 `scheduled → claimed → completed` 或 `scheduled → cancelled` 的状态推进；失败事实与命令不得更新或删除。

`retry_due` 在同租户、同 job 的 schedule 上执行原子领取，先检查 expected version 和到期时间，再调用已有执行入口。成功、已确认的 pending object 恢复和重复消费都复用 004A 的稳定对象键与自然键。Renderer 或 Storage 的结果未知时不自动再次产生外部副作用，而是保留 `unknown` 和唯一 `unknown_result` 人工任务。

`rerender_shot` 只接收合法 stage、正整数 shot_sequence 和已锁定 output profile；请求会把 scope 注入 Renderer，使用 `render/{job}/{profile}/{stage}/{shot}.bin` 作为稳定对象键。已确认的同键产物直接返回，不再调用 Renderer；不同输入哈希或不同 payload 产生确定性冲突。

## 补充场景

1. deterministic 失败不创建 schedule；重复上报只返回同一 failure id，任务保持不可自动 retry。
2. transient 失败按 1000/2000/4000… 毫秒退避，超过 cap 后保持 cap；达到 max_attempts 后创建 dead-letter 人工任务。
3. unknown 失败只创建一个人工任务，`retry_due`、直接 execute 和 shot rerender 都不能绕过人工核查触发自动重试。
4. 两个 Worker 同时领取同一 schedule 只有一个获得 `claimed`，另一个返回稳定冲突；已确认 artifact 的再次执行不会增加 Renderer 调用次数。
5. shot 同键同输入哈希重放返回原 object ref 和 artifact；同键异输入哈希、跨租户 job 或不匹配 profile 均拒绝且不写入新事实。
6. 命令 payload hash、expected version、tenant context、trace_id、actor 和 audit/outbox 在重放时保持一致；冲突请求不产生部分写入。
7. 迁移升级创建失败、schedule、command 和 shot target 四类表，SQLite/PostgreSQL 都检查租户复合引用、哈希、自然键、追加式保护并可降级回 004A。

## 回滚

先关闭 retry 分派并保留 failure、schedule、shot target、audit 和 private object 事实；已确认对象不删除。停止 retry Worker 后执行 `alembic downgrade 20260920_media_004a`，只移除 MEDIA-004B 的四张表，保留 004A 的 render job、输入和产物记录。

## 开工前细化

本卡已从 bootstrap 任务卡细化为可执行行为；实现阶段只允许修改 `modules/media`、契约、MEDIA-004B 迁移、Worker/fake seam、测试和 foundation 证据。未知外部结果必须停在人工核查边界，不能由 retry schedule 自动放大副作用。

## 当前实现

- `modules/media/render_retry_service.py`：失败分类、`RenderRetryPolicy`、幂等失败事实、到期 schedule 领取、Worker handler、未知结果人工解析、死信和 `rerender_shot`；`MediaRenderService` 提供兼容委托入口。
- `modules/media/render_service.py`：retry_scheduled 执行边界、完整事件信封和已写入 pending private object 的 head/get 恢复；普通 Worker 不能绕过到期 schedule 直接重试。
- `packages/contracts/jsonschema/render-retry.schema.json` 与 `render-job.schema.json`：失败、schedule、shot target、retry 状态和恢复字段的关闭式契约。
- `packages/db/migrations/versions/20260920_media_004b.py`：render job 重试字段、失败事实、retry schedule、命令和 shot target；SQLite/PostgreSQL 的租户、哈希、自然键、追加式及状态推进保护。

## 验证记录

- MEDIA-004B 专项单元、Worker、SQLite 迁移、契约和 PostgreSQL 离线 SQL 测试通过。
- 全量回归除预期的 FOUND-000 清单指纹过期外，其余 **979 项通过**；文档与生成物收口后刷新 inventory 并单独复验。
- Schema、架构、迁移图、事件兼容和计划一致性门禁通过；PostgreSQL 为离线 SQL 生成验证，未执行实机运行测试。
