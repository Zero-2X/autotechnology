# DIST-007 — 实现 `manual_export`、`simulation`、`draft_only`、`authorized_api` 四种唯一交付模式。

状态：`done`  
阶段：7（Distribution 抽象、Manual Export 和 Fake Adapter）  
Owner：`team/distribution`  
优先级：`critical` / `P0`

## 目标

实现 `manual_export`、`simulation`、`draft_only`、`authorized_api` 四种唯一交付模式。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `FOUND-008`
- `POLICY-001`
- `DIST-003A`
- `DIST-004`
- `DIST-006C`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `DIST-007.implementation`
- `DIST-007.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/publication-intent.schema.json`
- `packages/contracts/jsonschema/distribution-target-version.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_dist_007.py`

## 实现规格

- `DistributionService` 使用 `delivery-mode.schema.json` 的四值枚举作为唯一模式边界；PublicationIntent 只能选择目标版本声明的一个模式，重复模式、未声明模式和跨租户目标均拒绝。
- `manual_export` 生成私有 ExportPackage，不产生公开 URL；`simulation` 仅调用无网络 FakePublisher 并生成 simulated PublicationRecord；两者保持既有策略、审批、幂等和租户校验。
- `draft_only` 与 `authorized_api` 只允许带 account connection 的 TargetVersion，在 Policy allow 后进入 `PublicationIntent.status=queued`，创建契约合法的 `DeliveryAttempt.status=created` 和 `publication.queued` 事件；本切片不调用真实平台、不生成 PublicationRecord。
- 连接模式的 attempt 保留 account connection snapshot、provider idempotency key 和原始 payload 快照，使用 sandbox/authorized provider_mode 区分环境；重放相同命令返回同一队列投影。
- 四种模式都记录 actor、trace、input/output hash 和拒绝原因；失败不会绕过 Policy/Approval，也不会把队列投影伪造成成功发布。
## 目录边界

拥有目录：

- `modules/distribution`

允许目录：

- `modules/distribution`
- `adapters/contract`
- `adapters/manual`
- `adapters/fake`
- `tests/replay`
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

- `执行 DIST-007 的公开用例或内部命令`

Then：

- `实现 `manual_export`、`simulation`、`draft_only`、`authorized_api` 四种唯一交付模式。`
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- synthetic target 只能选择 manual_export/simulation；连接目标只能选择 draft_only/authorized_api；模式不匹配或重复声明必须在写入前拒绝。
- manual_export 的包引用保持 `private://`；simulation 的结果标记 `simulated=true`；draft_only/authorized_api 只有 queued attempt，没有外部对象或成功 PublicationRecord。
- 同一租户同一幂等键重放返回原结果，不重复创建包、attempt 或队列事件；跨租户目标、缺失连接、Policy deny 和未批准 Approval 不产生投递事实。
- 队列模式使用原始 account connection snapshot 和 provider idempotency key，供后续授权 worker 安全接管；本命令本身的 `side_effect_triggered` 必须为 false。

回滚：

- 关闭 draft_only/authorized_api 队列入口，保留既有四模式意图、attempt、包、记录、事件和审计事实。
- 本 revision 不创建业务表，模式路由使用内存投影；若需回退迁移，执行 `python -m alembic downgrade 20260919_found_dist_006c`，不删除既有交付事实。

## 验证

```text
python -m pytest tests/unit/distribution tests/integration --maxfail=1
```

Gate：`dist_007_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
