# AI 跨境技术内容自动化工作流开发清单（LangGraph V3）

**版本**：V3.0  
**日期**：2026-09-15  
**执行关系**：本清单在 V2.4 业务基线之上增加 LangGraph/LangChain 编排层。V2.4 的领域规则、契约、安全边界、账号后置策略继续有效；本文件只负责新增和调整的编排工作。

## 1. 结论：可以采用，但必须限定边界

可以采用。项目有长流程、条件分支、人工审批、失败恢复、版本锁定和反馈闭环，这些正是 LangGraph 的强项；LangChain 适合统一模型、Prompt、Retriever、Tool 和结构化输出。

推荐组合：

```text
FastAPI/API + Worker + Scheduler
              │
              ▼
        LangGraph Runtime
  (State / Node / Router / Interrupt / Checkpoint)
              │
              ▼
      Application Use Cases / Ports
              │
              ▼
Domain Modules + PostgreSQL + Outbox + Audit
              │
              ▼
 Manual/Fake/Platform Adapters
```

LangGraph 不负责版权、Policy、审批、账号授权、Token、数据库事务和最终发布事实。LangChain 不直接拥有业务状态，也不允许 LLM 节点直接调用平台发布接口。

### 账号后置是否科学

科学且可执行。M1 只做 `manual_export` 和 `simulation`，使用 Fake Provider、Fake Adapter、Fake Geo、synthetic fixture；M2 才创建新的 `AccountConnection`、`DistributionTargetVersion`、`PolicySnapshot` 和 `PublicationIntent`。历史 synthetic 版本、审批记录和 Intent 永远不改写。

## 2. 目标目录

```text
apps/
  api/                         # HTTP、鉴权、幂等、输入校验
  worker/                      # 拉取 TaskJob、运行 GraphRun、租约和死信
  scheduler/                   # 只负责创建/唤醒任务，不实现业务图逻辑
modules/                       # 纯领域模块，禁止依赖 LangChain/LangGraph
  governance/ topic/ provenance/ rights/ knowledge/
  canonical_content/ production/ qa/ policy/ approval/
  distribution/ analytics/ feedback/ accounts/
orchestration/
  graphs/                      # 可组合的 StateGraph 定义
    content_pipeline/ research/ localization/
    qa_review/ distribution/ feedback/
  state/                       # TypedDict/Pydantic Graph State
  nodes/                       # 薄适配节点，只调用 Use Case/Port
  routers/                     # 纯函数条件路由
  interrupts/                  # HumanTask 创建、恢复和超时
  reducers/                    # 并行分支合并规则
  checkpointers/               # SQLite(dev)/PostgreSQL(prod)
  graph_registry/              # graph_key、版本、输入输出、兼容策略
integrations/
  langchain/
    models/ prompts/ retrievers/ tools/ parsers/
  adapters/
    fake/ manual/ platforms/
packages/
  contracts/                   # JSON Schema、事件、OpenAPI、Graph State Schema
  db/                          # SQLAlchemy、Alembic、事务和 Outbox
  observability/               # trace、metrics、audit、cost
  testkit/                     # Fake Model、fixtures、replay harness
docs/
  adr/                         # 架构决策
  graphs/                      # 图拓扑、状态和恢复说明
  runbooks/                    # 运维、暂停、重放、事故处理
```

目录规则：Domain 不导入 `langchain_*`、`langgraph`、FastAPI 或 ORM；Node 不直接写数据库；Adapter 是唯一能接触平台 SDK/HTTP 的位置；公共代码放入有 Owner 的 package，禁止无边界 `utils`。

## 3. 固定技术基线

```text
Python 3.12
FastAPI
LangGraph（固定主版本并记录升级窗口）
LangChain Core + 一个供应商集成包
SQLAlchemy 2 + Alembic
PostgreSQL（业务库和生产 Checkpointer）
Redis（P1，可选，用于并发/短期缓存）
S3 兼容对象存储
OpenTelemetry
pytest + contract/e2e/replay 测试
```

