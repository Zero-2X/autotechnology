# FEEDBACK-LIVE-001 — 账号接入后增加真实平台归因、互动窗口、平台成本和线索质量观察。

状态：`planned`  
阶段：9（Analytics、Feedback Loop 和 Support）  
Owner：`team/feedback`  
优先级：`normal` / `M2`

## 目标

账号接入后增加真实平台归因、互动窗口、平台成本和线索质量观察。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `DIST-010`
- `ACCOUNT-002`
- `PLAT-003`
- `ANALYTICS-003`
- `FEEDBACK-CORE-005`

## 输入

准备性实现：`modules/feedback/live/service.py` 与本地 `ObservationPort`。
由组合入口注入 Analytics 的公开 ObservationService，不允许反馈模块导入其内部实现。
接口、逐条恢复语义与授权来源限制见 `docs/adr/ADR-002-live-feedback-observation-port.md`。
本地测试通过不代表完成本任务的真实平台验收，状态继续为 planned。

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `FEEDBACK-LIVE-001.implementation`
- `FEEDBACK-LIVE-001.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/observation.schema.json`

迁移计划：

- `packages/db/migrations/planned/feedback_live_001.sql`
## 目录边界

拥有目录：

- `modules/feedback/live`

允许目录：

- `modules/feedback/live`
- `packages/contracts`
- `packages/db/migrations`
- `tests/unit`
- `tests/integration`
- `tests/contract`

禁止目录：

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

- `执行 FEEDBACK-LIVE-001 的公开用例或内部命令`

Then：

- `账号接入后增加真实平台归因、互动窗口、平台成本和线索质量观察。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/feedback tests/integration --maxfail=1
```

Gate：`feedback_live_001_acceptance`

## 外部依赖

- `EXT-ACCOUNT-001`

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
