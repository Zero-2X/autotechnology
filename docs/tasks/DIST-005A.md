# DIST-005A — 实现 capability matrix 和平台字段 mapping；平台字段只能留在 adapter 层。

状态：`done`  
阶段：7（Distribution 抽象、Manual Export 和 Fake Adapter）  
Owner：`team/distribution`  
优先级：`critical` / `P0`

## 目标

实现租户范围的 capability matrix 和平台字段 mapping；平台字段只能留在 adapter 层。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `POLICY-001`
- `DIST-002`
- `DIST-004`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `DIST-005A.implementation`
- `DIST-005A.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/publisher-capability.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_dist_005a.py`

## 实现规格

- `CapabilityMatrix` 校验 PublisherCapability，冻结 capability/version 与 canonical 字段映射；只接受 `title`、`body`、`tags`、`disclosure`、`media` 作为核心 payload 键。
- `map_payload` 输出只供 adapter 使用的平台字段名，并在 capability 缺少目标 action、canonical payload 混入平台字段或映射重复时拒绝；平台字段不会写入 Distribution 核心投影。
- `CapabilityMatrixRegistry` 按 `(org_id, platform_id, version)` 追加不可变快照，payload hash 幂等重放，跨租户读取拒绝，并追加 `distribution.capability_matrix.registered` EventEnvelope。
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

- `注册 capability matrix 并把标准 PublicationIntent payload 映射到 FakeOfficialAdapter 字段`

Then：

- `能力版本和 mapping 快照不可覆盖，核心 payload 不接受平台字段`
- `映射结果只在 adapter 边界出现，事件、租户和幂等审计可复现`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/distribution tests/integration --maxfail=1
```

Gate：`dist_005a_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