首期不引入 LangGraph Server、Temporal、Kafka、Kubernetes、多个模型供应商或多个真实平台。

## 4. Graph 运行契约

### 4.1 Graph State 最小字段

```python
class ContentGraphState(TypedDict, total=False):
    run_id: str
    org_id: str
    workflow_key: str
    workflow_version: str
    input_refs: dict[str, str]
    current_node: str
    artifact_refs: dict[str, str]
    evidence_refs: list[str]
    qa_refs: list[str]
    policy_decision_ref: str
    human_interrupt_ref: str
    retry_context: dict[str, object]
    idempotency_key: str
    trace_id: str
    error_ref: str
```

State 只保存引用和运行上下文。完整正文、Token、PII、媒体二进制和可变业务事实必须放在业务库或对象存储。

### 4.2 Node/Router/副作用规则

- Node 输入输出必须有 JSON Schema；成功返回 artifact reference，失败返回可分类错误。
- Router 只能读取 State 和只读业务结果，不能产生副作用。
- LLM/Agent Node 只能输出候选、草稿、报告或 HumanTask 请求。
- 任何写操作必须经过 Application Use Case，由 Use Case 负责事务、幂等、版本和 Outbox。
- 任何发布副作用必须依次检查 `PolicySnapshot`、审批、Kill Switch、TargetVersion 和 provider 幂等键。
- `interrupt()` 恢复时重新读取版本、Rights、Region、Policy 和 Kill Switch，不信任旧 State。

### 4.3 Checkpoint/重放规则

- 开发可用 SQLite Checkpointer；生产使用 PostgreSQL Checkpointer。
- Checkpoint 只为恢复 GraphRun 服务，不能作为审计真源。
- Graph 重放不得再次产生外部副作用；使用 `PublicationIntent`、`DeliveryAttempt` 和 provider 幂等键隔离。
- unknown 外部结果进入人工核查，禁止自动再次发布。

## 5. 分阶段开发清单

每项任务都必须单独建立 `docs/tasks/<TASK-ID>.md`，并执行：先契约、再迁移、再 domain/application、再 node/入口、再测试和证据。除非任务卡明确允许，不得跨任务重构。

### 阶段 0：架构冻结与迁移准备（P0）

| ID | 依赖 | 必须完成 | 验收标准 |
|---|---|---|---|
| GRAPH-GOV-001 | GOV-001~006 | 写入 ADR-001，冻结 LangGraph 边界、版本策略和不负责清单 | ADR 被引用；V2.4 安全规则无削弱；契约检查通过 |
| GRAPH-GOV-002 | GRAPH-GOV-001 | 选择 LangGraph/LangChain 版本、Python 版本和升级窗口 | `pyproject.toml`、锁文件和升级 Runbook 存在 |
| GRAPH-GOV-003 | GRAPH-GOV-001 | 定义 GraphRun、GraphAttempt、NodeExecution、HumanInterrupt 的业务语义 | 对象 Schema、状态转换和事件 Schema 完整 |
| GRAPH-GOV-004 | GRAPH-GOV-003 | 定义 graph_key、workflow_version、兼容/废弃策略 | 同一 graph_key 的版本不可覆盖；旧运行可恢复 |
| GRAPH-GOV-005 | GRAPH-GOV-001 | 更新 Codex 执行协议，加入 Node/State/Replay 门禁 | 协议包含禁止直接 DB/SDK、State 最小化和副作用规则 |

### 阶段 1：LangGraph Runtime 与任务接入（P0）

