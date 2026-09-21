# AGENT-CORE-003 — 实现 `ToolGateway` 和外部输入隔离：网页、评论、附件和代码作为不可信数据，不得注入系统 Prompt。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/agent`  
优先级：`critical` / `P0`

## 目标

实现 `ToolGateway` 和外部输入隔离：网页、评论、附件和代码作为不可信数据，不得注入系统 Prompt。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `AGENT-CORE-002`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `AGENT-CORE-003.implementation`
- `AGENT-CORE-003.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/agent-run.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_agent_core_003.py`

## 实现规格

1. `ToolGateway` 仅接收 web、review、attachment、code 四类外部输入，并限制大小、清理控制字符和保存内容哈希。
2. 外部内容以 `untrusted` evidence channel 返回，系统指令保持独立，调用方不能把 evidence 自动插入 system prompt。
3. 未知来源、空内容和超限内容明确拒绝；本卡不启用网络连接、平台适配器或真实凭据。

## 验收证据

- `modules/agent/tools.py` 实现外部输入隔离、哈希和独立 prompt context。
- 单元测试覆盖来源白名单、空/超限拒绝、控制字符清理和系统指令与不可信证据分离。
- 迁移为无业务表 no-op。
## 目录边界

拥有目录：

- `modules/agent`

允许目录：

- `modules/agent`
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

- `执行 AGENT-CORE-003 的公开用例或内部命令`

Then：

- `实现 `ToolGateway` 和外部输入隔离：网页、评论、附件和代码作为不可信数据，不得注入系统 Prompt。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/agent tests/integration --maxfail=1
```

Gate：`agent_core_003_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
