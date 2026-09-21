# DIST-009 — 完成首个无账号纵向切片：Canonical→Variant→QA→Approval→PublicationIntent→Manual Export。

状态：`done`  
阶段：7（Distribution 抽象、Manual Export 和 Fake Adapter）  
Owner：`team/distribution`  
优先级：`critical` / `P0`

## 目标

完成首个无账号纵向切片：Canonical→Variant→QA→Approval→PublicationIntent→Manual Export。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `CANON-006`
- `PROD-002`
- `QA-001`
- `POLICY-001`
- `APPROVAL-001`
- `DIST-003A`
- `DIST-007`
- `DIST-008B`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `DIST-009.implementation`
- `DIST-009.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/publication-intent.schema.json`
- `packages/contracts/jsonschema/export-package.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_dist_009.py`

## 实现规格

- `ManualExportVerticalSliceService.run` 接收同租户 CanonicalVersion、VariantVersion、QAReport、Approval、PolicyDecision 和 account-free TargetVersion 快照，按 Canonical→Variant→QA→Approval→PublicationIntent→Manual Export 顺序执行门禁。
- Canonical 必须 fact_checked/approved 且 freshness 为 fresh；Variant 必须 approved 并引用 Canonical；QA 必须 passed 且 subject 为 Variant；Approval 必须 distribution/content 且 approved；Policy 必须 allow。
- 仅允许无 account connection 且声明 `manual_export` 的 TargetVersion；调用现有 DistributionService 创建 PublicationIntent 并执行私有 ExportPackage，包引用必须 `private://`，不生成平台 PublicationRecord。
- 纵向命令按租户和输入哈希幂等，重放返回原始 stage projection；拒绝前置状态、跨租户 artifact、Policy/Approval 或目标不匹配时不写入分发事实，并记录审计摘要。
- 所有输出保持 PublicationIntent、ExportPackage 和 EventEnvelope Schema 边界；本切片不读取账号凭证、不调用平台 API、不产生网络副作用。
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

- `执行 DIST-009 的公开用例或内部命令`

Then：

- `完成首个无账号纵向切片：Canonical→Variant→QA→Approval→PublicationIntent→Manual Export。`
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- Canonical freshness 非 fresh/withdrawn、Variant 非 approved、QA 非 passed、Approval 未批准或 Policy deny 时，流程在对应阶段停止，不创建 PublicationIntent/ExportPackage。
- Variant 引用的 Canonical、QA subject、Approval org 或 TargetVersion org 不一致时拒绝，不能跨租户拼接纵向链路。
- 连接目标、未声明 manual_export 的目标和公开存储引用均拒绝；成功结果只包含私有 ExportPackage。
- 相同纵向幂等键重放不重复创建 Intent、包或事件；输入变化返回 `IDEMPOTENCY_KEY_REUSED`。

回滚：

- 关闭纵向入口，保留既有 Canonical、Variant、QA、Approval、Intent、ExportPackage 和审计事实。
- 本 revision 不创建业务表，纵向服务只组合现有投影；若需回退迁移，执行 `python -m alembic downgrade 20260919_found_dist_008b`。

## 验证

```text
python -m pytest tests/unit/distribution tests/integration --maxfail=1
```

Gate：`dist_009_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
