# PROV-003 — 实现无授权阻断、到期提醒、投诉冻结和派生内容反向追踪。

状态：`done`  
阶段：3（Provenance、Rights、KnowledgeCore 和 Canonical Content）  
Owner：`team/provenance`  
优先级：`critical` / `P0`

## 目标

实现无授权阻断、到期提醒、投诉冻结和派生内容反向追踪。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `WORKFLOW-CORE-002`
- `TOPIC-004`
- `PROV-002`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `PROV-003.implementation`
- `PROV-003.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/rights-record.schema.json`
- `packages/contracts/jsonschema/rights-record-version.schema.json`

迁移：

- `packages/db/migrations/versions/20260918_prov_003.py`

## 实现规格

- `RightsGuardService.check_authorization` 在使用前读取租户范围的 RightsRecordVersion，按状态、有效期、地区、语言、媒体和用途层级返回 allow/deny、稳定原因码、快照摘要和审计决定；缺少 verified 授权默认阻断。
- 到期扫描按 horizon/lead 窗口生成幂等 `rights_expiry_reminders`，不提前篡改授权事实；`expire_due` 到期后使用 RightsRecordVersion 的 expected version 写入 `rights.version.expired`。
- `register_lineage` 只允许 verified 权利版本登记派生对象，支持父派生对象继续挂接子对象；边记录包含租户、关系、创建人、权利快照摘要和私有元数据。
- `freeze_complaint` 原子调用 complaint_hold 状态迁移并沿 lineage 写入不可变 `rights_derivative_blocks`；撤回/过期同样可调用阻断投影，不能自动恢复授权。
- guard 命令、决定、提醒、lineage 边和阻断记录均追加不可变，跨租户查询、父边缺失、重复派生目标和幂等键复用均确定性拒绝。

## 补充场景

- 匹配授权范围和有效时间返回 allowed；任一范围、用途、状态或时间检查失败返回 blocked 与完整原因集合，且不暴露原文。
- 相同扫描幂等键返回相同提醒集合；重复扫描不创建重复提醒，投诉冻结重复提交返回原状态与原阻断结果。
- 两层以上派生链可从 RightsRecordVersion 反向追踪；冻结根权利时所有后代均产生阻断记录，跨租户边不能作为父节点。
- SQLite 文件重启后决定、提醒、lineage 和阻断记录可读；底层 UPDATE/DELETE 由触发器拒绝。
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

- `执行 PROV-003 的公开用例或内部命令`

Then：

- `实现无授权阻断、到期提醒、投诉冻结和派生内容反向追踪。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/provenance tests/integration --maxfail=1
```

Gate：`prov_003_acceptance`

## 回滚与运行说明

- 通过任务级开关暂停授权判定、到期扫描和投诉冻结命令；已产生的 deny、reminder、lineage 与 block 证据不删除。
- 迁移先创建 guard/lineage 表和索引，再启用追加式触发器；验证失败时停止写入，回退前暂停相关 Worker 并保留历史权利事件。
- 外部状态不确定时保持 blocked 或 complaint_hold，等待人工提供新的授权证据；重试必须复用原幂等键。

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。

## Implementation Evidence

- `modules/provenance/guard.py`：授权判定、到期提醒、自动到期迁移、投诉冻结、lineage 注册/遍历和派生阻断。
- `modules/provenance/infrastructure/rights_guard_schema.py` 与 `packages/db/migrations/versions/20260918_prov_003.py`：决定、提醒、lineage、阻断和 guard 幂等表及追加式触发器/复合外键。
- `apps/api/main.py`：内部 guard/check、expiry-reminders、lineage 和 complaint-hold 命令入口。
- `tests/unit/provenance/test_rights_guard.py` 与 `tests/integration/test_rights_guard_api.py`：allow/deny、幂等扫描、多层反向追踪、投诉冻结、租户隔离和篡改拒绝。
- `docs/foundation/PROV-003-EVIDENCE.yaml`：专项门禁结果。
