# FOUND-007C — 创建 Agent 输出 Schema、拒绝未知字段和 Schema 版本迁移规则。

状态：`done`
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/foundation`  
优先级：`critical` / `P0`

## 目标

创建 Agent 输出 Schema、拒绝未知字段和 Schema 版本迁移规则。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-001`
- `FOUND-004A`
- `FOUND-007B`

## 输入

- 已注册的 Draft 2020-12 Schema、固定的 schema ref/version 和不可信 Agent 输出对象。
- 显式注册的相邻版本纯函数迁移；不得从模型输出加载迁移函数。

## 输出

- `infra/foundation/agent_output.py`：离线验证与逐版本迁移。
- `tests/contract/test_found_007c_agent_output.py`：正反例和迁移测试。
- `docs/foundation/FOUND-007C-EVIDENCE.yaml`：验证与能力边界。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/agent-definition.schema.json`
- `packages/contracts/jsonschema/agent-output.schema.json`
- `packages/contracts/jsonschema/foundation.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260916_found_007c_agent_output.py`
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

## 实现规格

1. 基础输出 v1 只表达 draft/report/needs_review；result 包含 summary/artifact_refs，metadata 包含 limitations，issues 为字符串数组；所有对象拒绝未知字段，数组验证元素类型。
2. 本任务只实现共享契约验证边界，不实现各角色业务输出、AgentRunner、模型调用、持久化或授权；artifact_refs 不意味着资源读取权限，租户权限由后续调用用例验证。
3. 使用标准 jsonschema Draft202012Validator 和 FormatChecker，显式空引用注册表禁止远程加载；返回深拷贝，不修改调用者数据；错误消息不回显模型内容。
4. Schema 按 ref/version 注册，版本必须与 schema_version 的必填整数 const 一致；同键禁止覆盖。旧文件必须保留，新版本使用新文件；本任务发布 v1，测试中的 v2 仅为 synthetic fixture。
5. 迁移只允许显式注册相邻前向纯函数。先验证源对象并检查完整路径，再逐步执行和验证目标；拒绝降级、缺失路径和无效目标。无自动版本推断或重试。
6. 不新增业务表；Alembic revision 仅连续检查点，不宣称已迁移持久化 AgentRun。

## 权限、幂等、失败和审计

- 由 `TenantContext` 注入 `org_id` 和 actor；跨租户访问必须拒绝。
- 写命令使用 `Idempotency-Key` 和 payload hash；状态修改使用 `If-Match` 或 expected version。
- 确定性校验失败不重试；临时失败按任务卡与策略退避；未知外部结果转人工核查。
- 记录 `trace_id`、actor、输入/输出版本、Policy 快照、拒绝原因、耗时和成本。

## Given–When–Then

Given：

- `固定的 v1 Schema 与 synthetic 输出`
- `测试专用 v2 Schema 和可信迁移函数`

When：

- `调用 AgentOutputRegistry.validate/register_migration/migrate`

Then：

- `合法输出返回独立深拷贝；顶层与嵌套未知字段、非法状态、错误类型和未知版本被拒绝。`
- `迁移前后均验证，缺失路径、降级、重注册和版本不匹配均被拒绝；原输出与旧 Schema 不改变。`

## 验证

```text
python -m pytest tests/contract/test_found_007c_agent_output.py -q
python scripts/check_task_card_precision.py --task FOUND-007C --strict
python scripts/check_task_card_registry_refs.py
python scripts/check_migrations.py --strict --json
python -m pytest tests --maxfail=1 -q
```

Gate：`found_007c_acceptance`

## 外部依赖

- 无

## 开工前细化

已细化为基础报告/草稿输出契约与离线验证器。运行时调用链及各 Agent 业务结果由 AGENT-CORE 系列接入；不将本任务的独立验证器等同于端到端 Agent 执行。
