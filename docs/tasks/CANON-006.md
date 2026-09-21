# CANON-006 — 建立 `canonical → variant → asset → publication` lineage 查询。

状态：`done`  
阶段：3（Provenance、Rights、KnowledgeCore 和 Canonical Content）  
Owner：`team/canonical_content`  
优先级：`critical` / `P0`

## 目标

建立 `canonical → variant → asset → publication` lineage 查询。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `TOPIC-004`
- `CANON-002`
- `CANON-004`
- `CANON-005`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `CANON-006.implementation`
- `CANON-006.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/lineage-query.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_canon_006.py`
## 目录边界

拥有目录：

- `modules/canonical_content`

允许目录：

- `modules/canonical_content`
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

## 实现规格

- 提供只读 `LineageQuery` 用例，以 `canonical_content_id` 或 `canonical_content_version_id` 为根，返回 `canonical → variant → asset → publication` 的节点和边。
- Canonical 节点来自本模块的租户范围版本；Variant、Asset 和 Publication 通过已登记的查询 Port 读取，不能在本任务内直接写其他模块表，也不能因为下游对象缺失伪造节点。
- 节点统一包含 `type`、`id`、`org_id`、`status`、`version` 和 `metadata_ref`；边统一包含 `from`、`to`、`relation` 和 `created_at`。所有结果按类型、版本和 ID 稳定排序并通过 `lineage-query.schema.json` 校验。
- 查询必须拒绝跨租户根、跨 Canonical 根和不存在的版本；下游没有记录时返回已存在的上游节点和空边，不把“未接入”误报为已发布。
- 查询不产生发布、刷新或其他外部副作用；仅在同一命令幂等键下保存可复算的查询摘要和审计事件（如实现存储投影），不得修改 Canonical、Variant、Asset 或 Publication 事实。
- `CanonicalLineageService.query` 是内部用例。Variant 和 Asset Port 分别按 Canonical 版本 ID、Variant 版本 ID 查询；Publication Port 可返回以 Asset 版本或 Variant 版本为父级的记录，支持无素材的文本发布。Port 返回的 `parent_id` 必须在本次查询已验证的上游集合中。
- 结果增加 `unavailable_stages`，明确区分未接入 Port 与已接入但无记录；查询返回 `query_hash`，同租户同幂等键重放首个快照。`canonical_lineage_queries` 以追加式记录请求摘要、响应摘要、actor、trace 和响应，不修改业务事实。
- 历史 Canonical 版本的 lineage 状态投影为 `superseded`，撤回版本投影为 `withdrawn`，并附 `is_current`；根查询包含所有版本，版本查询仅包含指定版本及其根。

补充场景：

- Given 一个 Canonical 版本有两个 Variant、一个 Asset 和两个 Publication 记录，When 查询，Then 返回全部节点和确定性排序的三段边。
- Given Variant 或 Asset 尚未创建，When 查询，Then 保留已有 Canonical 节点并返回空的对应下游边，不创建占位事实。
- Given 根对象或下游对象属于另一个 `org_id`，When 查询，Then 返回 `TENANT_SCOPE_VIOLATION`，不泄漏节点 ID 或状态。
- Given 同一查询幂等键和参数重复提交，When payload 相同，Then 返回相同 `query_hash`；payload 不同返回 `IDEMPOTENCY_KEY_REUSED`。
- Given 版本已被 supersede 或 withdrawn，When 查询，Then 仍可读取历史版本及其已存在的边，但不得把它标记为当前可发布版本。

## 回滚

- 停止新的 lineage 查询入口并保留已产生的查询摘要和审计记录；不删除 Canonical 或下游业务事实。
- planned migration 在验证失败时不执行；进入版本迁移后只追加兼容修订，不重写 `CANON-001`～`CANON-005` 的历史迁移。

## Given–When–Then

Given：

- `所有前置任务已完成`
- `TenantContext、trace_id 和 Idempotency-Key 可用`

When：

- `执行 CANON-006 的公开用例或内部命令`

Then：

- `建立 `canonical → variant → asset → publication` lineage 查询。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/canonical_content tests/integration --maxfail=1
```

Gate：`canon_006_acceptance`

## 外部依赖

- 无

## 开工前细化

已细化并实现本卡。契约、迁移、Port 边界和验收测试可在 `CANON-006-EVIDENCE.yaml` 中复核。

## 开发入口

Variant、Asset 和 Publication 的实体 Schema 已存在，下游事实服务尚未实现。已建立只读 Port 并用受控投影测试全链路；默认查询明确标出未接入阶段，不虚构发布记录。后续下游任务负责接入真实 Port。
