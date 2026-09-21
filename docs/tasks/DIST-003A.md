# DIST-003A — 实现 `ManualAdapter` 导出标题、正文、媒体、标签、披露、检查清单和证据包。

状态：`done`  
阶段：7（Distribution 抽象、Manual Export 和 Fake Adapter）  
Owner：`team/distribution`  
优先级：`critical` / `P0`

## 目标

实现确定性的 `ManualAdapter`，把标题、正文、媒体、标签、披露、检查清单和证据摘要组装成私有导出包。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `PROD-002`
- `POLICY-001`
- `DIST-001`
- `DIST-002`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `DIST-003A.implementation`
- `DIST-003A.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/export-package.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_dist_003a.py`

## 实现规格

- `ManualAdapter.export` 校验租户范围和 PublicationIntent payload，稳定排序媒体、检查清单与证据，生成 `manifest.json`、内容文件索引和 SHA-256 包哈希。
- ExportPackage 使用 `private://distribution/...` 对象引用，保留 variant/asset 与 approval refs、过期时间和可撤回状态；不生成公开 URL，不调用平台或对象存储网络接口。
- 仅接受 `private://` 媒体源，外部公开媒体 URL 直接返回 `PUBLIC_MEDIA_URL_FORBIDDEN`；同一租户同一幂等键按输入哈希重放原包。
- 追加 `distribution.manual_export.created` EventEnvelope 和审计摘要，文件内容与 manifest 均可离线复现。
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

- `ManualAdapter.export` 接收 PublicationIntent、内容、媒体、检查清单和 evidence refs

Then：

- `输出的 ExportPackage 符合闭合 Schema，manifest 覆盖标题、正文、媒体、标签、披露、检查清单和证据`
- `所有对象引用为 private://；公开媒体、跨租户 intent 和幂等键 payload 复用被拒绝`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/distribution tests/integration --maxfail=1
```

Gate：`dist_003a_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
