# Codex 执行协议

本文件规定 Codex 如何从任务清单实施代码。它不能替代任务卡、JSON Schema、OpenAPI 或迁移；这些文件共同构成一次实现的输入。

执行 `GRAPH-*` 或 `LC-*` 任务时，还必须读取 `AI跨境技术内容自动化工作流开发清单_LangGraph_V3.md`、`docs/adr/ADR-001-langchain-langgraph-architecture.md` 和 `docs/task-registry-langgraph-v3.yaml`。V3 是编排增量层，V2.4 仍是领域、治理和账号后置规则的真源。

## 开工前门禁

只有满足以下条件，任务才能从 `planned` 进入 `in_progress`：

1. `FOUND-000` 的仓库清点报告已更新，且当前工作树没有被覆盖的用户修改。
2. `docs/task-registry.yaml` 中存在该任务的精确 ID，依赖任务全部为 `done`。
3. `docs/tasks/<TASK-ID>.md` 包含“实现规格”、六类 Given-When-Then 场景、验证命令和回滚说明。
4. `contract_refs` 指向实际 JSON Schema/OpenAPI/事件 Schema；Schema 通过 JSON Schema 校验。
5. 按迁移生命周期检查 `migration_refs`：`planned` 只允许引用
   `packages/db/migrations/planned/` 规划路径；`in_progress` 必须已替换为真实
   Alembic revision，并通过 migration lint/upgrade 检查；`done` 还必须有已执行、
   可重放的验证证据。仅创建空占位文件不满足门禁。
6. 任务的 `owned_paths`、`exclusive_paths` 与当前波次没有未排序的冲突。
7. 外部依赖已满足，或任务卡写明 Fake/Simulation 替代路径。真实账号未满足时，任务不能调用真实平台。

可用检查：

```text
python scripts/repo_inventory.py --check
python scripts/check_plan_consistency.py --strict-contracts
python scripts/check_task_card_registry_refs.py
python scripts/check_openapi_contract.py
python scripts/check_task_card_precision.py --task <TASK-ID> --strict
```

## 一次任务的固定执行顺序

```text
读取仓库状态
→ 读取任务卡、依赖输出、ADR 和契约
→ 写/更新 Schema、OpenAPI、迁移和测试
→ 实现 domain 纯规则
→ 实现 application 用例和事务边界
→ 实现 infrastructure/repository/projection
→ 接入 API、Worker 或 Scheduler 入口
→ 写入 Outbox 和审计
→ 运行任务卡验证命令
→ 运行架构/安全/回放检查
→ 更新任务状态和交付证据
```

## LangGraph/LangChain 任务附加门禁

1. Graph State 只允许运行 ID、对象引用、版本、路由、错误和恢复信息；禁止 Token、完整正文、PII 和二进制。
2. Node 只能调用 Application Use Case/Port；不得直接写 ORM/数据库，不得直接调用平台 SDK/HTTP。
3. Router 和 Reducer 必须是无副作用纯函数；合并冲突必须显式失败。
4. LLM/Agent Node 只能产生结构化候选、草稿、报告或 HumanTask，不能直接批准或发布。
5. `interrupt()` 恢复必须使用同一 `run_id/thread_id`，并重新检查版本、Rights、Region、Policy 和 Kill Switch。
6. Checkpoint 只用于工作流恢复；PostgreSQL 业务表、AuditLog 和 Outbox 仍是事实真源。
7. 重放和恢复不得重复产生外部副作用；unknown 外部结果必须进入人工核查。
8. Model、Prompt、Retriever、Tool、Parser 都必须有版本、Schema、trace、成本和失败上限。

## 固定执行消息模板

```text
只完成 TASK-ID：<TASK-ID>。
先读取：docs/tasks/<TASK-ID>.md、docs/task-registry.yaml、相关 ADR、packages/contracts、前置任务输出和当前工作树。
只修改 task card 的 allowed_paths；优先修改 owned_paths；禁止触碰 forbidden_paths。
先更新或确认 JSON Schema、OpenAPI、事件 Schema、迁移和测试，再写业务代码。
所有写入都必须使用 TenantContext、Idempotency-Key、If-Match/expected_version、审计和 Outbox 规则。
没有真实账号时只使用 Fake Provider、Fake Adapter、FakeInbox、FakeGeo 和 synthetic fixture；不得读取、生成或保存真实凭证，不得调用真实平台副作用。
如果依赖、契约、字段、状态转换或验收条件有歧义，停止扩大范围，报告阻塞项。
完成后输出：修改文件、迁移、测试命令和结果、事件/审计证据、回滚方法、未完成项和风险。
```

## 完成判定

任务只有在以下条件全部满足时才可标记 `done`：

- 指定契约、迁移、代码和测试已存在并通过；
- 合法和非法状态转换、重复请求、跨租户访问、权限拒绝、外部依赖缺失、重试或 unknown 场景均有断言；
- 业务事实与 Outbox 在同一事务，消费者可按事件 ID 去重；
- 版本、Policy、Rights、Region 和 Target 快照可从审计记录恢复；
- 没有把 Fake/人工数据标记为真实平台数据；
- 变更说明、Runbook、指标和回滚方式已更新。

## 账号后置时的特别规则

无账号阶段只允许：

```text
manual_export → 私有 ExportPackage
simulation    → FakeOfficialAdapter
```

账号到位后也不能把旧 Intent 直接改成真实发布。必须创建新的 `AccountConnection`、`DistributionTargetVersion`、Policy 快照和 `derived_from_intent_id`，先运行 `draft_only`，回查成功后才可申请受控发布。

## 任务状态和证据

任务状态只允许：

```text
planned → in_progress → done
                    ↘ blocked
```

`blocked` 必须写明缺失依赖、负责人、替代方案和下一次复核时间。每次状态变更附带 `trace_id`、actor、提交/构建指纹和测试输出路径。

迁移状态必须与任务状态同步：

| 任务状态 | `migration_refs` 要求 | 必须证据 |
|---|---|---|
| `planned` | 可以是 `packages/db/migrations/planned/` 下的规划路径，文件可以不存在 | 表结构范围、Owner、expand/contract 计划 |
| `in_progress` | 必须指向真实迁移 revision；不得继续只引用 planned 路径 | revision 文件、迁移 lint、测试数据库执行结果 |
| `done` | 真实 revision 已执行并验证；引用不能回退到 planned 路径 | schema 快照、审计记录、验证和回滚策略证据 |
| `blocked` | 保留当前阶段可复核的路径，并记录阻塞原因 | 缺失依赖、负责人、替代方案和下次复核时间 |

迁移 manifest 是索引和门禁输入，不是 SQL；Codex 不得通过修改 manifest 伪造迁移完成。
