# FOUND-004A — 建立 Alembic 迁移基线、expand/contract 规则和迁移检查。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/foundation`  
优先级：`critical` / `P0`

## 目标

建立 Alembic 迁移基线、expand/contract 规则和迁移检查。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-003A`
- `FOUND-003D`

## 输入

- `docs/contracts/migration-manifest.yaml`：既有 SQL migration 记录及生命周期规则。
- `packages/db/migrations/versions/*.sql`：已接受的 SQL 基线；本任务不得改写。
- `alembic.ini`、`requirements.txt`：Alembic/SQLAlchemy 运行时基线。

## 输出

- `alembic.ini`、`requirements.txt`：可执行的 Alembic 入口和依赖。
- `packages/db/migrations/env.py`、`packages/db/migrations/script.py.mako`：非秘密 SQLite fixture/迁移模板。
- `packages/db/migrations/versions/20260916_found_004a_migration_baseline.py`：真实 revision，含 `revision/down_revision/upgrade/downgrade`。
- `scripts/check_migrations.py`：迁移图、命名、可逆性、破坏性操作和秘密扫描。
- `docs/foundation/migration-framework-baseline-v1.yaml`、`packages/contracts/jsonschema/migration-baseline.schema.json`：迁移框架基线契约。
- `tests/contract/test_found_004a_migrations.py`：契约、升级/降级和负例测试。
- `docs/foundation/FOUND-004A-EVIDENCE.yaml`：验证和副作用证据。

## 实现规格

在 `packages/db/migrations/versions/` 建立 Alembic 基线、版本命名规范和 CI 检查。迁移必须包含 `revision`、`down_revision`、`upgrade()`、`downgrade()`；采用 expand/contract：先加可空字段/新表，再回填与双写，最后单独任务收紧约束。禁止在同一迁移中删除列、重命名列或破坏性改数据。`scripts/check_migrations.py` 检查线性/分支头、命名、可逆性和无生产密钥。

接口/命令：`python -m alembic upgrade head`、`python scripts/check_migrations.py --strict`。错误码：`MIGRATION_HEAD_INVALID`、`MIGRATION_NOT_REVERSIBLE`、`DESTRUCTIVE_MIGRATION_BLOCKED`。迁移文件不得包含业务逻辑或外部网络调用。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/foundation.schema.json`
- `packages/contracts/jsonschema/migration-baseline.schema.json`

迁移 revision：

- `packages/db/migrations/versions/20260916_found_004a_migration_baseline.py`
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
- `alembic.ini`
- `requirements.txt`
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

- `执行 FOUND-004A 的公开用例或内部命令`

Then：

- `Alembic upgrade head` 创建 migration framework baseline，重复 upgrade 幂等；downgrade base 删除本任务新增基线表。
- `check_migrations.py --strict` 报告单一 head、revision 命名合法、upgrade/downgrade 存在、无秘密和无破坏性 upgrade 操作。
- `既有 SQL migration 文件保持不变，新的 Python revision 遵循 expand_then_contract 规则。`
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- 重复执行 upgrade 不产生新变更，downgrade 后可恢复 fixture。
- 检测到多个 head、非法命名、缺失 upgrade/downgrade 或 destructive SQL 时 CI 失败且不执行迁移。
- 迁移锁超时返回 `MIGRATION_LOCK_TIMEOUT`，可重试但不修改半成品。

回滚：先停止写流量，执行已验证 downgrade；expand/contract 的 contract 步骤只能在独立发布确认后执行。

六类 GWT 必须覆盖：成功、重复执行、非法输入、权限/跨租户、依赖缺失、失败重试与未知结果。

## 验证

```text
python -m pytest tests/contract tests/integration --maxfail=1
```

Gate：`found_004a_acceptance`

## 外部依赖

- 无

## 回滚与运行说明

- 运行 `python -m alembic downgrade base` 回滚本任务新增的框架基线；不得重写或删除既有 `.sql` 基线。
- `DATABASE_URL` 未设置时 Alembic 使用 `sqlite:///:memory:` synthetic fixture；这不代表真实 PostgreSQL 已连接。
- expand/contract 的 contract 收紧、真实 PostgreSQL 驱动和生产迁移锁策略由后续任务在此框架上实现。

## 开工前细化

本卡已完成：真实 revision、迁移检查器、契约测试、临时 SQLite upgrade/downgrade 和负例 lint 均已验证；既有 SQL baseline 未改写。
