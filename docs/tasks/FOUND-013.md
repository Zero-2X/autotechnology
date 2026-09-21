# FOUND-013 — 在 `FOUND-000` 清点结果基础上维护并校验已提交的 `docs/task-registry.yaml`：为每个任务登记唯一 ID、阶段、Owner、优先级、层级、精确依赖、允许/禁止目录、`owned_paths`/`shared_paths`/`exclusive_paths`、契约、测试命令、出口 Gate、外部依赖和状态；CI 检查 ID、依赖、环、路径冲突和文档对齐。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/foundation`  
优先级：`critical` / `P0`

## 目标

在 `FOUND-000` 清点结果基础上维护并校验已提交的 `docs/task-registry.yaml`：为每个任务登记唯一 ID、阶段、Owner、优先级、层级、精确依赖、允许/禁止目录、`owned_paths`/`shared_paths`/`exclusive_paths`、契约、测试命令、出口 Gate、外部依赖和状态；CI 检查 ID、依赖、环、路径冲突和文档对齐。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-001`
- `FOUND-007D`
- `FOUND-012A`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `FOUND-013.implementation`
- `FOUND-013.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/foundation.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_found_013_registry.py`
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

- `执行 FOUND-013 的公开用例或内部命令`

Then：

- `在 `FOUND-000` 清点结果基础上维护并校验已提交的 `docs/task-registry.yaml`：为每个任务登记唯一 ID、阶段、Owner、优先级、层级、精确依赖、允许/禁止目录、`owned_paths`/`shared_paths`/`exclusive_paths`、契约、测试命令、出口 Gate、外部依赖和状态；CI 检查 ID、依赖、环、路径冲突和文档对齐。`
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- Given 已提交清单和机器注册表，When 运行 `check_plan_consistency.py --strict-contracts`，Then 157 个任务的 ID、阶段、标题、source_line 和状态与清单逐项对齐。
- Given 任务依赖，When 出现未知 ID、自依赖、环或不允许的未来层级依赖，Then 检查失败并输出任务与依赖路径。
- Given 同阶段的 exclusive_paths，When 两个任务路径重叠且不存在传递依赖，Then 检查失败；有明确依赖顺序时允许共享推进。
- Given 已完成任务，When 契约、迁移或任务卡引用缺失，Then `--strict-contracts` 失败；planned 任务的计划路径可保留为警告。
- Given CI 工作流，When 运行基础门禁，Then 任务注册表检查与 JSON/OpenAPI/事件/迁移/架构检查一起执行。

## 实现规格

1. 继续使用 `scripts/check_plan_consistency.py` 作为唯一注册表门禁，覆盖 Markdown/Registry 对齐、唯一 ID、字段完整性、依赖存在性与环、层级顺序、路径边界/冲突、契约引用、事件登记和可选命令检查。
2. 将 `--strict-contracts` 加入本地 `check_foundation_contracts.py` 和 GitHub Actions；对 planned 缺失路径只报告警告，对 in_progress/done 缺失引用报错。
3. 新增 FOUND-013 负例测试，直接验证循环依赖与路径重叠判定；现有提交注册表必须通过严格门禁。
4. 本任务不创建业务数据库状态；Alembic revision 仅作为审计顺序标记。

## 回滚

恢复上一版 CI 门禁并保留现有注册表快照、错误报告和审计证据；Alembic 可降级到 `20260918_found_012a`，不修改任务业务数据。

## 验证

```text
python scripts/check_plan_consistency.py
```

Gate：`found_013_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
