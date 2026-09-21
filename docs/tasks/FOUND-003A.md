# FOUND-003A — 配置 PostgreSQL、本地健康检查和最小连接 fixture。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/foundation`  
优先级：`critical` / `P0`

## 目标

配置 PostgreSQL、本地健康检查和最小连接 fixture。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-002`

## 输入

- `docs/foundation/runtime-entry-baseline-v1.yaml`：FOUND-002 的 API readiness 入口。
- `docs/governance/tech-stack-baseline-v1.yaml`：PostgreSQL 事实源与 P0 技术约束。
- `DATABASE_URL`：可选运行时环境变量；CI 和无数据库本地环境允许缺失。

## 输出

- `infra/foundation/database.py`：配置解析、脱敏健康快照和 synthetic connection fixture。
- `docs/foundation/postgresql-foundation-baseline-v1.yaml`：无秘密配置基线。
- `packages/contracts/jsonschema/database-config.schema.json`：配置基线契约。
- `docs/foundation/FOUND-003A-EVIDENCE.yaml`：验证和副作用证据。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/foundation.schema.json`
- `packages/contracts/jsonschema/database-config.schema.json`
- `packages/contracts/openapi/openapi.yaml`：`/health/ready` 的 PostgreSQL 配置状态。

迁移：

- `packages/db/migrations/versions/20260916_found_003a_database_baseline.sql`
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

- `GOV-006、FOUND-000 和 FOUND-002 已完成`
- `CI 无 PostgreSQL 驱动、真实数据库或真实凭证`

When：

- `执行 FOUND-003A 的配置、健康快照、fixture、契约和迁移测试`

Then：

- `DATABASE_URL 缺失、合法或非法时均返回确定性且不泄漏密码的配置结果`
- `/health/ready 未配置时返回 not_configured，配置但未注入驱动时返回 configured/not_attempted`
- `synthetic connection fixture 可执行内存 SQLite 测试事务、不打开网络，迁移可重复执行且版本唯一`

补充场景：

- Given 未设置 `DATABASE_URL`，When 请求 readiness，Then 返回 `not_configured`，不尝试网络连接。
- Given URL 含密码，When 生成健康快照，Then 输出仅含脱敏 URL 和 `sha256` 配置哈希。
- Given URL scheme、host、database 或 timeout 非法，When 解析配置，Then 确定性拒绝且错误信息不包含密码。
- Given synthetic fixture，When 执行内存 SQLite 建表、写入与查询，Then 事务结果可复现且不打开网络。
- Given 基线迁移已执行，When 重复执行，Then 不新增表；重复插入同一版本被唯一键拒绝。

## 验证

```text
python -m pytest tests/contract tests/integration --maxfail=1
```

Gate：`found_003a_acceptance`

## 外部依赖

- 无

## 实现规格

1. `infra/foundation/database.py` 只使用 Python 标准库解析 `DATABASE_URL`，校验 PostgreSQL scheme/host/database/port，并以脱敏 URL、配置哈希和非秘密字段输出配置快照。
2. `/health/ready` 复用配置快照：未配置返回 `not_configured`；已配置但未注入驱动时返回 `configured` 与 `probe=not_attempted`；实际探测只能由后续任务通过注入 probe 完成。
3. `create_connection_fixture()` 返回 `foundation_fixture` 的内存 SQLite DB-API connection seam，可执行本地测试 SQL，不打开网络、不读取凭证、不冒充真实 PostgreSQL 可用性；pytest 入口位于 `tests/integration/conftest.py`。
4. `postgresql-foundation-baseline-v1.yaml`、`database-config.schema.json` 和版本化迁移只记录非秘密配置基线；迁移使用 `(baseline_key, baseline_version)` 唯一键并可重复执行。
5. dev 配置模板和本地 compose 文件只提供无凭证的 PostgreSQL 16 启动形状；staging 只声明由运行时 secret manager 注入 URL。
6. 测试覆盖缺失配置、合法/非法 URL、密码脱敏、健康快照、synthetic fixture 和迁移幂等性。

## 实施证据

- 配置基线：`docs/foundation/postgresql-foundation-baseline-v1.yaml`。
- 配置契约：`packages/contracts/jsonschema/database-config.schema.json`，并纳入 foundation contract union。
- 连接边界：`infra/foundation/database.py` 与 `tests/integration/conftest.py`，使用内存 SQLite fixture，无 PostgreSQL 驱动、网络探测或真实凭证副作用。
- 本地模板：`deploy/environments/dev/database.env.example`、`deploy/environments/staging/database.env.example`、`infra/compose/postgresql.dev.yaml`。
- 迁移：`packages/db/migrations/versions/20260916_found_003a_database_baseline.sql`。
- 专项测试：`python -m pytest tests/contract/test_found_003a_database.py -q`（`7 passed`）；integration fixture：`python -m pytest tests/integration/test_found_003a_connection_fixture.py -q`（`1 passed`）；全量测试：`44 passed`。

## 回滚与运行说明

- 仅新增配置、fixture、基线和迁移；回滚使用受审查的反向变更，不删除 FOUND-002 入口或重写已接受迁移。
- 未提供 `DATABASE_URL` 时保持 `not_configured`；提供 URL 但未装配驱动时只报告 `configured/not_attempted`，不伪造 ready。
- 具体 PostgreSQL 驱动、连接池、真实探测和业务表由后续持久化任务实现。

## 开工前细化

本卡已完成从 `planned` 到 `in_progress` 再到 `done` 的状态闭环；队列表、ORM 和真实连接池继续由后续任务实现。
