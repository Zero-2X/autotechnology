# FOUND-012A — 在 CI 实现 lockfile 校验、格式、类型、单元测试、secret scanning、SAST 和依赖/CVE 扫描；CI 不得读取生产凭证。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/foundation`  
优先级：`critical` / `P0`

## 目标

在 CI 实现 lockfile 校验、格式、类型、单元测试、secret scanning、SAST 和依赖/CVE 扫描；CI 不得读取生产凭证。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-001`
- `FOUND-011`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `FOUND-012A.implementation`
- `FOUND-012A.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/foundation.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_found_012a_ci.py`
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

- `执行 FOUND-012A 的公开用例或内部命令`

Then：

- `在 CI 实现 lockfile 校验、格式、类型、单元测试、secret scanning、SAST 和依赖/CVE 扫描；CI 不得读取生产凭证。`
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- Given Python 和前端依赖清单，When CI 启动，Then 先验证 `requirements.lock`、`ci/tooling.lock` 和两个 pnpm v9 lockfile；任一依赖未精确锁定或 importer 缺失则失败。
- Given Python 代码，When CI 运行质量门禁，Then 对 CI-owned 检查器执行 Ruff 格式、Ruff lint、mypy 和 Bandit SAST，并运行全量契约门禁与测试。
- Given 仓库源文件，When CI 运行秘密扫描，Then 本地保守扫描和 Gitleaks 均执行；发现私钥、已知 Token 形状或高熵凭证即失败。
- Given 依赖锁文件，When CI 执行 CVE 审计，Then `pip-audit --no-deps -r requirements.lock` 失败即阻断；审计不读取生产环境变量或仓库 Secret。
- Given Pull Request，When 工作流运行，Then 只授予 `contents: read`，触发器使用 `pull_request`，不得使用 `pull_request_target` 或 `secrets.*`。

## 实现规格

1. `requirements.lock` 锁定运行/测试直接依赖，`ci/tooling.lock` 锁定 Ruff 0.15.17、mypy 2.0.0、Bandit 1.9.4 与 pip-audit 2.10.1；更新必须伴随兼容、漏洞和回滚证据。
2. `.github/workflows/ci.yml` 分为 Python 与前端两个 Job，使用 Python 3.12、Node 22 和 pnpm 10.15.1；工作流只使用读取权限，环境中不注入生产凭证。
3. 本地 `check_lockfiles.py`、`check_secrets.py` 与 `check_ci_configuration.py` 可离线验证配置；Gitleaks 负责完整 Git 历史/工作树秘密扫描，Bandit 与 pip-audit 负责外部工具扫描。
4. CI-owned 工具配置集中在 `pyproject.toml`；前端使用 `--frozen-lockfile` 安装并构建两个站点。
5. 本任务不新增业务表；Alembic revision 是可回退 no-op 标记，防止把 CI 状态写入业务数据库。

## 回滚

停用 CI workflow 后仍可运行本地基础门禁；回退 lockfile 或工具版本必须恢复上一份经过审计的版本。Alembic 可降级到 `20260918_found_011`，不影响任何业务数据。

## 验证

```text
python -m pytest tests/contract tests/integration --maxfail=1
```

Gate：`found_012a_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
