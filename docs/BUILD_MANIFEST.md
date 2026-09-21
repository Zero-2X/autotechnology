# 项目构建总安排

## 当前资料的唯一用途

| 文件 | 用途 | 是否可直接作为 Codex 输入 |
|---|---|---|
| `AI跨境技术内容自动化工作流开发清单_审计与优化版.md` | V2.4 领域、治理、安全、账号后置和业务任务基线 | 是 |
| `AI跨境技术内容自动化工作流开发清单_LangGraph_V3.md` | LangGraph/LangChain 编排层增量基线 | 是 |
| `docs/task-registry.yaml` | V2.4 业务任务机器注册表，157 个任务 | 是 |
| `docs/task-registry-langgraph-v3.yaml` | V3 编排任务机器注册表，38 个任务 | 是 |
| `docs/tasks/*.md` | 每个任务的实现规格和验收场景 | 是 |
| `packages/contracts/` | JSON Schema、事件、OpenAPI 和迁移索引 | 是 |
| `docs/CODEX_EXECUTION_PROTOCOL.md` | 单任务执行和安全门禁 | 是 |
| `docs/adr/ADR-001-langchain-langgraph-architecture.md` | LangGraph 架构边界 | 是 |
| `docs/audits/` | 只读审计证据和历史判断 | 仅作参考 |

## 严格构建顺序

### 阶段 A：仓库和治理

1. `FOUND-000`：更新仓库清点。
2. `GOV-001` 至 `GOV-010`：冻结垂直领域、范围、RACI、风险、Policy、指标和 Go/No-Go。
3. `FOUND-001` 至 `FOUND-013`：模块化单体、契约、数据库、Outbox、任务租约、审计和观测底座。
4. `GRAPH-GOV-001` 至 `GRAPH-GOV-005`：登记 ADR，冻结 Graph 边界、版本和 Codex 门禁。

### 阶段 B：LangGraph 运行时

5. `GRAPH-CORE-001` 至 `GRAPH-CORE-006`：GraphRegistry、GraphRunner、TaskJob 映射、错误、暂停和 Checkpointer。
6. `GRAPH-STATE-001` 至 `GRAPH-STATE-005`：State Schema、引用、Reducer、迁移和敏感字段 lint。
7. `LC-MODEL-001`、`LC-MODEL-002`、`LC-PROMPT-001`、`LC-PARSER-001`、`LC-TOOL-001`。
8. `LC-RETRIEVER-001`：知识检索完成后再执行；如果 M1-Core 暂不做检索，可延至 M1-Plus。

### 阶段 C：无账号业务纵向切片（M1-Core）

9. 按 V2.4 依赖完成 Topic、Provenance、Rights、Knowledge、Canonical、Production、QA、Policy、Approval、Distribution P0 任务。
10. `GRAPH-NODE-001` 至 `GRAPH-NODE-004`：连接领域 Use Case，构成第一条内容图。
11. `GRAPH-ROUTER-001`、`GRAPH-HUMAN-001`、`GRAPH-REPLAY-001`：路由、人工中断、恢复和重放。
12. 只验证 `manual_export` 和 `simulation`；不得调用真实平台。

### 阶段 D：反馈和评测

13. `GRAPH-OBS-001`、`GRAPH-OBS-002`。
14. `GRAPH-EVAL-001`、`GRAPH-EVAL-002`。
15. `GRAPH-FEEDBACK-001` 与 V2.4 的 `FEEDBACK-CORE-*`。

### 阶段 E：账号和平台（M2）

16. 只有 M1-Core Go/No-Go 通过后，执行 `GRAPH-DIST-001` 至 `GRAPH-DIST-004`。
17. 首个平台先 `draft_only`，再做低频受控发布。

## 每次只运行一个任务

Codex 每次只接受一个精确 ID。任务状态只能按下列路径变化：

```text
planned → in_progress → done
                    ↘ blocked
```

进入 `in_progress` 前必须通过：

```text
python scripts/repo_inventory.py --check
python scripts/check_plan_consistency.py --strict-contracts
python scripts/check_task_card_registry_refs.py
python scripts/check_langgraph_task_registry.py   # GRAPH/LC 任务
python scripts/check_task_card_precision.py --task <TASK-ID> --strict
python scripts/check_openapi_contract.py
```

## M1-Core 完成定义

必须完成并留存证据：

- `TopicSignal→TopicBrief→Source/Rights→KnowledgeCore→CanonicalContent`。
- `CanonicalContent→zh-CN/en-US Variant→QA→Policy→Approval`。
- `Approval→Manual Export` 和 `Approval→Simulation/Fake Adapter`。
- checkpoint 恢复、interrupt/resume、重复消费、429、unknown 外部结果和跨租户拒绝测试。
- 业务事实、AuditLog 和 Outbox 的事务证据。
- 一份可按 `trace_id` 查询的完整运行报告。

## 禁止事项

- 没有账号时读取、生成、保存真实 Token 或调用真实平台。
- Node 直接写数据库、直接使用 ORM 或直接调用平台 SDK。
- 将完整正文、PII、Token 或媒体二进制塞进 Graph State。
- 使用 checkpoint 代替业务事实、审批或审计。
- unknown 外部结果自动重发。
- 为了 LangGraph 提前引入 Kubernetes、Kafka、Temporal 或微服务拆分。

