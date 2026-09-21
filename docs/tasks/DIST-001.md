# DIST-001 — 定义 `DistributionTarget`、不可变 `DistributionTargetVersion`、`PublicationIntent`、`ExportPackage`、`DeliveryAttempt`、`PublicationRecord`。

状态：`done`  
阶段：7（Distribution 抽象、Manual Export 和 Fake Adapter）  
Owner：`team/distribution`  
优先级：`critical` / `P0`

## 目标

定义 `DistributionTarget`、不可变 `DistributionTargetVersion`、`PublicationIntent`、`ExportPackage`、`DeliveryAttempt`、`PublicationRecord`，并提供无凭证的 manual export 与 simulation 执行路径。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `FOUND-010`
- `ACCOUNT-CORE-001`
- `POLICY-001`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `DIST-001.implementation`
- `DIST-001.tests`
- `audit_evidence`

## 实现规格

实现规格：

- `DistributionService.create_target` 生成 Schema 闭合的 `DistributionTarget`；`create_target_version` 生成不可变快照、版本号、`snapshot_hash` 和 `etag`，并按账户连接/合成目标约束可用 delivery mode。
- `create_publication_intent` 固定 variant、asset、target version、payload、region、capability hash 和 policy snapshot 引用；审批引用存入租户内不可变 metadata，公共投影仍遵循 `publication-intent.schema.json`。
- `execute` 先验证同租户 `PolicyDecision.final_decision=allow` 和（若 intent 绑定）已批准 Approval；失败返回 `PUBLICATION_BLOCKED`，不创建 DeliveryAttempt 或 PublicationRecord。
- 只实现 `manual_export` 与 `simulation`：manual export 生成 `private://` ExportPackage 和成功的 `manual:export` DeliveryAttempt；simulation 通过可替换 FakePublisher，永不发起 HTTP，写入 `result_snapshot.simulated=true`、重放输入哈希和 `publication.simulated` EventEnvelope。
- `authorized_api` 没有 AccountConnection 时返回 `ACCOUNT_CONNECTION_REQUIRED`；当前阶段对已有连接的 `draft_only`/`authorized_api` 返回 `DELIVERY_MODE_UNSUPPORTED`，不伪造平台成功结果。
- `(org_id, idempotency_key)` 按 payload hash 幂等；`(org_id, intent_id, attempt_no)` 唯一。所有返回投影经过对应 JSON Schema 校验，跨租户读取或写入拒绝。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/distribution-target.schema.json`
- `packages/contracts/jsonschema/distribution-target-version.schema.json`
- `packages/contracts/jsonschema/publication-intent.schema.json`
- `packages/contracts/jsonschema/export-package.schema.json`
- `packages/contracts/jsonschema/delivery-attempt.schema.json`
- `packages/contracts/jsonschema/publication-record.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_dist_001.py`
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

- `DistributionService 创建目标、目标版本和 PublicationIntent`
- `execute` 使用允许的 PolicyDecision 执行 `manual_export` 或 `simulation`

Then：

- `六类投影均符合闭合 JSON Schema，目标版本不可变且带快照哈希`
- `manual_export` 只生成私有导出包；`simulation` 只生成 Fake 记录和 simulated 事件，不调用 HTTP
- `PolicyDecision`/Approval 不满足时没有投递事实；同一幂等键重放原结果
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- 未通过 approval 或 policy gate 时返回 `PUBLICATION_BLOCKED`，不生成 PublicationRecord。
- simulation 成功必须写入 `simulated=true`、可重放输入哈希和 `publication.simulated` 事件。
- 未知外部结果（仅未来 authorized_api）转 `unknown` 并创建 HumanTask，当前阶段不得模拟为成功。


## 回滚与运行说明

- 通过任务级 feature flag 关闭新命令；已提交的业务事实和审计记录不删除。
- 迁移按 expand/contract 顺序执行；验证失败时停止后续任务，保留兼容字段，不执行破坏性回滚。
- 如产生可重试任务，先暂停对应队列，再按原幂等键重放；任何外部未知结果必须转人工核查。

## 验证

```text
python -m pytest tests/unit/distribution tests/integration --maxfail=1
```

Gate：`dist_001_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
