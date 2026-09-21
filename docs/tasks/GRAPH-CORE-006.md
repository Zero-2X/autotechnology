# GRAPH-CORE-006：实现 Checkpointer Port 及 SQLite/PostgreSQL 实现

- **状态**：planned
- **阶段**：1 — LangGraph Runtime 与任务接入
- **层级**：P0
- **依赖**：GRAPH-CORE-002
- **主目录**：`orchestration, integrations/langchain, packages/contracts, packages/observability, tests, docs/graphs, docs/runbooks`
- **禁止目录**：`secrets, deploy/environments/prod/secrets, **/*.pem, **/*token*.json`

## 目标

实现 Checkpointer Port 及 SQLite/PostgreSQL 实现。本任务只处理该目标，不跨任务重构。

## 输入

- 前置任务输出：GRAPH-CORE-002
- `TenantContext(org_id, actor_id)`
- `trace_id`、`Idempotency-Key`
- V2.4 领域契约、V3 ADR-001、Graph State/事件 Schema

## 实现规格

1. 先补齐或确认 JSON Schema、事件 Schema、迁移和公开 Port。
2. 实现可测试的 domain/application 规则，再写 LangGraph Node/Router/Runner 适配。
3. 为成功、校验失败、权限拒绝、重复请求、瞬时故障和 unknown/human_required 保留结构化结果。
4. 写入业务事实、AuditLog 和 Outbox 必须处在同一事务；Graph checkpoint 仅用于恢复。
5. 所有模型调用记录 `model.call.started/succeeded/failed`，不得把 Prompt 中的敏感数据写入日志。

- Node 只能调用领域 Application Use Case/Port，不得直接写 ORM、数据库或平台 SDK。
- 所有写命令必须携带 org_id、trace_id、Idempotency-Key，并使用 expected_version/If-Match。
- Graph State 只保存引用、版本和恢复信息；禁止 Token、完整正文、PII 和二进制。
- 没有真实账号时仅允许 manual_export、simulation、Fake Provider/Adapter。

## Given–When–Then 验收场景

### 1. 正常路径

- **Given** 依赖已完成且输入契约有效
- **When** 通过公开 Use Case/GraphRunner 执行 `GRAPH-CORE-006`
- **Then** 产生声明的输出、事件、审计证据，且结果可由 `trace_id` 查询

### 2. 输入与权限

- **Given** 缺字段、错误 org_id 或无权限 actor
- **When** 提交执行
- **Then** 返回结构化拒绝，不写业务事实，不创建副作用

### 3. 幂等与版本

- **Given** 相同 Idempotency-Key 或过期 expected_version
- **When** 重复提交/更新
- **Then** 返回第一次结果或 409；不产生第二个版本、Intent、Outbox 或外部对象

### 4. 故障与重试

- **Given** timeout、429、5xx、解析失败或依赖不可用
- **When** 节点执行
- **Then** 仅可重试的 transient 错误按上限退避；policy/rights/权限/unknown 进入阻断或人工路径

### 5. 恢复与重放

- **Given** checkpoint、interrupt 或 worker 崩溃
- **When** 使用同一 run_id/thread_id 恢复或重放
- **Then** 从安全边界继续；重新检查最新版本/Policy/Kill Switch；不重复产生副作用

### 6. 隔离与审计

- **Given** 跨租户引用、提示注入、越权 Tool 参数或敏感日志
- **When** 执行
- **Then** 请求被拒绝，AuditLog 记录原因，Token/PII 不出现在 State、事件和日志

## 验证命令

```text
python -m pytest tests --maxfail=1
python scripts/check_plan_consistency.py --strict-contracts
python scripts/check_task_card_registry_refs.py
python scripts/check_task_card_precision.py --task GRAPH-CORE-006 --strict
python scripts/check_openapi_contract.py
```

## 交付证据

- 修改文件清单和契约 diff
- 迁移 revision、升级/回滚验证（如有）
- 测试输出、trace_id、AuditLog/Event ID、checkpoint/replay 证据
- Runbook、指标和回滚方式
- 未完成项、风险和后续任务

