# FOUND-001 — 创建 V2 目录、README、CONTRIBUTING、CODEOWNERS 和分支保护。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/foundation`  
优先级：`critical` / `P0`

## 目标

创建 V2 目录、README、CONTRIBUTING、CODEOWNERS 和分支保护。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`

## 输入

- `docs/repo-inventory.md`：FOUND-000 的仓库分类、已有文件和兼容/禁止覆盖结论。
- `docs/governance/tech-stack-baseline-v1.yaml` 与 ADR-001：模块化单体入口和目录边界。
- `docs/task-registry.yaml`：本任务的 Owner、路径和后续任务依赖。

## 输出

- 根目录 `README.md`、`CONTRIBUTING.md`、`CODEOWNERS`。
- V2 应用、模块、适配器、测试、基础设施和文档目录骨架；每个可扩展模块包含职责 README。
- `docs/foundation/v2-directory-baseline-v1.yaml`：完整目录集合、模块内部布局和禁止路径清单。
- `docs/governance/branch-protection-baseline-v1.yaml`：在非 Git 工作区可审计、可迁移的分支保护基线。
- `docs/foundation/FOUND-001-EVIDENCE.yaml` 与结构/契约测试结果。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/foundation.schema.json`
- `packages/contracts/jsonschema/branch-protection.schema.json`

迁移：

- `packages/db/migrations/versions/20260916_found_001_repository_baseline.sql`
## 目录边界

拥有目录：

- `infra/foundation`
- `README.md`
- `CONTRIBUTING.md`
- `CODEOWNERS`
- `docs/governance/branch-protection-baseline-v1.yaml`

允许目录：

- `infra/foundation`
- `apps`
- `modules`
- `adapters/contract`
- `adapters/fake`
- `adapters/manual`
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
- `README.md`
- `CONTRIBUTING.md`
- `CODEOWNERS`

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

- `GOV-006 和 FOUND-000 已完成`
- `docs/repo-inventory.md` 当前有效，且仓库暂无正式业务运行时代码

When：

- `执行 FOUND-001 的目录、契约和迁移测试`

Then：

- `根 README、CONTRIBUTING、CODEOWNERS 和目录骨架存在，且没有覆盖 FOUND-000 或既有治理/契约文件`
- `branch-protection-baseline-v1.yaml 声明 required checks、CODEOWNERS review、禁止 force-push/deletion，并明确当前非 Git 工作区只记录基线而未声称已远程启用`
- `每个模块 README 都声明职责、公开接口、事件、权限和禁止事项；运行入口仍由 FOUND-002 实现`
- `迁移可重复执行，重复基线版本被唯一约束拒绝`

补充场景：

- Given 已有 `packages/contracts`、`packages/db/migrations` 和治理文件，When 创建 V2 骨架，Then 只新增缺失文件，不覆盖既有文件。
- Given 当前不是 Git worktree，When 生成分支保护基线，Then 报告 `documented_not_enforced`，不伪造远程 branch protection 已生效。
- Given 贡献者提交未关联任务 ID 的变更，When 按 CONTRIBUTING 检查，Then 文档要求拒绝合并并补充任务/证据。
- Given 变更触及 contracts、migrations、apps 或 modules，When CODEOWNERS 匹配，Then 必须请求 foundation 或 governance Owner 审查。
- Given 后续任务需要 API/Worker/Scheduler，When 读取目录 README，Then 只能接入公开契约和 Use Case，不能把运行实现提前写入 FOUND-001。
- Given 重复执行目录初始化或迁移，When 已有同版本基线，Then 文件不覆盖、迁移返回唯一约束失败且历史记录保留。
- Given 任务卡和前置清点有效，When 运行指定命令，Then 根文件、目录 README、契约和证据全部可复现。
- Given 运行者再次提交相同基线，When 命中同一版本，Then 不覆盖现有文件，数据库唯一键拒绝重复版本。
- Given 变更触及禁止目录或没有 Owner 权限，When 通过路径和 CODEOWNERS 检查，Then 门禁失败且不产生新文件。
- Given 本任务不保存租户业务事实，When 检查跨租户访问，Then 明确标记不适用，后续业务任务必须通过 TenantContext。
- Given Git remote、真实账号或外部服务不可用，When 执行 FOUND-001，Then 仅使用本地基线和 synthetic 元数据，不阻塞目录交付。
- Given 检查命令临时失败或重复执行，When 没有外部副作用，Then 可安全重试；任何未知外部结果不得被伪造为已启用分支保护。

## 验证

```text
python -m pytest tests/contract/test_found_001_repository_baseline.py -q
```

Gate：`found_001_acceptance`

## 回滚与运行说明

- 目录骨架和协作文件只做新增；如需撤销，使用受审查的反向提交，不覆盖 FOUND-000 报告、既有 ADR、契约或迁移。
- 分支保护基线在非 Git 工作区只记录为 `documented_not_enforced`；远程仓库创建后由管理员按同一版本应用，并保留平台侧审计记录。
- 迁移失败时停止后续任务，保留已创建元数据表和历史记录，通过新版本修复，不执行破坏性删除。

## 外部依赖

- 无

## 实现规格

1. 依据主清单 3.3 的模块化单体目录创建缺失目录和职责 README；不创建 `adapters/platforms`、生产 secrets 或任何运行时业务代码。
2. 根 README 说明当前是 planning-and-contract-baseline，列出入口、机器真源、任务顺序和无账号阶段的 synthetic/manual_export/simulation 边界。
3. CONTRIBUTING 固定单任务、任务卡门禁、契约/迁移/测试命令、审查和回滚要求；CODEOWNERS 覆盖 contracts、migrations、apps、modules、adapters 和治理文件。
4. 创建 `branch-protection-baseline-v1.yaml`，将 Git provider 无关的 PR 审查、required checks、CODEOWNERS review、禁止 force-push/deletion和非 Git 的未启用状态机器化。
5. 创建 `repository_branch_protection_baselines` 版本表；只保存基线元数据和哈希，不保存凭证、账号或平台配置。
6. 新增结构化测试，验证文件集合、内容关键规则、YAML 字段和 SQLite 迁移幂等性。

## 实施证据

- 已创建根目录 `README.md`、`CONTRIBUTING.md`、`CODEOWNERS`，以及应用、模块、适配器、测试、基础设施、部署模板和文档边界。
- 已创建 `docs/foundation/v2-directory-baseline-v1.yaml`，并为 19 个逻辑模块补齐 `domain/application/ports/infrastructure/projections` 固定层。
- 已创建机器可读的 `branch-protection-baseline-v1.yaml` 与 `branch-protection.schema.json`；当前非 Git worktree 明确记录为 `documented_not_enforced`。
- 已创建版本化迁移 `packages/db/migrations/versions/20260916_found_001_repository_baseline.sql`，合同测试验证可重复执行和版本唯一性。
- 已完成 `tests/contract/test_found_001_repository_baseline.py`（6 passed）和全量测试；完整证据见 `docs/foundation/FOUND-001-EVIDENCE.yaml`。

## 开工前细化

本卡已完成从 `planned` 到 `in_progress` 再到 `done` 的状态闭环；后续运行入口任务必须复用本目录和 CODEOWNERS 边界。
