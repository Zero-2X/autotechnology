# FOUND-000 — 清点当前仓库、已有代码、依赖、迁移、环境变量、密钥占位、部署脚本和未提交修改，输出 `docs/repo-inventory.md`；若已有实现，只能兼容扩展，不得覆盖。只有确认仓库为空时，才采用本清单的默认技术栈。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/foundation`  
优先级：`critical` / `P0`

## 目标

清点当前仓库、已有代码、依赖、迁移、环境变量、密钥占位、部署脚本和未提交修改，输出 `docs/repo-inventory.md`；若已有实现，只能兼容扩展，不得覆盖。只有确认仓库为空时，才采用本清单的默认技术栈。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`

## 输入

- 当前仓库中非忽略文件的相对路径、大小和非敏感内容哈希。
- Git worktree、分支、HEAD 与未提交路径；非 Git 工作区必须显式标记为不可用。
- 依赖清单、迁移、部署、测试及环境变量引用的文件名和结构元数据。
- 命中 `.env`、私钥或凭证标记的文件只允许读取路径、大小和修改时间，不读取内容。

## 输出

- `docs/repo-inventory.md`：固定栏目、UTC 扫描时间、仓库分类和 `sha256` 源指纹。
- `python scripts/repo_inventory.py --check`：报告缺失、栏目缺失、超过 24 小时或指纹不一致时返回非零。
- `docs/foundation/FOUND-000-EVIDENCE.yaml`：迁移、测试、无真实凭证/平台副作用的验收证据。

## 实现规格

执行 `python scripts/repo_inventory.py --write` 将安全清点结果写入 `docs/repo-inventory.md`，至少包含：扫描时间和源指纹、Git 状态/分支、顶层目录、现有应用与模块、依赖清单、迁移文件、环境变量名（仅名称，不含值）、密钥文件名命中、部署脚本、测试入口、未提交修改、兼容策略和禁止覆盖路径。当前仓库应归类为 `planning-and-contract-baseline`，除非在 `apps/`、`modules/`、`services/` 或 `src/` 下检测到正式运行时代码。`--check` 必须只校验、不改写报告，并在报告不存在、固定栏目缺失、UTC 时间无效或超过 24 小时、源指纹与当前仓库不一致时返回非零。扫描不得读取敏感文件内容；报告和清点脚本/测试/迁移/证据以外不得修改业务源代码。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/foundation.schema.json`

迁移：

- `packages/db/migrations/versions/20260916_found_000_repository_inventory.sql`
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

- `GOV-006 已完成且当前仓库可读`
- `清点输出路径为 docs/repo-inventory.md`

When：

- `执行 python scripts/repo_inventory.py --write 后执行 --check`

Then：

- `报告包含全部固定栏目、合法 UTC 时间、当前源指纹和 planning-and-contract-baseline 分类`
- `报告只列环境变量名称与敏感文件路径分类，不包含秘密值`
- `重复 --check 不写文件且返回 0；仓库或报告失配时返回非零`

补充场景：

- 仓库含未提交修改时，报告必须保留其路径和状态，任务不得清理或覆盖。
- 扫描到 `.env`/凭证文件时只记录相对路径与脱敏类型，不读取内容。
- `--check` 在报告不存在、栏目缺失或报告时间/提交指纹与当前仓库不一致时返回非零。
- 非 Git 工作区必须写明 `not a git worktree`，分支、HEAD 和未提交状态不得伪造。
- 未检测到正式运行时代码时，报告必须声明当前是规划、契约和治理基线，而不是空仓库。
- 检测到既有实现时，报告必须列出兼容扩展策略以及 ADR、契约、版本化迁移、治理基线和用户文件等禁止覆盖路径。


## 回滚与运行说明

- 通过任务级 feature flag 关闭新命令；已提交的业务事实和审计记录不删除。
- 迁移按 expand/contract 顺序执行；验证失败时停止后续任务，保留兼容字段，不执行破坏性回滚。
- 如产生可重试任务，先暂停对应队列，再按原幂等键重放；任何外部未知结果必须转人工核查。

## 验证

```text
python scripts/repo_inventory.py --check
```

Gate：`found_000_acceptance`

## 实施证据

- 已重写 [repo_inventory.py](../../scripts/repo_inventory.py)，支持 `--write` 和只读 `--check`；检查报告栏目、UTC 时间新鲜度、源指纹和敏感内容未读取声明。
- 已生成 [仓库清点报告](../repo-inventory.md)，明确当前分类为 `planning-and-contract-baseline`，并保留非 Git 工作区、已有契约/治理/迁移/测试文件和兼容边界。
- 敏感文件只记录相对路径、脱敏类型和大小；环境变量仅记录名称，不记录值。
- 已创建版本化元数据迁移：`packages/db/migrations/versions/20260916_found_000_repository_inventory.sql`，用于登记不可变的报告指纹和“未读取秘密内容”声明。
- 已完成合同测试：`tests/contract/test_found_000_inventory.py`，覆盖报告栏目、敏感文件隔离、指纹失配、过期报告和迁移幂等性。
- 状态证据：`docs/foundation/FOUND-000-EVIDENCE.yaml`。

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。已完成从 `planned` 到 `in_progress` 再到 `done` 的状态闭环；后续任务必须继续复用本报告中的兼容策略和禁止覆盖路径。
