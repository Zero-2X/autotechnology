# FOUND-011 — 建立架构依赖检查、禁止跨模块直写检查、`org_id` 隔离测试和首个 smoke 命令。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/foundation`  
优先级：`critical` / `P0`

## 目标

建立架构依赖检查、禁止跨模块直写检查、`org_id` 隔离测试和首个 smoke 命令。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-001`
- `FOUND-010`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `FOUND-011.implementation`
- `FOUND-011.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/foundation.schema.json`
- `packages/contracts/jsonschema/architecture-guard.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_found_011_architecture_guard.py`
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

- `执行 FOUND-011 的公开用例或内部命令`

Then：

- `建立架构依赖检查、禁止跨模块直写检查、`org_id` 隔离测试和首个 smoke 命令。`
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- Given 一个领域模块，When 它导入 `apps`、`adapters`、`infra` 或另一模块内部代码，Then 架构检查失败并定位文件与行号。
- Given 模块内出现常量 SQL 写入，When 目标表属于另一模块或没有所有权登记，Then 检查失败；App 入口中的直接 SQL 写入一律失败。
- Given 同一个 FakeStorage，When `org-b` 读取或删除 `org-a` 的对象，Then 拒绝且 `org-a` 的对象保持不变。
- Given 本地 smoke 命令，When 执行，Then 架构检查、API `/health/live` 和共享存储租户隔离均通过；无需网络或真实账号。

## 实现规格

1. `architecture-guard-v1.yaml` 与 Schema 冻结模块依赖方向、表所有权和 smoke 内容；`scripts/check_architecture.py` 扫描 `modules/` 与 `apps/` 的 Python AST。
2. 静态门禁识别直接导入、常量动态导入和常量 SQL DML；变量拼接/反射代码不能仅靠此检查证明安全，须在后续模块代码审查与集成测试中核对。
3. `scripts/smoke_foundation.py` 使用本地 TestClient 与同一 FakeStorage 实例，验证 API 存活及 `org_id` 读、列举、删除隔离；纳入全量基础门禁。
4. 本任务无持久状态，Alembic revision 为可回退 no-op 标记，迁移清单 `tables_in_scope` 为空。

## 回滚

恢复先前基础门禁配置并移除 FOUND-011 的检查器、smoke 与 Schema；Alembic 可降级到 `20260918_gov_010`。已存在的租户隔离测试与审计证据不得删除。

## 验证

```text
python -m pytest tests/contract tests/integration --maxfail=1
```

Gate：`found_011_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
