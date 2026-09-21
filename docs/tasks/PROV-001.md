# PROV-001 — 实现 Source、SourceSnapshot、抓取方式、原文哈希和可信度。

状态：`done`  
阶段：3（Provenance、Rights、KnowledgeCore 和 Canonical Content）  
Owner：`team/provenance`  
优先级：`critical` / `P0`

## 目标

实现 Source、SourceSnapshot、抓取方式、原文哈希和可信度。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `FOUND-003A`
- `FOUND-003B`
- `TOPIC-002`
- `TOPIC-004`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `PROV-001.implementation`
- `PROV-001.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/source.schema.json`
- `packages/contracts/jsonschema/source-snapshot.schema.json`

迁移：

- `packages/db/migrations/versions/20260918_prov_001.py`

## 实现规格

- `Source` 保存 `id`、`org_id`、`source_type`、`fetch_method`、`canonical_url`、`status`、`current_snapshot_id`、`confidence`、版本和创建时间；同一租户的规范 URL 只能注册一次。
- `SourceSnapshot` 保存采集时间、SHA-256 `content_hash`、`private://` 对象引用、条款快照引用、置信度和状态；原文不写入业务表，内容只能通过私有对象引用回取。
- ingest 在一个事务内写入 Source、首个 captured snapshot、`source.ingested` 事件和幂等命令；命令 payload hash 只覆盖调用方输入，生成的时间戳不破坏重放。
- 快照状态只允许 `captured → quarantined → usable` 或转入 `expired/revoked/blocked`；终态需要原因，状态写入使用 expected version 并追加 `source.snapshot.*` 与 Source 投影事件。
- `source_commands`、`source_events` 和 `source_snapshot_state_events` 追加不可变；快照身份字段和原文哈希不可变，跨租户查询与状态修改统一拒绝。

## 补充场景

- 相同租户和幂等键重复提交相同输入返回原结果；输入、内容哈希或 URL 改变返回 `IDEMPOTENCY_KEY_REUSED` 或 `SOURCE_ALREADY_EXISTS`。
- 不同租户读取、状态迁移或验证已有 Source/SourceSnapshot 返回 `TENANT_SCOPE_VIOLATION`，数据库层复合外键阻止跨租户事件挂接。
- 过期、撤回和阻断没有原因、版本过期或尝试从终态迁移时不改变状态、不追加事件；原文哈希验证返回 expected/actual 摘要而不暴露原文。
- 服务重启后可从 SQLite 文件恢复 Source、快照、命令和审计事件；事件信封通过已注册的 JSON Schema 校验。
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

- `执行 PROV-001 的公开用例或内部命令`

Then：

- `实现 Source、SourceSnapshot、抓取方式、原文哈希和可信度。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/provenance tests/integration --maxfail=1
```

Gate：`prov_001_acceptance`

## 回滚与运行说明

- 通过任务级 feature flag 或路由开关暂停新的抓取命令；已保存的哈希、私有对象引用和审计事件不删除。
- 迁移使用 expand/contract 顺序；验证失败时停止后续任务并保留兼容表，不执行破坏性升级回滚。需要回退时先停止写入，再按 Alembic downgrade 清理本任务新增表和触发器。
- 抓取结果未知时只保留 captured/quarantined 记录并转人工核查；原始对象仍留在私有存储，重试必须复用原幂等键。

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。

## Implementation Evidence

- `modules/provenance/source.py`：Source/SourceSnapshot ingest、内容规范化与 SHA-256、私有对象引用、可信度和抓取方式校验、幂等命令、快照状态机、验证报告和租户隔离。
- `modules/provenance/infrastructure/source_schema.py` 与 `packages/db/migrations/versions/20260918_prov_001.py`：五张租户范围表、复合外键、检查约束、不可变字段和追加式审计触发器。
- `apps/api/main.py`：`/v1/sources` ingest 入口、内部快照/状态/验证命令，以及统一错误映射。
- `tests/unit/provenance/test_source.py` 与 `tests/integration/test_provenance.py`：幂等重放、哈希保密、状态版本、原因、租户隔离、事件 Schema、重启恢复和 API 行为。
- `docs/foundation/PROV-001-EVIDENCE.yaml`：专项门禁结果。
