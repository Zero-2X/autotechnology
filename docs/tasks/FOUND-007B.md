# FOUND-007B — 创建业务事件 JSON Schema、事件版本和向后兼容检查。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/foundation`  
优先级：`critical` / `P0`

## 目标

创建业务事件 JSON Schema、事件版本和向后兼容检查。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-001`
- `FOUND-004A`
- `FOUND-007A`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `docs/foundation/event-compatibility-baseline-v1.yaml`：162 个当前事件的版本、注册元数据、envelope/payload 必填字段和约束快照。
- `scripts/check_event_compatibility.py`：检查事件注册表、事件 Schema、本地 ref、版本和向后兼容性。
- `scripts/generate_event_compatibility_baseline.py`：从已接受的事件注册表和 Schema 生成确定性基线。
- `packages/contracts/jsonschema/event-compatibility-baseline.schema.json`：基线机器契约并纳入 foundation union。
- `packages/db/migrations/versions/20260916_found_007b_events.py`：不新增业务表的连续检查点。
- `tests/contract/test_found_007b_events.py`、`tests/integration/test_found_007b_events_integration.py`。
- `docs/foundation/FOUND-007B-EVIDENCE.yaml`。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/foundation.schema.json`
- `packages/contracts/events/event-envelope.schema.json`
- `packages/contracts/jsonschema/event-compatibility-baseline.schema.json`

迁移 revision：

- `packages/db/migrations/versions/20260916_found_007b_events.py`
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

1. 事件注册表 `docs/contracts/event-registry.yaml` 是事件类型、producer、aggregate、`event_kind`、`replay_policy` 和 Schema ref 的机器索引；当前 162 个事件必须唯一、可解析且每个 ref 都存在。
2. 每个事件 Schema 必须使用 Draft 2020-12，包含 `$id`、`allOf` envelope ref、与注册表一致的 `event_type` const、正整数 `event_schema_version` const、对象 payload 和 `aggregate_id/aggregate_version` 必填字段；事件元数据扩展必须与注册表一致。
3. `event_schema_version` 是同一事件类型的兼容版本。v1 基线禁止在原 Schema ref 上直接改变版本、删除已有事件、删除已有 required 字段、增加新的 required payload 字段或收窄既有约束；这些变化必须先建立新的版本化 Schema ref/事件版本。
4. 允许新增事件类型、增加 optional payload 字段和增加不收窄的响应/枚举范围；新增事件只产生 warning，不要求本任务实现业务 producer。
5. envelope 基线必须冻结租户、trace、aggregate、actor、幂等和 payload hash 字段的存在性与约束；不得包含真实 payload、token、secret 或凭证。
6. checker 只读、无网络、无数据库写入；支持 `--strict`、临时 registry/baseline 输入和稳定错误路径，供 CI 及后续任务复用。
7. 2026-09-17 增量：递归比较已快照的 payload property 中的 properties、required、items、additionalProperties、数组长度和唯一性；类型集合扩展与 integer → number 允许通过。排序键固定为 aggregate_id，消费者去重键固定为 event_id。
8. 根级 payload 全部非注释约束参与比较；事件根、envelope 分支、specific 分支及类型/版本 const 的额外验证约束禁止静默绕过。对组合 Schema、引用、条件等未实现语义包含证明的关键字保守拒绝并提示版本评审。现有 v1 payload 无引用依赖快照，因此含引用的新增可选字段也拒绝；字面量 const/examples 中的 `$ref` 不作引用。
9. `infra/foundation/event_validation.py` 提供 `EventSchemaRegistry`：按 event_type + 整数版本注册/选择不可覆盖的校验器，深复制 Schema 和显式资源包；校验格式与 JSON 数值，不回退版本、不在线取引用。注册时检查所有 Schema 位置的离线引用，支持嵌套 `$id` 和递归引用。无效输入和引用错误不在异常链中泄露载荷。消费者业务处理、持久化去重和 Outbox 派发仍由各自运行时任务负责。

## 权限、幂等、失败和审计

- 由 `TenantContext` 注入 `org_id` 和 actor；跨租户访问必须拒绝。
- 写命令使用 `Idempotency-Key` 和 payload hash；状态修改使用 `If-Match` 或 expected version。
- 确定性校验失败不重试；临时失败按任务卡与策略退避；未知外部结果转人工核查。
- 记录 `trace_id`、actor、输入/输出版本、Policy 快照、拒绝原因、耗时和成本。
- 事件版本升级必须保留旧版本 Schema ref，消费者按 `event_type + event_schema_version` 选择解析器；禁止静默覆盖旧版本语义。

## Given–When–Then

Given：

- `所有前置任务已完成`
- `TenantContext、trace_id 和 Idempotency-Key 可用`

When：

- `执行 FOUND-007B 的公开用例或内部命令`

Then：

- `当前 162 个事件注册项和 Schema 全部通过结构、ref、event_type、版本和元数据一致性检查。`
- `删除事件/required 字段、增加 required payload 字段、修改 event_type/version 或收窄约束的临时变体被稳定拒绝。`
- `新增事件和 optional 字段只产生兼容结果或 warning，不生成业务 producer。`
- `EventEnvelope 生成的事件可通过 envelope 和对应事件 Schema 的边界检查；跨租户和幂等语义仍由 FOUND-004B 保持。`
- `输出契约、迁移、证据、指定测试结果可复现。`

## 验证

```text
python -m pytest tests/contract/test_found_007b_events.py tests/integration/test_found_007b_events_integration.py -q
python -m pytest tests/contract/test_found_007b_envelope_regressions.py -q
python -m pytest tests/contract/test_found_007b_versioned_consumers.py -q
python scripts/check_event_compatibility.py --strict
python scripts/check_task_card_precision.py --task FOUND-007B --strict
python scripts/check_migrations.py --strict --json
python -m pytest tests --maxfail=1 -q
```

Gate：`found_007b_acceptance`

## 外部依赖

- 无

## 开工前细化

已完成开工前细化：事件注册表、Schema 版本边界、required/constraint 兼容规则、旧版本保留策略、临时变体测试、迁移检查点和无副作用边界已冻结。本任务不重写既有 162 个事件 payload，也不创建真实 producer 或业务表。
