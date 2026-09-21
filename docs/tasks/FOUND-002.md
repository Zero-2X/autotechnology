# FOUND-002 — 创建 API、Worker、Scheduler 三个后端运行入口，以及 Web Console/Knowledge Site 前端构建入口。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/foundation`  
优先级：`critical` / `P0`

## 目标

创建 API、Worker、Scheduler 三个后端运行入口，以及 Web Console/Knowledge Site 前端构建入口。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-001`

## 输入

- `docs/foundation/v2-directory-baseline-v1.yaml`：入口目录和模块边界。
- `docs/governance/tech-stack-baseline-v1.yaml` 与 ADR-001：FastAPI、Python worker、scheduler 和前端构建职责。
- `packages/contracts/openapi/openapi.yaml`：现有 HTTP 契约；本任务不得新增业务 CRUD。

## 输出

- `apps/api/main.py`：FastAPI composition root 与 liveness/readiness 健康检查。
- `apps/worker/main.py`：可 dry-run/once 的 Worker composition root，不连接数据库。
- `apps/scheduler/main.py`：可 dry-run/once 的 Scheduler composition root，不复制领域规则。
- `apps/web-console/`、`apps/knowledge-site/`：无依赖静态构建入口和 package script。
- `docs/foundation/runtime-entry-baseline-v1.yaml` 与 `docs/foundation/FOUND-002-EVIDENCE.yaml`。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/foundation.schema.json`
- `packages/contracts/jsonschema/runtime-entry.schema.json`
- `packages/contracts/openapi/openapi.yaml`：FOUND-002 健康检查路径。

迁移：

- `packages/db/migrations/versions/20260916_found_002_runtime_entry_baseline.sql`
## 目录边界

拥有目录：

- `infra/foundation`
- `apps/api`
- `apps/worker`
- `apps/scheduler`
- `apps/web-console`
- `apps/knowledge-site`

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

- `GOV-006、FOUND-000 和 FOUND-001 已完成`
- `FastAPI/Node 入口可在本地运行，真实数据库和账号不可用也不阻塞本任务`

When：

- `执行 FOUND-002 的入口、构建、契约和迁移测试`

Then：

- `API 暴露 liveness/readiness，且不暴露未登记的业务 CRUD；Worker/Scheduler 支持 --once --dry-run 并返回确定性结果`
- `两个前端入口可用同一无依赖 build script 输出静态构建产物；不访问数据库或真实平台`
- `runtime-entry-baseline-v1.yaml 与 Schema 登记入口、职责、命令和禁止边界`
- `迁移可重复执行，重复 baseline version 被唯一约束拒绝`

补充场景：

- Given API 进程启动，When 请求 GET /health/live，Then 返回 200、service=api 和 runtime=modular-monolith。
- Given API 尚未装配数据库，When 请求 GET /health/ready，Then 返回可解释的 not_configured 状态，不伪造数据库 ready。
- Given Worker 无数据库、队列或账号，When 执行 --once --dry-run，Then 返回 no_jobs 且退出码为 0，不读取凭证。
- Given Scheduler 无数据库或外部时钟服务，When 执行 --once --dry-run，Then 返回 no_due_jobs 且退出码为 0。
- Given 前端构建入口，When 在临时输出目录运行 build，Then 生成 index.html 和 manifest.json，且不写入业务源目录。
- Given 入口收到未知参数或迁移重复执行，When 执行命令，Then 确定性失败并保留已有文件/基线，不产生外部副作用。

## 验证

```text
python -m pytest tests/contract/test_found_002_runtime_entries.py -q
pnpm --dir apps/web-console build -- --out-dir <temp-dir>
pnpm --dir apps/knowledge-site build -- --out-dir <temp-dir>
```

Gate：`found_002_acceptance`

## 外部依赖

- 无

## 实现规格

1. API 只负责 FastAPI app 创建、健康检查和依赖装配占位；业务 HTTP 操作继续由既有 OpenAPI 和后续领域任务提供。
2. Worker/Scheduler 只实现可注入的 dry-run loop seam；不得直接导入 ORM、LangGraph、平台 SDK 或复制领域判断。
3. Web Console/Knowledge Site 使用零运行时依赖的静态入口和可指定输出目录的 Node build script。
4. 创建 runtime-entry baseline/schema，明确每个入口的路径、命令、健康语义、拥有者和禁止依赖。
5. 创建版本化 runtime baseline 元数据迁移，保存入口清单哈希和配置状态，不保存正文、Token、账号或业务事实。
6. 测试覆盖入口成功、未配置依赖、dry-run、构建产物、未知参数和迁移幂等性。

## 回滚与运行说明

- 入口是新增文件；回滚采用受审查的反向提交，不删除 FOUND-001 目录或覆盖已有契约。
- 数据库/队列尚未配置时保持 dry-run 和 not_configured，不把模拟结果标为真实运行指标。
- 迁移失败时停止后续任务，保留元数据表并通过新版本修复，不执行破坏性删除。

## 实施证据

- 已创建 FastAPI API composition root，并提供 `/health/live` 与诚实报告 `not_configured` 的 `/health/ready`。
- 已创建 Worker/Scheduler 命令入口；队列和调度持久化落地前只允许 `--once --dry-run`，非 dry-run 确定性拒绝。
- 已创建 Web Console/Knowledge Site 的无依赖静态构建脚本，并在临时目录验证 `index.html` 与 `manifest.json`。
- 已创建 `runtime-entry-baseline-v1.yaml`、`runtime-entry.schema.json` 和版本化迁移。
- 专项测试 `tests/contract/test_found_002_runtime_entries.py` 结果 `8 passed`；全量测试结果 `36 passed`。完整证据见 `docs/foundation/FOUND-002-EVIDENCE.yaml`。

## 开工前细化

本卡已完成从 `planned` 到 `in_progress` 再到 `done` 的状态闭环；数据库、任务队列和业务路由继续由其后续任务实现。