| ID | 依赖 | 必须完成 | 验收标准 |
|---|---|---|---|
| GRAPH-CORE-001 | FOUND-001~012, GRAPH-GOV-002 | 建立 `orchestration/` 包和 GraphRegistry | 可按 key+version 注册、查询、拒绝重复版本 |
| GRAPH-CORE-002 | GRAPH-CORE-001 | 实现 GraphRunner：输入校验、trace、租约、超时和结果引用 | Worker 可运行 Fake Graph；重复 job 不重复执行 |
| GRAPH-CORE-003 | GRAPH-CORE-002 | 将 TaskJob 映射为 GraphRun，保留现有状态机 | TaskJob、GraphRun、AuditLog 可互相追踪 |
| GRAPH-CORE-004 | GRAPH-CORE-002 | 统一错误分类：validation、policy、rights、transient、unknown、human_required | 每类错误都有路由、重试上限和事件 |
| GRAPH-CORE-005 | GRAPH-CORE-002 | 实现取消、暂停、Kill Switch 检查 | 暂停后不创建新副作用；审计记录 actor 和原因 |
| GRAPH-CORE-006 | GRAPH-CORE-002 | 实现 SQLite(dev) 和 PostgreSQL(prod) Checkpointer Port | 通过同一契约测试；禁止业务代码直接依赖实现 |

### 阶段 2：Graph State 与契约（P0）

| ID | 依赖 | 必须完成 | 验收标准 |
|---|---|---|---|
| GRAPH-STATE-001 | GRAPH-GOV-003 | 建立通用 `BaseGraphState` 和 `ContentGraphState` Schema | 字段均有类型、来源、敏感级别、生命周期 |
| GRAPH-STATE-002 | GRAPH-STATE-001 | 定义 ArtifactRef、EvidenceRef、PolicyRef、HumanInterruptRef | 只能引用已存在且同 org_id 的对象 |
| GRAPH-STATE-003 | GRAPH-STATE-001 | 定义 State Reducer 和并行分支合并规则 | 冲突显式失败；列表去重稳定；无隐式覆盖 |
| GRAPH-STATE-004 | GRAPH-STATE-001 | 定义 State 迁移和版本兼容策略 | 新旧 State 可迁移；迁移有测试和回滚说明 |
| GRAPH-STATE-005 | GRAPH-STATE-001 | 增加 contract lint：禁止 token/body/blob 进入 State | CI 对字段名、大小和敏感标签有门禁 |

### 阶段 3：LangChain 组件层（P0/P1）

| ID | 依赖 | 必须完成 | 验收标准 |
|---|---|---|---|
| LC-MODEL-001 | MODEL-CORE-001~003, GRAPH-GOV-002 | 实现 ModelPort 与 LangChain ChatModel Adapter | Domain 只见 Port；记录 model.call.* 事件和成本 |
| LC-MODEL-002 | LC-MODEL-001 | 实现 FakeModel、固定响应和故障注入 | CI 不依赖外网；可注入超时、429、格式错误 |
| LC-PROMPT-001 | LC-MODEL-001 | Prompt 模板、版本、变量 Schema 和渲染器 | Prompt 版本写入 GraphRun；缺变量先失败 |
| LC-PARSER-001 | LC-MODEL-001 | 结构化输出解析、Schema 校验和修复上限 | 解析失败不自动无限重试；输出带原始响应引用 |
| LC-RETRIEVER-001 | KNOW-CORE-001 | Retriever Port、权限过滤和证据引用 | 检索结果带 source/evidence/region；跨租户被拒绝 |
| LC-TOOL-001 | GRAPH-CORE-002 | Tool 白名单、参数 Schema、超时和审计 | 工具只能访问授权 Port；提示注入不能改变权限 |

### 阶段 4：无账号内容纵向切片（M1-Core，P0）

