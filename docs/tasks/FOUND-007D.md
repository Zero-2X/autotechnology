# FOUND-007D — 将核心对象契约落到 `packages/contracts/jsonschema/*.schema.json`：必须包含 `$schema`、`$id`、`type`、`required`、`additionalProperties:false`、枚举、`oneOf` 和跨字段约束；Markdown 只作说明，不能作为机器真源。

状态：`done`
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/foundation`  
优先级：`critical` / `P0`

## 目标

将核心对象契约落到 `packages/contracts/jsonschema/*.schema.json`：必须包含 `$schema`、`$id`、`type`、`required`、`additionalProperties:false`、枚举、`oneOf` 和跨字段约束；Markdown 只作说明，不能作为机器真源。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-001`
- `FOUND-007A`
- `FOUND-007B`
- `FOUND-007C`

## 输入

- 字段目录对应的 49 个核心对象 Schema、任务注册表、本地契约引用。
- 已鉴权调用方注入的 org_id、Observation 与按 ID/版本读取的 MetricDefinition。

## 输出

- `scripts/check_json_schemas.py`：离线元 Schema、引用、对象边界检查。
- `infra/foundation/observation_contract.py`：指标定义、租户、版本和值 Schema 关联校验。
- `tests/contract/test_found_007d_core_schemas.py`、`tests/contract/test_found_007d_observation_binding.py`。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/foundation.schema.json`
- `packages/contracts/events/event-envelope.schema.json`
- `packages/contracts/jsonschema/topic-signal.schema.json`
- `packages/contracts/jsonschema/topic-opportunity.schema.json`
- `packages/contracts/jsonschema/topic-brief.schema.json`
- `packages/contracts/jsonschema/topic-score-snapshot.schema.json`
- `packages/contracts/jsonschema/canonical-content.schema.json`
- `packages/contracts/jsonschema/canonical-content-version.schema.json`
- `packages/contracts/jsonschema/variant-version.schema.json`
- `packages/contracts/jsonschema/content-variant.schema.json`
- `packages/contracts/jsonschema/asset.schema.json`
- `packages/contracts/jsonschema/asset-version.schema.json`
- `packages/contracts/jsonschema/publication-intent.schema.json`
- `packages/contracts/jsonschema/delivery-attempt.schema.json`
- `packages/contracts/jsonschema/export-package.schema.json`
- `packages/contracts/jsonschema/publication-record.schema.json`
- `packages/contracts/jsonschema/observation.schema.json`
- `packages/contracts/jsonschema/feedback-item.schema.json`
- `packages/contracts/jsonschema/source.schema.json`
- `packages/contracts/jsonschema/source-snapshot.schema.json`
- `packages/contracts/jsonschema/entity.schema.json`
- `packages/contracts/jsonschema/claim.schema.json`
- `packages/contracts/jsonschema/evidence.schema.json`
- `packages/contracts/jsonschema/knowledge-core.schema.json`
- `packages/contracts/jsonschema/knowledge-core-version.schema.json`
- `packages/contracts/jsonschema/platform.schema.json`
- `packages/contracts/jsonschema/rights-record.schema.json`
- `packages/contracts/jsonschema/rights-record-version.schema.json`
- `packages/contracts/jsonschema/distribution-target.schema.json`
- `packages/contracts/jsonschema/distribution-target-version.schema.json`
- `packages/contracts/jsonschema/account-profile.schema.json`
- `packages/contracts/jsonschema/authorization-evidence.schema.json`
- `packages/contracts/jsonschema/policy-decision.schema.json`
- `packages/contracts/jsonschema/account-connection.schema.json`
- `packages/contracts/jsonschema/region-profile.schema.json`
- `packages/contracts/jsonschema/region-profile-version.schema.json`
- `packages/contracts/jsonschema/policy-snapshot.schema.json`
- `packages/contracts/jsonschema/metric-definition.schema.json`
- `packages/contracts/jsonschema/approval.schema.json`
- `packages/contracts/jsonschema/approval-decision.schema.json`
- `packages/contracts/jsonschema/human-task.schema.json`
- `packages/contracts/jsonschema/feedback-action.schema.json`
- `packages/contracts/jsonschema/task-job.schema.json`
- `packages/contracts/jsonschema/outbox-event.schema.json`
- `packages/contracts/jsonschema/task-failure.schema.json`
- `packages/contracts/jsonschema/site-page-version.schema.json`
- `packages/contracts/jsonschema/geo-query-fixture.schema.json`
- `packages/contracts/jsonschema/geo-run.schema.json`
- `packages/contracts/jsonschema/webhook-receipt.schema.json`
- `packages/contracts/jsonschema/deletion-request.schema.json`
- `packages/contracts/jsonschema/kill-switch.schema.json`

迁移检查点（不包含业务 DDL）：

- `packages/db/migrations/versions/20260916_found_007d_core_contracts.py`
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

## 实现规格

1. 清点所有已登记核心对象，使用 Draft 2020-12 元 Schema 检查文件，检查对象闭合、required/枚举、租户字段和本地引用；模块 union 不强制伪造对象 type。
2. 修复字段生成器遗漏数字/布尔示例类型的问题；不得直接运行旧的全量生成器覆盖已接受的 Foundation 扩展。逐文件修复并测试。
3. Observation 按 metric_type 分为 number/boolean/string/enum/json，版本号为正整数；json 分支的具体结构还须结合固定 MetricDefinition 验证，不能把宽泛 JSON 类型检查等同于业务指标规则。
4. 核查 TargetVersion 的交付模式、连接与 synthetic/environment 组合，以及 PolicySnapshot 激活条件；只实现当前计划明确规定的约束，不臆造业务枚举。
5. 同租户外键和引用存在性属于数据库/领域校验，JSON Schema 的 UUID/nullable 规则不能代替授权。
6. 增加正反例、契约引用与 CI 检查；全量回归及证据齐备后才标记 done。

### 当前增量与未完成项

已修复数字/布尔示例生成空 Schema 的根因和全部字段目录对应标量，补齐 Observation 类型分支、版本号、TargetVersion 模式/环境/连接规则、TargetVersion/PublicationIntent 激活时 PolicySnapshot 约束。恢复被模块 alias 覆盖成自引用 union 的 Approval Schema，并防止生成器再次覆盖。新增 scripts/check_json_schemas.py 离线检查全部对象 Schema；structured-log 按 FOUND-005 保留明确的扩展字段例外。
已增加 MetricDefinition.quality_rules.value_schema，json/enum 必须提供；validate_observation 校验定义 ID/版本/type/key/租户，应用离线值 Schema，拒绝非 JSON 数值，不修改输入。49 个核心对象已逐文件登记到本任务 contract_refs，测试强制覆盖注册和对象闭合。
Approval 的 approved 分支要求满足 quorum、足够且唯一的 decision_ids、approved 决策、reviewer 与 decided_at；12 项正反例覆盖。不同审批人及禁止自审由后续审批用例校验真实投票记录，不将 UUID 数量等同于授权。
新增跨字段正反例覆盖 Variant/Asset 批准快照、PublicationIntent ready/queued 快照、PolicySnapshot 全局/租户边界、AccountConnection 授权状态以及 DeliveryAttempt 连接条件。新增 scripts/check_foundation_contracts.py 本地/CI 共用入口，缺失前端工具或任一门禁失败即停止，不自动刷新基线。迁移为连续无 DDL 检查点，不能宣称数据库 FK 已实现。完整门禁通过：233 passed，无跳过；证据已归档。前期整体审计的独立问题继续跟踪，不随本任务关闭。

## 权限、幂等、失败和审计

- 由 `TenantContext` 注入 `org_id` 和 actor；跨租户访问必须拒绝。
- 写命令使用 `Idempotency-Key` 和 payload hash；状态修改使用 `If-Match` 或 expected version。
- 确定性校验失败不重试；临时失败按任务卡与策略退避；未知外部结果转人工核查。
- 记录 `trace_id`、actor、输入/输出版本、Policy 快照、拒绝原因、耗时和成本。

## Given–When–Then

Given：

- `49 个登记的核心对象 Schema，以及 synthetic 正反例`
- `调用方注入租户与按 ID/version 固定的指标定义`

When：

- `执行离线 Schema 门禁、validate_observation 和跨字段反例`

Then：

- `将核心对象契约落到 `packages/contracts/jsonschema/*.schema.json`：必须包含 `$schema`、`$id`、`type`、`required`、`additionalProperties:false`、枚举、`oneOf` 和跨字段约束；Markdown 只作说明，不能作为机器真源。`
- `未知字段、类型/版本/租户错配、非法模式/状态与缺失快照被拒绝；全量测试及引用/迁移图通过。`
- `本任务无存储写入或外部副作用，不新增业务审计事件；运行证据记录到 FOUND-007D-EVIDENCE.yaml。`

## 验证

```text
python -m pytest tests/contract tests/integration --maxfail=1
python scripts/check_json_schemas.py
python -m pytest tests/contract/test_found_007d_core_schemas.py -q
python scripts/check_foundation_contracts.py
```

Gate：`found_007d_acceptance`

## 外部依赖

- 无

## 开工前细化

已按上述实现规格细化并完成契约任务验收。运行时装配、数据库关联与真实业务权限不在此任务的完成声明中。
