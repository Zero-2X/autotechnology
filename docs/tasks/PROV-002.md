# PROV-002 — 实现 RightsRecord 身份对象、不可变 RightsRecordVersion、授权范围、期限、地区、语言、媒体、商业使用和撤销事件。

状态：`done`  
阶段：3（Provenance、Rights、KnowledgeCore 和 Canonical Content）  
Owner：`team/provenance`  
优先级：`critical` / `P0`

## 目标

实现 RightsRecord 身份对象、不可变 RightsRecordVersion、授权范围、期限、地区、语言、媒体、商业使用和撤销事件。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `TOPIC-004`
- `PROV-001`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `PROV-002.implementation`
- `PROV-002.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/rights-record.schema.json`
- `packages/contracts/jsonschema/rights-record-version.schema.json`

迁移：

- `packages/db/migrations/versions/20260918_prov_002.py`

## 实现规格

- `RightsRecord` 是按租户和 Source 绑定的身份对象，保存当前授权版本指针及 `pending/verified/expired/revoked/complaint_hold` 投影状态。
- `RightsRecordVersion` 以递增 `version_no` 保存 SourceSnapshot 引用、许可证/合同/证据引用、条款摘要、权利人、地区/语言/媒体范围、用途、有效期、Policy 规则版本和可复算 `snapshot_hash`。
- 创建版本要求所有 SourceSnapshot 属于同一租户和同一 Source；首个版本原子创建身份对象、版本、`rights.version.created` 和幂等命令，后续版本通过 `supersedes_version_id` 保留历史。
- `verify` 只允许 pending 版本，要求所有快照为 usable、至少一个授权证据、条款摘要、Policy 版本和人工验证原因；成功时原子写入 verified 元数据、父指针和 `rights.version.verified`。
- `expire`、`revoke`、`hold_complaint` 只允许 verified 版本，必须带原因、expected version，并清空不可发布的父当前指针；版本身份字段和事件记录由数据库触发器保护。

## 补充场景

- 相同幂等键和输入返回原结果；改变授权范围、证据或版本条件返回 `IDEMPOTENCY_KEY_REUSED`，并发版本写入返回 `VERSION_CONFLICT`。
- 跨租户读取、创建或状态修改拒绝；混用不同 Source 的快照、快照未达 usable、缺证据或期限倒置均不改变任何记录。
- 已 verified 版本不能原地改权利人、范围、用途、快照列表或摘要；新授权只能创建递增 draft/pending 版本并保留旧版本事件。
- 版本事件信封通过已登记 Schema 校验，SQLite 文件重启后父对象、版本、幂等结果和事件 sequence 可重建。
## 目录边界

拥有目录：

- `modules/provenance`

允许目录：

- `modules/provenance`
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

- `执行 PROV-002 的公开用例或内部命令`

Then：

- `实现 RightsRecord 身份对象、不可变 RightsRecordVersion、授权范围、期限、地区、语言、媒体、商业使用和撤销事件。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/provenance tests/integration --maxfail=1
```

Gate：`prov_002_acceptance`

## 回滚与运行说明

- 通过任务级开关暂停新授权验证和撤销命令；历史授权事实与审计事件保留，不做物理删除。
- Alembic 迁移先扩展 rights 表和索引，再启用不变性触发器；验证失败时停止写入并保留兼容列，回退前先暂停队列和人工核查任务。
- 外部授权状态未知时保持 pending 或 complaint_hold，不能自动恢复 verified；重试复用原幂等键并保留原始证据引用。

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。

## Implementation Evidence

- `modules/provenance/rights.py`：RightsRecord/Version 创建、授权范围校验、SourceSnapshot 租户/状态检查、验证与撤销状态机、内容摘要、幂等和事件投影。
- `modules/provenance/infrastructure/rights_schema.py` 与 `packages/db/migrations/versions/20260918_prov_002.py`：身份/版本/命令/事件表、复合外键、范围约束、版本不可变和追加式审计触发器。
- `apps/api/main.py`：`/v1/rights-records/{record_id}/versions` 创建和 `/verify` 验证入口，以及内部终态命令。
- `tests/unit/provenance/test_rights.py` 与 `tests/integration/test_rights_api.py`：摘要重放、usable 前置、租户隔离、版本冲突、不可变篡改、终态原因和 API 行为。
- `docs/foundation/PROV-002-EVIDENCE.yaml`：专项门禁结果。
