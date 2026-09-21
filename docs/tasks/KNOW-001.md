# KNOW-001 — 实现 Entity、Claim、Evidence、适用版本/地区/时间和事实类型。

状态：`done`  
阶段：3（Provenance、Rights、KnowledgeCore 和 Canonical Content）  
Owner：`team/knowledge`  
优先级：`critical` / `P0`

## 目标

实现 Entity、Claim、Evidence、适用版本/地区/时间和事实类型。

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

- `KNOW-001.implementation`
- `KNOW-001.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/entity.schema.json`
- `packages/contracts/jsonschema/claim.schema.json`
- `packages/contracts/jsonschema/evidence.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_know_001.py`

## 实现规格

- `KnowledgeService` 以 `org_id` 为所有 Entity、Claim、Evidence、关系、命令和事件查询/写入边界；跨租户 ID 只返回稳定的 `TENANT_SCOPE_VIOLATION`，不泄露记录是否存在。
- Entity 保存规范化名称、别名、事实类型、内容哈希和状态版本；创建命令按 `Idempotency-Key` 与 payload hash 幂等，`activate`/`retire` 使用 expected version，并把状态变化写入追加式 `knowledge_events`。
- Claim 保存关联 Entity、事实类型、适用版本/地区/语言、有效起止时间、复核截止时间、替代关系和 freshness；Claim 只有在至少一条 Evidence 为 `valid` 时才能 `verify`，withdraw 和 freshness 变化均带原因/版本校验。
- Evidence 必须引用同租户 SourceSnapshot，可选引用 RightsRecordVersion；引用关系写入 `entity_claims`/`claim_evidences`，状态从 captured 到 valid 前必须通过可用来源、定位器和已验证权利检查。
- 关系、命令和事件表使用不可变触发器；实体/事实身份字段不可改写，内容哈希和 payload 与契约同步，时间窗口拒绝倒置或复核晚于失效时间。
- `apps/api/main.py` 提供 `/v1` 与 `/internal` 的 Entity、Claim、Evidence 创建、查询、状态转换和 Claim-Evidence 关联入口，统一注入 TenantContext、actor、trace 和幂等键。

## 补充场景

- 同一租户重复提交完全相同的创建/转换命令返回原响应和原事件；复用幂等键但改变 payload 返回 `IDEMPOTENCY_KEY_REUSED`。
- 未经验证的 Claim 无法进入 verified；不可用、过期、撤回或阻断的来源不能产生有效 Evidence，缺少 locator 的 Evidence 不能验证。
- 版本、地区、语言、有效时间和复核截止字段在 Claim/Evidence 中持久化并通过 JSON Schema 与服务层双重校验；`list_*` 查询只返回当前租户关系事实。
- SQLite 文件重启后实体、事实、证据、关系、命令和事件仍可读取；底层关系/审计记录 UPDATE/DELETE 由触发器拒绝，状态投影只允许受控版本推进。
## 目录边界

拥有目录：

- `modules/knowledge`

允许目录：

- `modules/knowledge`
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

- `执行 KNOW-001 的公开用例或内部命令`

Then：

- `实现 Entity、Claim、Evidence、适用版本/地区/时间和事实类型。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
py -3.12 -m pytest tests/unit/knowledge tests/integration/test_knowledge_api.py --maxfail=1
py -3.12 scripts/check_json_schemas.py
py -3.12 scripts/check_architecture.py
py -3.12 scripts/check_migrations.py --strict --json
```

Gate：`know_001_acceptance`

## 回滚与运行说明

- 先暂停 Knowledge 写入 Worker，再按 Alembic 逆序回退 `20260918_found_know_001`；回退前导出并保留 `knowledge_events`、关系和命令证据，禁止直接删除业务事实。
- 外部来源或权利状态不确定时保持 Evidence 为 captured、拒绝验证，等待人工补充同租户授权证据；重试必须复用原幂等键。
- API 状态转换必须携带 expected version/`If-Match`；发生冲突时停止写入并重新读取当前快照，不覆盖并发修改。

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。

## Implementation Evidence

- `modules/knowledge/service.py`：Entity、Claim、Evidence 创建/查询、幂等命令、状态转换、适用范围与新鲜度校验、事件信封和租户隔离。
- `modules/knowledge/infrastructure/knowledge_schema.py` 与 `packages/db/migrations/versions/20260918_know_001.py`：七张租户表、复合外键、索引、不可变身份/追加式关系触发器和可逆迁移。
- `apps/api/main.py`：`/v1` 与 `/internal` Knowledge 路由、TenantContext/actor/trace/幂等头解析和稳定错误映射。
- `tests/unit/knowledge/test_service.py` 与 `tests/integration/test_knowledge_api.py`：生命周期、证据前置条件、幂等、时间范围、租户隔离、API 路由和篡改拒绝。
- `docs/foundation/KNOW-001-EVIDENCE.yaml`：专项门禁、Schema、架构和迁移验证结果。