| ID | 依赖 | 必须完成 | 验收标准 |
|---|---|---|---|
| GRAPH-NODE-001 | TOPIC-001~004, GRAPH-STATE-001 | TopicSignal→TopicOpportunity→TopicBrief 节点 | 选题锁定版本；缺证据进入人工任务 |
| GRAPH-NODE-002 | PROV/RIGHTS/KNOW/ CANON P0 | Source/Rights/Knowledge/Canonical 节点 | 每个 Claim 有 Evidence；Canonical 版本不可变 |
| GRAPH-NODE-003 | PROD/QA/POLICY P0 | Variant、QA、GEO_CONTENT、GEO_REGION 节点 | zh-CN/en-US 变体独立版本；QA/Policy 结果可追踪 |
| GRAPH-ROUTER-001 | GRAPH-NODE-001~003 | 实现通过/返工/人工/阻断路由 | 路由是纯函数；非法状态无边可走 |
| GRAPH-HUMAN-001 | APPROVAL P0, GRAPH-CORE-005 | Approval interrupt/resume 节点 | 同一 run_id 恢复；重新检查 Policy/版本/Kill Switch |
| GRAPH-NODE-004 | DIST-001~010 | Manual Export 和 FakeOfficialAdapter 节点 | 只允许 manual_export/simulation；重复运行不重复建 fake 对象 |
| GRAPH-REPLAY-001 | GRAPH-NODE-004 | 重放和幂等保护 | 429 可退避；unknown 转人工；无第二个 PublicationIntent |

### 阶段 5：反馈、评测和可观测性（P0/P1）

| ID | 依赖 | 必须完成 | 验收标准 |
|---|---|---|---|
| GRAPH-OBS-001 | GRAPH-CORE-002 | Node/Graph/Model/Outbox 统一 trace 和 metrics | 可按 trace_id 查询完整链路和耗时/成本 |
| GRAPH-OBS-002 | GRAPH-OBS-001 | LangGraph 事件映射到 AuditLog | 节点开始、成功、失败、中断、恢复均可审计 |
| GRAPH-EVAL-001 | LC-MODEL-002, EVAL-001 | Graph golden set、确定性回归和成本预算 | CI 使用 FakeModel；真实模型评测独立运行 |
| GRAPH-EVAL-002 | GRAPH-EVAL-001 | 节点级质量评测和整图 E2E 评测 | 事实、版权、语言、Policy、可访问性指标有阈值 |
| GRAPH-FEEDBACK-001 | FEEDBACK-CORE-001~004 | Observation→Feedback→Recommendation 图 | 建议可解释、可追溯，不自动改写已批准版本 |

### 阶段 6：真实账号与平台（M2，必须 Go/No-Go）

| ID | 依赖 | 必须完成 | 验收标准 |
|---|---|---|---|
| GRAPH-DIST-001 | GRAPH-REPLAY-001, ACCOUNT-CORE | AccountConnection/TargetVersion/PolicySnapshot 新版本链 | 不修改 synthetic 记录；所有连接带授权证据 |
| GRAPH-DIST-002 | OAUTH/Vault P0 | OAuth 回调、Scope、Vault 引用和租约检查 | Graph State 不含 Token；过期/撤销自动阻断 |
| GRAPH-DIST-003 | PLAT-001~002 | 首个平台 draft_only 适配器 | HTTP 仅在 adapter；provider 幂等键和回查完整 |
| GRAPH-DIST-004 | GRAPH-DIST-003 | 受控发布、unknown 核查和停发演练 | 未知结果不重发；Kill Switch 在节点前生效 |

### 阶段 7：规模化（M3）

仅在连续运行、成本、失败率、平台健康和人工负载达到 Go/No-Go 阈值后进行。再评估 Redis、队列拆分、独立分析仓库、更多模型/平台和 Kubernetes；账号数量本身不是拆分理由。

## 6. 第一条必须跑通的 Graph

```text
content_pipeline:v1
START
 → load_topic_signal
 → build_topic_brief
 → verify_sources_rights
 → build_knowledge_core
 → create_canonical_version
 → create_variants(zh-CN,en-US)
 → run_qa
 → run_policy_gate
 ├─ blocked → END
 ├─ human_required → interrupt(Approval)
 └─ passed → create_manual_or_simulation_intent
 → execute_manual_export_or_fake_adapter
 → record_observation
 → create_feedback_item
 → END
```

并行 Variant 合并必须使用显式 reducer；任何一个分支的 Rights/Policy 失败都不能被其他分支覆盖。

## 7. Codex 单任务执行卡（必须复制到每个任务卡）

```text
只完成 TASK-ID：<TASK-ID>。
先读取：V2.4 主清单、V3 清单、docs/tasks/<TASK-ID>.md、task-registry、ADR、相关 Schema 和当前工作树。
只修改 allowed_paths；不得跨任务重构。
先更新/确认 JSON Schema、事件、OpenAPI、迁移和测试，再实现 domain/application，再实现 Node/Router/入口。
Node 不直接写数据库或调用平台 SDK；LLM 只返回结构化候选；副作用必须走 Use Case + Outbox + 幂等键。
没有真实账号时只使用 Fake/Manual/Simulation；不得读取、生成或保存真实 Token。
完成前运行契约、任务卡精细化、OpenAPI、迁移、回放和安全检查。
输出：修改文件、迁移、测试、trace/audit/outbox 证据、回滚、未完成项和风险。
```

## 8. 全局验收场景

1. **恢复**：Graph 在 QA 后中断，人工批准后用同一 `thread_id/run_id` 恢复，且重新读取最新 Policy 和版本。
2. **重放**：同一 GraphRun 重放两次，PublicationIntent、DeliveryAttempt 和 fake 平台对象均不重复。
3. **故障**：模型 429/超时/格式错误分别按退避、有限重试、人工或失败路由处理。
4. **隔离**：跨 `org_id` 的 State 引用、Retriever 结果、Tool 调用和 API 请求全部拒绝。
5. **安全**：提示注入不能越权读取来源、Token 或调用发布 Tool。
6. **账号后置**：无账号运行全链路只产生私有 ExportPackage 或 synthetic fake 结果；真实账号接入创建新版本链。
7. **反馈**：站点、QA、GEO、人工和 Fake Observation 能生成可解释 Recommendation，但不会自动修改已批准版本。

## 9. Go/No-Go 清单

### Go：进入 M1-Core

- Graph State、Node I/O、事件和版本契约已冻结。
- Checkpoint 恢复、interrupt/resume、重放和幂等测试通过。
- `TopicSignal→Canonical→Variant→QA→Approval→Manual/Fake` E2E 通过。
- 业务事实仍在 PostgreSQL；AuditLog 和 Outbox 同事务。
- 没有真实账号、Token 或平台副作用依赖。

### Go：进入 M2

- M1 连续运行稳定，质量/成本/人工负载达到阈值。
- OAuth/Vault、Scope、Kill Switch、回查和撤销演练通过。
- 首个平台先 `draft_only`，再进行低频受控发布。

### No-Go 条件

- Node 直接写 ORM/数据库或直接调用平台 SDK。
- 将完整正文、Token 或 PII 放进 Graph State。
- 用 checkpoint 代替业务事实、审批或审计。
- unknown 外部结果自动重发。
- 为了 LangGraph 提前引入微服务、Kubernetes、Kafka 或多个真实平台。

## 10. 与 V2.4 的关系

V2.4 保留为领域和治理基线；V3 的 GRAPH/LC 任务是增量层。实施时应为本文件的任务建立对应 `docs/tasks/` 卡片，并把新任务登记到 `docs/task-registry.yaml`；在注册表更新前不得把 V3 任务标记为 `in_progress`。建议首批落地顺序：`GRAPH-GOV-001 → GRAPH-CORE-001~006 → GRAPH-STATE-001~005 → LC-MODEL-001/002 → GRAPH-NODE-001~004 → GRAPH-HUMAN-001 → GRAPH-REPLAY-001`。

