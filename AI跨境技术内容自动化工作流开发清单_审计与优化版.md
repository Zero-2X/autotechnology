# AI 跨境技术内容自动化工作流开发清单

## 审计与优化版 V2.4

**编制日期**：2026-09-14  
**依据**：`AI跨境技术内容自动化工作流实施计划清单.md`、`AI跨境技术内容自动化工作流开发清单.md`  
**核心目标**：先搭建一个不依赖真实账号的内容与知识生产架构，再接入真实授权账号和官方平台能力。
**默认首个纵向切片（由 `GOV-001` 锁定）**：`AI 技术与应用工程`，重点覆盖 LLM、RAG、Agent、LangChain/LangGraph、Prompt、模型评测、AI 应用架构、部署、可观测性、安全、隐私、版权和合规工程；中文 `zh-CN`、英文 `en-US`、文本内容、第一方知识站、手工导出和 Fake Platform。

> **V2.4 领域与治理基线**
>
> 本文件 **V2.4** 继续作为领域模型、治理、安全、账号后置、状态机、事件和验收口径的基线。采用 LangGraph 后，编排层和 LangChain 组件以 `AI跨境技术内容自动化工作流开发清单_LangGraph_V3.md` 及 `docs/adr/ADR-001-langchain-langgraph-architecture.md` 为执行基线。原文件和 V2.1 备份只作为需求来源与审计对照，不能作为 Codex 的执行输入。
>
> 开工顺序固定为：先执行 `FOUND-000`，核对仓库清点结果，再读取已提交的 `docs/task-registry.yaml`，最后一次只执行一个精确 `TASK-ID`。`FOUND-013` 负责在清单变化后维护并校验注册表。Markdown 只负责说明；任务注册表、`packages/contracts/jsonschema/` 和数据库迁移才是机器校验入口。
>
> 相对 V2.3 的关键修订：补充仓库清点、真实 Schema 真源、审批 quorum、TopicBrief 锁定、HumanTask 完整转换、TaskJob/Outbox 生命周期、FeedbackAction、并行路径所有权和原任务映射；原来的“12 周完成全部真实发布”计划废止。V2.4 进一步补齐状态机与事件登记闭环、机器契约闭环、任务卡就绪度分级和 Codex 开工门禁。

### 任务编号

```text
GOV-xxx       治理与合规
FOUND-xxx     工程底座
IAM-xxx       内部用户身份与权限
ACCOUNT-xxx   平台账号档案与连接
IAM-CORE-xxx  内部 IAM 基础实现
ACCOUNT-CORE-xxx 无凭证账号引用模型
TOPIC-xxx     选题智能
PROV-xxx      来源与版权
KNOW-xxx      知识资产与 Claim/Evidence
CANON-xxx     Canonical Content
PROD-xxx      翻译、本地化与内容生产
QA-xxx        事实、代码、相似度和可访问性质量
POLICY-xxx    策略门禁
APPROVAL-xxx  人工审批
AGENT-xxx     Agent 与工作流
AGENT-CORE-xxx Agent 注册、运行和工具网关
WORKFLOW-xxx  持久化状态机与人工任务
MODEL-xxx     模型网关与供应商适配
SCHED-xxx     定时任务与排程
OAUTH-xxx     OAuth 回调与凭证租约
EVAL-xxx      模型和 Prompt 评测
WORKFLOW-CORE-xxx 工作流基础契约
MODEL-CORE-xxx 模型网关基础契约
OBS-CORE-xxx   观测、审计和恢复基础
SITE-xxx      第一方知识站
GEO-xxx       GEO_CONTENT/GEO_REGION
GEO_CONTENT-xxx 生成式搜索内容优化
GEO_REGION-xxx 地域、本地化和区域规则
GEO_REGION-CORE-xxx 地域配置基础契约
MEDIA-xxx     媒体与资产
DIST-xxx      分发抽象与发布
PLAT-xxx      真实平台适配器
ANALYTICS-xxx 分析与归因
FEEDBACK-xxx  反馈与优化
FEEDBACK-CORE-xxx 无账号观测与反馈
FEEDBACK-LIVE-xxx 真实平台观测与归因
FEEDBACK-EXP-xxx 反馈实验
SUP-xxx       客服与统一收件箱
OBS-xxx       观测、审计与事故响应（真实运行与事故处置）
PILOT-xxx     试点与扩容
```

一个任务只解决一个可验收行为。每个任务必须有明确的允许修改目录、禁止修改范围、依赖、测试命令和 Given-When-Then 验收条件。

编号末尾的 `A/B/C...` 表示同一能力的独立子任务；子任务仍需单独验收、单独提交和单独记录迁移。未拆成子任务前，不得把同一条目中的多个外部副作用或多个供应商一次实现完。

---

## 0. 当前执行状态与阅读顺序

本版本已经完成架构审计、任务编号、依赖登记、事件索引、状态索引、JSON Schema 基线和 OpenAPI 基线；当前仓库仍然没有正式业务代码、生产凭证或可验收的真实平台连接。不要把“契约已生成”理解为“功能已实现”。

建议按以下顺序使用本清单：

1. 先读本文件第 1–3 节，确认范围、账号后置边界、模块依赖和默认技术基线。
2. 执行 `FOUND-000`，复核 `docs/repo-inventory.md`，确认已有代码和用户修改。
3. 读取 `docs/task-registry.yaml`，再读取目标 `docs/tasks/<TASK-ID>.md`；任务卡未达到精细化门禁时不得开工。
4. 以 `packages/contracts/jsonschema/`、`packages/contracts/events/` 和 `packages/contracts/openapi/openapi.yaml` 为机器契约真源，以 `docs/contracts/state-registry.yaml` 和 `docs/contracts/event-registry.yaml` 为索引。
5. 按“契约/迁移 → 测试 → 领域规则 → 用例 → 入口 → Outbox/审计 → 回放”的顺序一次执行一个任务。

可用的执行协议见 [`docs/CODEX_EXECUTION_PROTOCOL.md`](docs/CODEX_EXECUTION_PROTOCOL.md)。

阶段和任务有三种准备度含义：

- `planned`：已列入路线，但任务卡或迁移仍可能是占位；只能做规划和契约工作。
- `contract_ready`（准备度标签，不是任务状态）：机器契约、依赖和验收条件已具备，可以准备开工；仍未代表代码完成。
- `done`：代码、迁移、测试、审计、运行证据和回滚说明全部通过。

---

## 1. 审计结论

### 1.1 总体判断

你的原始计划方向完整，安全、版权、授权、审计和停发机制也比较扎实。主要问题不在“功能数量不够”，而在于领域边界、开发顺序和验收方式还不够精确。

| 项目 | 评价 | 主要原因 |
|---|---:|---|
| 治理与合规 | 8/10 | 已有风险分级和授权思路，还需补供应商处理、数据删除传播和 SLA |
| 内容与版权 | 8/10 | 已有来源和 RightsRecord，但缺少 Canonical Content 与派生链 |
| IAM 与账号 | 9/10 | 能力较完整，但放在核心流水线前段，造成无账号时无法开发 |
| Agent 与编排 | 7/10 | 角色过多、任务过大，容易让 Codex 一次生成大量不可验证代码 |
| GEO | 7/10 | 生成式搜索与地域本地化混在一起，应拆为两个领域 |
| Analytics | 5/10 | 有监控指标，但缺少统一事件语义、归因和反馈动作 |
| Topic Intelligence | 2/10 | 只有 Planner 概念，没有独立的选题信号、评分和决策模型 |
| Feedback Loop | 2/10 | 有结果监测，但没有自动回写选题、刷新、渠道和模型评测 |
| 基础设施 | 5/10 | 对 130 个账号提前引入微服务、Kubernetes 和多套中间件，成本过高 |
| 测试与运营台 | 7/10、5/10 | 有测试类别，但缺少 LLM golden set、证据对比视图、任务 SLA 和可访问性测试 |

### 1.2 对你提出的六条意见的判断

1. **账号移到 Distribution Layer：正确。** 但要区分两类 IAM：后台用户登录、角色和操作审计仍是基础能力；平台账号档案、OAuth 连接、凭证和账号健康属于 Distribution 子域，可以后置。
2. **增加 Canonical Content Layer：正确且必须优先。** 它应是与渠道和账号无关的内容语义、叙事、事实和证据源，不能简单等同于中文主稿。
3. **增加 Topic Intelligence 与 Feedback Loop：正确。** 选题原因、证据可行性、差异化和历史效果应该成为一级数据和工作流。
4. **保留账号风险治理，但不做对抗：正确。** Account Passport、授权证据、OAuth/Vault、权限和 Kill Switch 保留；不开发任何规避平台限制的功能。
5. **拆分 `GEO_CONTENT` 和 `GEO_REGION`：正确。** 前者解决内容被发现、理解、验证和引用；后者解决语言、市场、法规、单位、货币、时区、数据驻留和平台地区。
6. **Modular Monolith + Workers：正确。** 账号数量本身不是拆微服务或上 Kubernetes 的理由；应由吞吐、SLO、故障隔离、团队边界和数据驻留要求触发拆分。

### 1.3 原清单必须修正的地方

- 原清单把“视频、4 个平台、客服、完整 IAM、GEO 监测”同时放入 MVP，又在 P1 中再次列为后补项，范围互相矛盾。
- `contents` 的单一状态链把来源、Canonical 内容、翻译变体、媒体资产和发布任务混在一起，无法独立更新或回滚。
- `services/*`、`workers/*`、Temporal、Kafka、ClickHouse、OpenSearch、Kubernetes 等描述容易被误实现成伪微服务，增加维护成本。
- 一个任务编号常常包含 5–8 个能力，Codex 难以判断边界，容易扩大范围或留下半成品。
- 观测、审计、Outbox、幂等和架构测试被放得太晚；这些应从第一阶段就存在。
- 缺少 Topic 信号、选题 Brief、编辑日历、内容新鲜度、实验、归因、模型评测集、预算和数据删除传播。
- 缺少人工审批界面的差异对比、证据面板、审批覆盖期限、任务分派和 SLA。

### 1.4 V2.4 开工前必须解决的阻塞项

以下项目如果没有完成，Codex 只能继续做文档或契约，不能进入业务实现：

1. `FOUND-000` 完成仓库清点，确认当前仓库是否已有代码、迁移、依赖和环境变量；已有实现只能兼容扩展，不能覆盖。
2. `docs/task-registry.yaml` 列出每一个精确任务 ID。`depends_on` 禁止使用 `*`，禁止出现 `FEEDBACK-CORE-001/002` 这类复合 ID。
3. `packages/contracts/jsonschema/*.schema.json` 作为真实契约真源；本文件中的 JSON 仅作字段说明，不能替代 Schema 校验。
4. 所有状态机、事件和 API 命令必须一一对应；未列出的状态转换一律拒绝并返回错误码。
5. 审批聚合与 `approval_decisions` 明细分离；R3/R4 必须由两名不同审批人完成 quorum，创建人不能审批自己的内容。
6. 账号缺失时只允许 `manual_export` 或 `simulation`。真实 OAuth、Token、平台 HTTP 和真实指标必须等 `EXT-ACCOUNT-001` 满足后进入阶段 8。
7. 同一波次的任务不得同时修改同一迁移、契约或模块目录；注册表必须用 `owned_paths`、`shared_paths` 和 `exclusive_paths` 声明并行边界。

### 1.5 原清单功能映射

原清单的功能没有删除，而是按可验收边界重新拆分：

| 原任务/能力 | V2.4 任务 | 调整原因与进入阶段 |
|---|---|---|
| `QA-003` 代码沙箱、静态检查、依赖锁定、危险命令阻断 | `QA-003` + `FOUND-012A` | 沙箱属于 QA；锁定和扫描属于工程底座，阶段 1/4 分开验收 |
| Entity/Claim/Evidence Agent | `AGENT-CORE-005B`、`KNOW-001` | Agent 只产出候选和待核查项，事实写入仍由 Knowledge 用例完成 |
| Originality Agent | `AGENT-CORE-005D`、`QA-002` | 原创建议与相似度/披露检查分离，不能把翻译当原创 |
| CodeQA Agent | `AGENT-CORE-005E`、`QA-003` | 结果先进入人工任务，沙箱执行不得触碰生产凭证 |
| GEOLint Agent | `GEO_CONTENT-001`、`GEO_REGION-001` | 生成式搜索检查与地域规则分别建模 |
| Media/Distribution/Publisher/Monitor/Auditor Agent | `MEDIA-*`、`DIST-*`、`ANALYTICS-*`、`OBS-CORE-*` | 适配器和观测职责拆开，避免 Agent 直接产生外部副作用 |
| 原任务 `SUP-003`、`SUP-004`、`SUP-005`、`SUP-006`（legacy reference） | `SUP-001`、`SUP-002`、`ANALYTICS-003` | 先做草稿和升级，真实收件箱及发送后置到账号阶段 |
| 原任务 `OBS-002`、`OBS-008`（legacy reference）和事故响应 | `OBS-CORE-001`、`OBS-CORE-002`、`OBS-CORE-003`、`PILOT-004` | 观测骨架前置，真实事故演练在试点阶段验收 |

---

## 2. 先搭架构、后接账号是否可行

### 2.1 结论：可行，而且是更科学的顺序

在没有真实账号的情况下，可以完整开发和验证以下部分：

- Topic Intelligence、来源采集、版权台账和知识资产。
- `KnowledgeCore → CanonicalContent → ContentVariant` 内容链。
- 翻译、本地化、事实/代码/版权 QA、Policy Gate 和人工审批。
- 第一方知识中心、`GEO_CONTENT`、`GEO_REGION` 和文本可抓取性。
- 媒体脚本、字幕、素材权利、渲染和资产版本。
- `PublicationIntent`、手工导出包、Fake Adapter、幂等、重试、死信和重放。
- 审计、指标、成本记录、Feedback Loop 和内容刷新任务。

没有真实账号时不能验证：

- 真实 OAuth Scope、平台审核、配额、Webhook 和回查语义。
- 平台地区限制、账号健康、内容警告、真实发布结果和平台侧删除行为。
- 真实平台的上传格式、排程限制和政策变更响应。

因此，第一阶段的产品名称应是 **Account-free Architecture MVP（无账号架构 MVP）**，不能称为“可真实发布 MVP”。取得至少一个真实授权账号和一个可用的官方 Sandbox/测试主体后，才能进入 **Distribution Pilot Ready**。

### 2.2 无账号架构的正确边界

核心内容服务不依赖 Token，也不要求 `account_id` 到处为空。采用以下对象分层：

统一交付模式枚举（全项目只能使用这四个值）：

```text
manual_export   生成给人工发布的 ExportPackage，不产生平台副作用
simulation      仅调用 Fake Adapter，不产生真实平台副作用
draft_only      需要真实连接，但只允许创建平台草稿
authorized_api  需要真实连接，允许执行已批准的官方 API 动作
```

```text
AccountProfile
  法律主体、品牌、负责人、市场；可以是 planned 或 synthetic

AccountConnection
  平台连接、OAuth/Vault 状态、Scope、健康状态；无账号时不存在

DistributionTarget
  平台、市场、语言、渠道和环境；只描述稳定目标，不保存账号或能力快照

DistributionTargetVersion
  Target 的不可变快照；包含 Target 字段、AccountProfile/Connection 引用及脱敏快照、能力快照和政策快照

PublicationIntent
  内容变体、资产、目标 TargetVersion、标题、正文、标签、排程意图；不绑定 AccountConnection 或凭证

ExportPackage
  无账号时给人工使用的发布包

DeliveryAttempt
  一次手工导出、模拟发布或 API 发布尝试

PublicationRecord
  真实执行后的平台对象、外部 ID、URL、结果和回查信息
```

对外治理时仍保留 `AccountPassport` 这个概念：它是 `AccountProfile + AuthorizationEvidence + AccountConnection` 的只读汇总视图/证据包，不是新的凭证存储表。

推荐规则：

- `PublicationIntent` 不绑定 `AccountConnection` 或凭证，只绑定不可变的 `DistributionTargetVersion` 快照。
- `delivery_mode=manual_export` 时生成 `ExportPackage`，不需要账号连接。
- `delivery_mode=simulation` 时只能使用 Fake Adapter 和 synthetic target，`account_connection_id` 必须为空。
- `delivery_mode=draft_only` 时，`account_connection_id` 必须存在，且 `authorization_status=authorized`、`health_status=healthy`。
- `delivery_mode=authorized_api` 时，`account_connection_id` 必须存在，且 `authorization_status=authorized`、`health_status=healthy`，并通过平台能力和 Policy Gate。
- synthetic 账号只能在 dev/staging 使用；生产环境硬阻断任何副作用。
- 真实账号接入后，不修改既有 TargetVersion 或已执行/审批的 `PublicationIntent`；创建新的 TargetVersion 和 target-specific Intent，并记录 `derived_from_intent_id`，这样不需要重做内容生产且旧任务不会突然获得真实发布能力。

四种交付模式必须按下面的确定性矩阵校验；`delivery_mode` 不得脱离 `eligible_delivery_modes` 单独判断：

| `delivery_mode` | `AccountConnection` | `synthetic_target_id` | 允许环境 | 允许的副作用 | 适配器 |
|---|---|---|---|---|---|
| `manual_export` | 必须为空 | 可为空 | dev/staging/prod | 只生成私有 `ExportPackage`，不调用平台 | `ManualAdapter` |
| `simulation` | 必须为空 | 必须非空 | dev/staging | 只调用 `FakeOfficialAdapter`，创建完整模拟 Attempt/Record | `FakeOfficialAdapter` |
| `draft_only` | 必须存在且 connected/authorized/healthy | 必须为空 | staging/prod | 只创建平台草稿，不能直接发布 | 真实官方适配器 |
| `authorized_api` | 必须存在且 connected/authorized/healthy | 必须为空 | staging/prod | 仅执行已批准的官方 API 动作 | 真实官方适配器 |

`manual_export` 不要求账号，也不产生平台副作用；`simulation` 必须走与真实发布相同的幂等、回查、`unknown` 和重放链路，但 `provider_mode=fake`，其外部 ID 只能是 Fake ID。生产环境禁止 `synthetic_target_id` 和 Fake 副作用。`draft_only`/`authorized_api` 必须同时通过账号状态、Scope、平台能力、区域规则、PolicyDecision 和 Kill Switch；任何一个条件不满足都只能阻断或转人工。

环境权限矩阵：

| 环境 | 允许模式 | 禁止事项 |
|---|---|---|
| dev | `manual_export`、`simulation` | 真实 Token、真实平台副作用 |
| staging | `manual_export`、`simulation`、官方 Sandbox 的 `draft_only` | 未批准的真实发布、生产账号 |
| prod（无账号） | `manual_export` | synthetic 副作用、真实 API 调用 |
| prod（账号到位） | 经 Policy 允许的 `draft_only` 或 `authorized_api` | 未授权 Scope、被暂停账号、旧批准任务直接发送 |

### 2.3 账号获取作为外部依赖管理

账号不是代码任务的前置假设，而是单独登记的外部依赖：

```text
依赖 ID：EXT-ACCOUNT-001
需要的输入：法律主体、平台主体、授权人、官方 OAuth/Sandbox 条件
负责人：明确到人
最晚到位时间：进入真实 Distribution Pilot 前
阻塞影响：不能验收真实 Scope、配额、平台回查和账号健康
替代方案：Manual Export + FakeOfficialAdapter + synthetic fixtures
到位证据：授权记录、平台连接状态、Scope、回查结果和审计事件
```

不能用 synthetic 账号替代真实合规证据；synthetic 只用于开发、测试和模拟副作用。

平台账号、模型供应商账号和后台用户账号是三类不同依赖。平台账号缺失不会阻塞 M1；模型供应商凭证缺失时使用 Fake Model 或固定 fixture；后台用户身份和最小权限则必须在阶段 1 建立。

---

## 3. V2 目标架构

### 3.1 领域层级

```text
Governance / Product / Risk
        ↓
Topic Intelligence
        ↓
Provenance / Rights
        ↓
KnowledgeCore + Canonical Content
        ↓
Localization / Production / QA / Policy / Approval
        ↓
GEO_CONTENT + GEO_REGION
        ↓
Media / Asset
        ↓
Distribution（Manual Export / Simulation / Draft Only / Authorized API）
        ↓
Observations（站点、平台、客服、GEO、质量、成本）
        ↓
Feedback / Optimization
        ↺ 回写选题、刷新、变体、渠道和模型评测
```

`IAM` 分成两部分：

- `Internal IAM`：后台用户、组织、角色、操作权限和审计，从第一阶段开始做。
- `Account IAM`：平台账号、OAuth、Vault、账号健康和授权证据，作为 Distribution 子域后置。

### 3.2 默认技术基线

为了让 Codex 可以准确构建，V2 固定一套默认实现，不在开发中途反复选择：

| 部分 | 默认实现 | 何时替换 |
|---|---|---|
| Web Console | Next.js + TypeScript | 只有前端已有统一技术栈时替换 |
| API/领域模块 | Python 3.12 + FastAPI | 团队已确定 Go 且 Agent 运行环境不依赖 Python 时替换 |
| ORM/迁移 | SQLAlchemy 2 + Alembic | 数据库或语言统一要求改变时替换 |
| 主数据库 | PostgreSQL 16 | 吞吐、地域或团队边界证明需要拆库时替换 |
| 向量检索 | pgvector，可选启用 | 数据量和检索延迟达到阈值后再独立化 |
| 任务执行 | PostgreSQL `task_jobs` + Outbox + Worker polling | 长流程、跨团队重试和高并发满足条件后评估 Temporal |
| 缓存/锁 | Redis，仅用于缓存和短锁 | 不承担唯一事实和审计数据 |
| 对象存储 | S3 兼容存储 | 媒体容量或数据驻留要求改变时替换 |
| 密钥 | 云 Secret Manager/KMS；无真实账号阶段只使用假凭证 | 有真实 OAuth 后启用生产租约和轮换 |
| 观测 | OpenTelemetry + 结构化日志 + Prometheus | 指标规模达到独立分析系统门槛后再引入 ClickHouse |
| 部署 | Docker Compose（开发）+ API/Worker/Scheduler 三个后端进程；Web 前端单独构建 | 满足拆分触发条件后再上 Kubernetes |

根目录同时固定以下工具和命令，Codex 不得自行选择替代命令：

```text
pyproject.toml             Python 依赖、pytest、ruff、mypy
package.json               Web 依赖和脚本
pnpm-workspace.yaml        Web workspace
Taskfile.yml               跨平台任务入口

task dev                   启动本地依赖、API、Worker、Scheduler 和 Web
task test                  运行全部单元/集成测试
task lint                  运行 ruff、mypy、eslint、格式检查
task migrate               执行 Alembic 迁移
task seed                  写入 synthetic fixtures
task smoke                 执行首个纵向切片
task arch-test             执行模块依赖和禁止导入检查
```

初期后端只部署：

```text
API 进程
Worker 进程
Scheduler 进程
```

Web Console 和 Knowledge Site 作为前端构建产物部署，可以由 Next.js Server 或同域反向代理提供；它们不是业务领域服务。

初期不引入 Kafka、Redpanda、RabbitMQ、ClickHouse、OpenSearch、自建 Vault、Kubernetes 和 Temporal。它们可以记录为未来选项，但不能作为当前开发前置条件。

### 3.3 推荐目录

```text
ai-content-workflow/
├─ apps/
│  ├─ api/                         # FastAPI 入口和 HTTP 层
│  ├─ web-console/                 # 运营、审批、知识、指标后台
│  ├─ worker/                      # 任务消费和异步执行
│  ├─ scheduler/                   # 定时任务、刷新和 GEO 采样
│  └─ knowledge-site/              # 第一方知识中心
├─ modules/                        # 逻辑模块，初期不独立部署
│  ├─ governance/                  # 组织、角色、风险、政策卡
│  ├─ iam/                         # 内部用户权限；账号连接接口在 distribution
│  ├─ topic/                       # 信号、机会评分、Brief、编辑日历
│  ├─ provenance/                  # Source、Snapshot、Rights、撤回
│  ├─ knowledge/                   # Entity、Claim、Evidence、KnowledgeCore
│  ├─ canonical_content/           # CanonicalContent 和版本链
│  ├─ production/                  # Variant、翻译、本地化、原创改编
│  ├─ workflow/                     # 持久化状态机、人工任务、重试和重放
│  ├─ model_gateway/                # ModelPort、脱敏、预算、供应商路由
│  ├─ qa/                          # 事实、代码、相似度、可访问性
│  ├─ policy/                      # 确定性策略门禁和审批条件
│  ├─ geo_content/                 # 可抓取、可引用、Schema、内容新鲜度
│  ├─ geo_region/                  # 地区、语言、单位、法规、数据驻留
│  ├─ media/                       # 脚本、分镜、字幕、渲染
│  ├─ distribution/                # Target、Intent、Export、Delivery
│  ├─ support/                     # 评论、私信、客服草稿
│  ├─ analytics/                   # 规范事件、指标和归因
│  ├─ feedback/                    # 观察→动作→复评
│  └─ audit/                       # 追加式审计和证据包
├─ adapters/
│  ├─ contract/                    # Port、能力和错误码
│  ├─ fake/                        # FakeOfficialAdapter、FakeInbox、FakeGeo
│  ├─ manual/                      # 人工导出包适配器
│  └─ platforms/<platform>/        # 后置的真实平台适配器
├─ packages/
│  ├─ contracts/                   # OpenAPI、事件和 JSON Schema 真源
│  │  ├─ openapi/
│  │  ├─ events/
│  │  └─ jsonschema/
│  ├─ db/                          # 会话、迁移、查询和 Outbox
│  ├─ observability/               # trace、log、metric、correlation id
│  ├─ prompt_registry/             # Prompt 版本、golden set、评测
│  └─ testkit/                     # fixtures、fake clock、重放工具
├─ tests/
│  ├─ unit/                        # 领域规则
│  ├─ integration/                 # DB、Outbox、Worker
│  ├─ contract/                    # API、事件、适配器
│  ├─ replay/                      # 失败任务和历史事件重放
│  ├─ security/                    # 越权、注入、秘密和 PII
│  ├─ accessibility/               # 页面和字幕可访问性
│  └─ e2e/                         # 首个纵向切片
├─ infra/
│  ├─ compose/                     # 本地依赖
│  ├─ scripts/                     # 迁移、备份、恢复、数据检查
│  └─ policies/                    # OPA 或等效策略
├─ deploy/
│  └─ environments/
│     ├─ dev/                     # 开发配置模板，不放凭证
│     ├─ staging/                 # 测试配置模板，不放凭证
│     └─ prod/                    # 生产配置模板，不放凭证
├─ docs/
│  ├─ adr/
│  ├─ contracts/                  # 契约说明、变更记录和索引
│  ├─ modules/
│  ├─ runbooks/
│  ├─ workflows/
│  ├─ task-registry.yaml          # Codex/CI 的机器任务清单，必须列出全部任务
│  └─ external-dependencies.yaml  # 账号、模型、存储等外部依赖和替代方案
├─ scripts/
│  ├─ check_plan_consistency.py      # 计划、状态机、事件、API 和模式矩阵校验
│  └─ repo_inventory.py               # FOUND-000 使用的仓库清点脚本
├─ .env.example
├─ pyproject.toml
├─ package.json
├─ pnpm-workspace.yaml
├─ Taskfile.yml
├─ CODEOWNERS
├─ CONTRIBUTING.md
└─ README.md
```

目录规则：

- `modules` 是逻辑边界，不代表独立进程；初期可以共享一个 PostgreSQL，但每个模块拥有自己的表和公开用例。
- 领域模块之间只能通过公开用例、命令和事件交互，不能直接修改其他模块的表。
- 平台 HTTP 请求只能出现在 `adapters/platforms`。
- Worker 不复制业务规则，只消费任务并调用模块用例。
- 每个模块必须有 `README.md`，说明职责、表、公开接口、事件、权限和禁止事项。
- `docs/task-registry.yaml` 是机器唯一来源；Markdown 阶段表只是阅读版，不能作为 CI 的依赖输入。
- 开工前先执行 `FOUND-000` 清点现有仓库；已有技术栈、目录或迁移时只做兼容扩展，不覆盖现有实现。只有空仓库才采用本文件的默认技术基线。

### 3.3.1 模块内部统一布局

为了让后续修改有固定落点，每个 `modules/<module>/` 必须遵循同一层次，不允许把领域规则、数据库查询和 HTTP 代码混在一个文件夹中：

```text
modules/<module>/
├─ README.md              # 职责、Owner、公开用例、事件、权限、禁止依赖
├─ domain/                # 实体、值对象、状态机和纯业务规则
├─ application/           # 用例、命令、事务边界和权限检查
├─ ports/                 # 本模块需要的外部接口；只放抽象和 DTO
├─ infrastructure/        # 本地实现、数据库仓储、事件发布器
└─ projections/           # 只读查询模型和列表/详情投影
```

以下约束是可执行的维护规则：

- `domain` 不得导入 FastAPI、ORM、供应商 SDK 或其他模块的 `infrastructure`。
- `application` 只能调用本模块公开用例和已登记的 Port；跨模块操作必须通过命令、事件或查询接口完成。
- `infrastructure` 可以实现 Port，但不能把供应商类型泄漏到 `domain`、OpenAPI 或公共事件中。
- `projections` 是可重建的读模型，不是事实源；任何写入必须回到拥有该事实的模块用例。
- 数据库表按模块归属放在 `packages/db` 的命名空间或迁移文件中；迁移文件名必须包含任务 ID，查询代码只能由表的 Owner 修改。
- `apps/api`、`apps/worker` 和 `apps/scheduler` 只负责入口、依赖装配、租约和调用用例，不实现领域判断。`apps/web-console` 只能调用 API，不直接连接数据库。
- `adapters/` 只实现 Port。`manual`、`fake` 和真实平台适配器必须互相独立，禁止用真实适配器的分支逻辑模拟 Fake 行为。
- 新增公共工具前先判断其归属；禁止建立无边界的 `modules/common` 或 `utils`，共享内容必须进入 `packages/<明确用途>` 并登记 Owner。

模块 README、任务卡和注册表必须同时更新。目录移动、模块改名或跨模块依赖变化先写 ADR，再修改代码；这样 Codex 能根据任务卡的 `allowed_paths` 找到唯一修改位置。

### 3.4 WorkflowPort、ModelPort 和外部 IO 边界

核心模块只依赖端口（Port），不依赖具体供应商：

```text
modules/model_gateway/ModelPort
  generate_structured() / embed() / transcribe() / synthesize()

modules/workflow/WorkflowPort
  start() / resume() / pause() / retry() / replay()
  create_human_task() / complete_human_task() / expire_human_task()
  scan_expired_human_tasks() / wait_for_signal()

modules/distribution/ConnectionPort
  authorize() / health_check() / revoke()

modules/distribution/PublisherPort
  capabilities() / create_draft() / upload() / schedule() / publish() / fetch_status() / remove()

modules/distribution/WebhookPort
  verify() / receive() / dedupe() / replay()

modules/distribution/MetricsPort
  fetch_metrics() / normalize_observation()

modules/support/InboxPort
  list_threads() / list_messages() / create_draft() / send()
```

真实供应商、Fake Provider 和人工导出分别实现这些端口。`PublisherPort` 接收短时的 connection handle，不接收 raw token；`remove()` 只有在平台能力、Policy、Kill Switch 和人工授权都通过时才能调用。Webhook 验签、去重和回放属于 `WebhookPort`，不能塞进指标端口。`InboxPort.send()` 是真实副作用，只能在阶段 8 以后、经过 Policy 和人工批准后开放。

### 3.5 任务表和 Outbox 的最小语义

`task_jobs` 至少包含：`id`、`org_id`、`job_type`、`queue_name`、`aggregate_type`、`aggregate_id`、`aggregate_version`、`payload_ref`、`status`、`attempt_count`、`max_attempts`、`available_at`、`lease_until`、`locked_by`、`last_error`、`idempotency_key`、`trace_id`、`created_at`、`updated_at`。

`outbox_events` 使用与公共事件相同的信封，至少包含：`event_id`、`event_type`、`event_schema_version`、`occurred_at`、`org_id`、`trace_id`、`correlation_id`、`causation_id`、`aggregate_type`、`aggregate_id`、`aggregate_version`、`actor_type`、`actor_id`、`idempotency_key`、`payload`、`payload_hash`、`published_at`、`attempt_count`、`last_error`、`status`。

执行规则：

1. 业务状态和 Outbox 事件在同一个数据库事务中提交。
2. `OutboxDispatcher` 采用 at-least-once 投递；失败时指数退避，超过上限进入死信（DLQ）。同一 aggregate 按 `aggregate_version` 有序，Consumer 按 `event_id` 去重。
3. Worker 用租约领取任务；`lease_until` 过期后可以再次领取。
4. 每个副作用动作先检查幂等键，再检查 Kill Switch 和 PolicyDecision。
   `PublicationIntent.intent_key` 是一次逻辑交付的稳定键；`DeliveryAttempt.id`/`attempt_no` 记录执行历史，供应商幂等键在同一逻辑交付的重试中保持稳定。未知结果不得自动创建新的副作用请求。
5. `retryable` 是临时执行结果，不是业务最终状态；Attempt 最终结果必须是 `succeeded`、`failed`、`unknown` 或 `dead_letter`。
6. `human_tasks` 是唯一人工任务事实源；若需要兼容旧名，`review_tasks` 只能是查询视图或 subtype，不能再建第二张可写事实表。人工任务单独保存类型、分派人、claim lease、SLA、截止时间、输入版本、完成结果和 override 过期时间；不能把人工审批塞进普通任务 payload。
7. 事件可以重放，但重放只重新计算内部状态或生成新命令；外部副作用必须复用原始 provider 幂等键并先查询结果，禁止因重放再次创建平台对象。

### 3.6 模块拆分触发条件

只有至少满足以下一项并完成 ADR，才考虑从模块化单体拆成独立服务：

- 某模块需要独立扩缩容，且连续两个周期影响整体 SLO。
- 某模块故障必须与核心内容流程隔离。
- 团队已有明确的服务 Owner 和独立发布能力。
- 数据驻留、权限或合规要求必须独立部署。
- 媒体渲染或 GEO 采样资源长期占用核心 Worker，且无法通过队列隔离解决。

“未来可能有 130 个账号”本身不是拆服务或上 Kubernetes 的条件。

### 3.7 模块依赖方向

允许的依赖图如下，架构测试必须把它写成可执行规则：

```text
TopicBrief ───────────────────────────────┐
                                          ├→ canonical_content
Provenance/Rights → KnowledgeCore ────────┘        ↓
                                      production → qa → policy → approval
                                                              ├→ geo_region / geo_content → media → distribution
                                                              └→ support

support 与 distribution 并列，二者都依赖适配器能力、KnowledgeCore、Policy 和 Analytics；Support 可以把发布记录作为可选上下文，不把发布作为客服的硬前置条件。
governance / iam / audit / observability 是横切能力。
feedback 只通过 topic、canonical 或 production 的公开用例提交 Recommendation/Refresh 命令，不能反向直写业务表。
```

明确禁止：

- `canonical_content` 依赖 `distribution` 或任何平台 SDK。
- `distribution` 直接修改 `content`、`rights` 或 `approval` 表。
- `workers` 自己实现一套与模块不同的状态转换。
- 任何模块绕过 `ModelPort`、`WorkflowPort` 或 `PublisherPort` 直接访问外部供应商。

---

## 4. 核心数据模型与状态机

### 4.1 核心对象链

```text
TopicSignal
  → TopicOpportunity
  → TopicBrief
  → Source / RightsRecordVersion
  → KnowledgeCore
  → CanonicalContentVersion
  → VariantVersion(locale, market, audience)
  → AssetVersion(media, platform)
  → PublicationIntent
  → ExportPackage / DeliveryAttempt
  → PublicationRecord
  → Observation
  → FeedbackItem / Experiment
```

字段事实源规则：关系表（例如 `canonical_claims`、`claim_evidences`、`asset_rights`）是写入事实源；对象契约中的 `*_ids` 数组只作为不可变快照或读取投影。`Evidence.claim_id` 只为兼容单 Claim 查询的可选投影，不是多对多关系的唯一来源。写入关系时必须同时校验租户、版本和状态，不能由 API 客户端直接维护两套可写数据。

### 4.2 表目录与分期边界

下面的目录按交付分期划分。表名只是规划清单；每一张表必须在进入所属波次前登记 Owner、`contract_ref`、迁移路径和验收命令。未进入该波次前，Codex 禁止自行创建表或猜测字段。

```text
M1-P0（首个无账号纵向切片，必须先完成）
organizations, users, organization_memberships, role_bindings, roles, permissions
feature_flags, kill_switches
platforms, policy_versions, policy_snapshots, policy_decisions
topics, topic_signals, topic_opportunities, topic_briefs, topic_score_snapshots
region_profiles, region_profile_versions
sources, source_snapshots, rights_records, rights_record_versions
entities, claims, evidences, knowledge_cores, knowledge_core_versions
entity_claims, claim_evidences, canonical_claims
canonical_contents, canonical_content_versions
content_variants, variant_versions
distribution_targets, distribution_target_versions
account_profiles
publication_intents, export_packages, delivery_attempts, publication_records
observations, metric_definitions, feedback_items
human_tasks, approvals, approval_decisions, sla_policies
task_jobs, task_failures, outbox_events, inbox_events, audit_logs
workflow_runs, workflow_steps, agent_definitions, agent_runs, model_calls, prompt_versions

M1-P1（P0 Gate 通过后，知识站/GEO/媒体/评测，可延期）
site_pages, site_page_versions, site_publications
geo_query_fixtures, geo_runs
assets, asset_versions, asset_rights, asset_claims, render_jobs
experiments, eval_runs, feedback_actions

M2/M3（真实账号、平台、客服和规模化）
account_connections, authorization_evidences（M1 已有的 account_profiles 只作为无凭证身份对象继续复用）
oauth_authorization_sessions, token_leases, account_health_checks
platform_capability_versions, webhook_receipts
market_rules, disclosure_rules, platform_policies
attribution_events, support_threads, support_tickets, support_drafts
quotas, budgets, budget_usages, risk_events, deletion_requests
```

M1-P0 的首个纵向切片只要求文本内容；`PublicationIntent.asset_version_ids` 可以为空数组。媒体表和渲染任务进入 M1-P1 后，必须先完成权利、版本和 QA 契约，再接入分发；它们不会阻塞文本 Manual Export/Fake 流程。`eval_runs` 与 `prompt_versions` 若被 Agent/Model 任务引用，按 M1-P0 创建；`experiments` 仍属于 M1-P1。

关系表是事实源；对象中的 ID 数组只作为不可变快照或读取投影。`review_tasks` 只能是 `human_tasks` 的视图，不能再建第二个写入事实源。

`platforms`、全局 `platform_policies`、全局区域/指标目录可以作为 global catalog；组织级覆盖必须另存版本并明确优先级，不能直接改写全局记录。`review_tasks` 不单独建事实表，若旧代码需要该名称，只提供 `human_tasks` 的查询视图。

表类型必须在迁移和契约中写明，避免把投影误当成第二个事实源：

- `*_versions`、`claims`、`evidences`、`rights_record_versions`、`approval_decisions`、`delivery_attempts`、`publication_records` 是不可覆盖的事实或版本记录。
- `site_publications`、`current_version_id`、`AccountPassport` 和 `RightsRecord` 父对象状态是由事实记录投影出的读模型；只能由所属用例在同一事务刷新。
- `inbox_events`、`webhook_receipts`、`outbox_events` 是追加式入口/投递记录，原始载荷放私有对象存储并保存哈希，不允许删除后重建历史。
- `sla_policies`、`platform_policies`、`policy_versions`、`metric_definitions`、`region_profile_versions` 是带版本的配置事实；生效后只能创建新版本。
- `workflow_runs`、`workflow_steps`、`task_jobs`、`render_jobs` 是运行控制记录；它们可以重试，但不能改变已产生的业务事实。

### 4.3 关键约束

- 除 `platforms`、全局政策目录和其他明确标注为 global catalog 的表外，所有 tenant-owned 表必须带 `org_id`；API、Worker、Scheduler、对象存储、缓存、向量/搜索索引和备份路径都必须带租户上下文。客户端不能自行指定任意 `org_id`，由认证后的 `TenantContext` 注入。
- tenant-owned 外键必须引用同一 `org_id` 的父记录；唯一键按租户限定，例如 `(org_id, job_type, idempotency_key)`、`(org_id, intent_key)`、`(org_id, platform_id, external_account_id)`。共享平台账号的转移必须创建新的归属记录并留下审计，不得直接改写历史记录。
- `org_id=null` 只允许出现在明确的 global catalog（例如 `Platform`、全局 `MetricDefinition` 或全局 `PolicySnapshot`）；一旦对象的 `subject_id` 指向租户数据，`org_id` 必须非空且与被引用对象一致。`RegionProfileVersion`、`PolicySnapshot`、`MetricDefinition`、`Approval` 和 `HumanTask` 的 FK/复合 FK 必须执行同一租户约束。
- 所有版本不可覆盖：`(entity_id, version_no)` 唯一。
- 所有派生对象必须保存来源对象 ID 和版本号，例如 `canonical_content_version_id`。
- 内容、资产或 Claim 被撤回时，沿派生链冻结受影响对象。
- `publication_intents` 不要求账号连接；`delivery_attempts` 按交付模式决定是否要求连接。
- `publication_records` 才保存平台外部 ID、URL 和真实执行结果。
- `distribution_target_versions` 保存声明时的完整 `capability_snapshot`；`publication_intents` 只保存其哈希和 `policy_snapshot_id`，避免复制后漂移；`delivery_attempts` 保存执行时实际读取的 `adapter_version` 和 `capability_snapshot`。执行时能力哈希不一致必须阻断并创建新 TargetVersion/Intent。
- `rights_records` 只保存权利对象身份和 `current_version_id`；每次权利范围、期限或条款变化都创建不可变的 `rights_record_versions`。`CanonicalContentVersion.rights_snapshot_ids` 必须只引用具体版本快照，不能引用可变当前记录；Claim 与权利版本的对应关系写入 `canonical_claims`。
- `distribution_targets` 只保存平台、市场、语言、渠道和环境；账号引用、脱敏账号快照、能力和政策快照只能保存在不可变的 `distribution_target_versions`。
- `publication_intents.distribution_target_version_id` 必须指向创建时的目标版本；修改账号、能力、政策或地区目标时创建新版本和新 Intent，不修改旧快照。
- `platforms.key` 必须全局唯一；`distribution_targets.platform_id` 必须为有效 Platform；同一组织内 `(org_id, platform_id, market, locale, channel, environment)` 只能有一个稳定 Target。
- Target 创建后 `platform_id/market/locale/channel/environment` 五个稳定维度均不可变；其中任何一个改变都必须创建新的 Target。TargetVersion 只复制稳定字段并保存账号、能力和政策快照。
- `synthetic_target_id` 非空时，`(org_id, environment, synthetic_target_id)` 必须唯一；真实 TargetVersion 不得复用 synthetic ID。
- `eligible_delivery_modes` 重新计算时必须创建新的 TargetVersion，不能在旧版本上追加模式；live AccountConnection 和当前 Policy 只用于 preflight，历史判定仍以不可变快照为准。
- `PublicationIntent.policy_snapshot_id` 在 `planned` 阶段可为空；`prepare` 前必须与 `DistributionTargetVersion` 和内容对象采用的 Policy 快照一致。Policy 过期或变化时禁止回写旧 Intent，必须重新计算并创建新的 Intent。
- `claims`、`evidences` 和 `canonical_content_versions` 保存 `valid_from`、`valid_to`、`review_due_at`、`supersedes` 和 `freshness_status`。
- `task_jobs` 使用 `(org_id, job_type, idempotency_key)` 唯一；`publication_intents` 使用 `(org_id, intent_key)` 唯一；Outbox `event_id` 为全局 UUID 唯一，Consumer 仍按 `event_id` 去重。
- `RightsRecord.current_version_id` 只能指向同一记录下 `status=verified` 且当前时间未过期、未撤销、未投诉冻结的版本。验证成功时，父记录的 `status` 和 `current_version_id` 必须与版本状态在同一事务中原子更新；版本过期、撤销或投诉冻结时，必须原子地切换到另一个有效版本或置空。续期、范围/条款变化只能创建新版本，不能把终态版本改回 `verified`。
- `RegionProfile.current_version_id`、`KnowledgeCore.current_version_id`、`ContentVariant.current_version_id` 和 `CanonicalContent.current_version_id` 只能在对应 Version 激活/批准的同一事务中更新；旧版本保持只读，过期或撤回时不得把指针静默指向未审版本。
- 审计日志只追加；普通业务管理员不能更新或删除。
- 数据删除必须传播到关系库、对象存储、向量索引、缓存、搜索索引、备份标记和审计最小证明。

### 4.4 分离的状态机

不要用一条 `draft → published` 覆盖所有对象。至少实现以下状态机：

```text
TopicOpportunity:
captured → scored → approved → briefed → in_production → monitoring
scored → rejected
monitoring → refresh
refresh → in_production
monitoring → retired

TopicBrief（`approved` 即锁定，不另设可写的 locked 状态）：
draft → approved（同一事务写入 `locked_at`、`locked_by`、`lock_hash`）
draft → rejected
draft → deferred
approved → superseded（需要修改时创建新版本，旧版本保持只读）

SourceSnapshot（append-only 快照）：
captured → quarantined → usable
captured|quarantined|usable → expired|revoked|blocked

Entity（根对象）：
draft → active → retired

Claim：
draft → verified → withdrawn
verified → freshness_status=stale（由复核任务投影；`status` 仍为 `verified`，不能直接恢复为新事实）

Evidence（append-only 证据）：
captured → valid
valid → expired|revoked

KnowledgeCore：
draft → active → retired

KnowledgeCoreVersion:
draft → verified
verified → superseded|withdrawn

ContentVariant（根对象）：
draft → active → withdrawn|retired

Asset（根对象）：
draft → active → withdrawn|retired

Platform（全局目录）：
none → active → disabled

AccountProfile（账号身份，不含凭证）：
planned → active → restricted|retired
active → restricted → active

AuthorizationEvidence（append-only 证据）：
pending → verified
verified → expired|revoked

SitePage / SitePageVersion（站点发布对象）：
draft → ready → published
published → superseded|rolled_back

GeoQueryFixture（append-only 测试输入）：
created → active → retired

Source:
none → ingested
ingested → quarantined → usable
usable → expired
usable → revoked
usable → blocked
ingested → blocked
quarantined → blocked
usable → blocked

DistributionTarget:
none → active
active → retired

DistributionTargetVersion:
none → draft
draft → active
active → retired

RegionProfile:
none → active
active → retired

RegionProfileVersion:
none → draft
draft → active
active → retired

PolicySnapshot:
none → active
active → expired
active → revoked

RightsRecordVersion:
none → pending
pending → verified
verified → expired
verified → revoked
verified → complaint_hold

RightsRecord（父对象）：
pending → verified（仅当 current_version_id 指向有效 verified 版本）
verified → expired|revoked|complaint_hold（当前版本失效且无其他有效版本时）

CanonicalContentVersion:
draft → evidence_pending → fact_checked → approved
approved → superseded
approved → withdrawn

VariantVersion:
planned → draft → localized → qa_pending → approved
approved → withdrawn

AssetVersion:
planned → rendering → qa_pending → approved → withdrawn
planned|rendering|qa_pending → blocked

PublicationIntent:
planned → ready → exported
planned → ready → simulated
planned → ready → queued → dispatched
planned → blocked
ready → blocked
queued → blocked
ready → cancelled
queued → cancelled

ExportPackage:
available → expired
available → revoked

Approval:
pending → approved|rejected|expired|revoked
approved → revoked（权利、事实、政策或目标快照失效时）

HumanTask:
queued → assigned → claimed → in_progress → submitted → completed
queued|assigned|claimed|in_progress|submitted|escalated → rejected|expired|cancelled
queued|assigned|claimed|in_progress|submitted → escalated → assigned

TaskJob（运行控制对象，不是业务事实）：
queued → leased → running → succeeded
running → failed → retry_scheduled → queued
failed → dead_letter
queued|leased|running → cancelled

OutboxEvent（投递控制对象，业务事件本身不可变）：
pending → publishing → published
publishing → failed → pending
failed → dead_letter

DeliveryAttempt:
created → running
running → succeeded
running → failed (retryable 或 terminal)
running → unknown (需要人工核查)
unknown → succeeded|failed (仅 `resolve_unknown` 人工核查)
failed → dead_letter (retryable=false 或超过 max_attempts)
failed → created (仅 retryable=true 时创建新的 Attempt 记录)

PublicationRecord:
none → attempted
attempted → acknowledged → published
attempted → acknowledged → failed
attempted → acknowledged → unknown
unknown → published|failed（仅人工核查并保存证据后）
published → removed

AccountConnection:
connection_status: unavailable → pending → connected → revoked
connection_status: revoked → pending（重新发起授权）
authorization_status: unknown → authorized
authorization_status: authorized → expired
authorization_status: authorized → revoked
authorization_status: expired|revoked → authorized (重新授权并生成新证据)
health_status: unknown → healthy
health_status: healthy → degraded
health_status: degraded → restricted
health_status: degraded|restricted → healthy (健康检查连续通过)

KillSwitch：
active → paused → active（resume 必须记录操作者、原因和时间）

只有 `connection_status=connected`、`authorization_status=authorized`、`health_status=healthy` 同时满足时，才允许 `draft_only` 或 `authorized_api`。
```

状态只能由所属模块的确定性用例转换；跨模块通过命令或事件，不直接写状态字段。

### 4.5 关键状态转换表

下面的转换是 MVP 的最小实现。未列出的转换一律拒绝，并返回明确错误码。

| 对象 | 当前状态 | 命令 | 守卫 | 下一状态 | 事件 |
|---|---|---|---|---|---|
| TopicOpportunity | `captured` | `score` | 信号快照存在 | `scored` | `topic.opportunity.scored` |
| TopicOpportunity | `scored` | `approve` | 有负责人和风险判断 | `approved` | `topic.opportunity.approved` |
| TopicOpportunity | `scored` | `reject` | 有拒绝原因 | `rejected` | `topic.opportunity.rejected` |
| TopicOpportunity | `approved` | `create_brief` | 选题字段完整 | `briefed` | `topic.brief.created` |
| TopicBrief | `draft` | `approve` | 目标、问题、Claim、证据计划、原创角度和市场完整 | `approved` | `topic.brief.approved` |
| TopicBrief | `draft` | `reject` | 有拒绝原因 | `rejected` | `topic.brief.rejected` |
| TopicBrief | `draft` | `defer` | 有延期原因、责任人和下次复核时间 | `deferred` | `topic.brief.deferred` |
| TopicBrief | `approved` | `supersede` | 新版本已创建；旧版本不可修改 | `superseded` | `topic.brief.superseded` |
| TopicOpportunity | `briefed` | `start_production` | 关联 `TopicBrief.status=approved` 且 Brief 已锁定 | `in_production` | `topic.production.started` |
| TopicOpportunity | `in_production` | `start_monitoring` | 至少一个 Variant 已批准 | `monitoring` | `topic.monitoring.started` |
| TopicOpportunity | `monitoring` | `request_refresh` | 触发刷新规则且有证据 | `refresh` | `refresh.requested` |
| TopicOpportunity | `refresh` | `start_refresh` | Recommendation 已批准且刷新任务已创建 | `in_production` | `topic.refresh.started` |
| TopicOpportunity | `monitoring` | `retire` | 有归档原因 | `retired` | `topic.retired` |
| Source | `none` | `ingest` | 输入已登记并生成不可变快照 | `ingested` | `source.ingested` |
| Source | `ingested` | `quarantine` | 外部输入未完成安全检查 | `quarantined` | `source.quarantined` |
| Source | `quarantined` | `mark_usable` | 安全检查和来源规则通过 | `usable` | `source.usable` |
| Source | `ingested` | `block` | 命中安全/来源规则 | `blocked` | `source.blocked` |
| Source | `quarantined` | `block` | 无法通过安全/来源规则 | `blocked` | `source.blocked` |
| Source | `usable` | `expire` | 到达 `valid_to` 或复核期限 | `expired` | `source.expired` |
| Source | `usable` | `revoke` | 权利人撤销或投诉 | `revoked` | `source.revoked` |
| Source | `usable` | `block` | 安全、权利或政策规则命中 | `blocked` | `source.blocked` |
| SourceSnapshot | `captured` | `quarantine` | 外部输入尚未完成安全检查 | `quarantined` | `source.snapshot.quarantined` |
| SourceSnapshot | `quarantined` | `mark_usable` | 安全检查通过 | `usable` | `source.snapshot.usable` |
| SourceSnapshot | `captured/quarantined/usable` | `expire` | 快照超过有效期 | `expired` | `source.snapshot.expired` |
| SourceSnapshot | `captured/quarantined/usable` | `revoke` | 来源权利撤销或投诉 | `revoked` | `source.snapshot.revoked` |
| SourceSnapshot | `captured/quarantined/usable` | `block` | 安全、权利或政策规则命中 | `blocked` | `source.snapshot.blocked` |
| Entity | `draft` | `activate` | 名称、别名和去重键通过校验 | `active` | `entity.activated` |
| Entity | `active` | `retire` | 有替代实体或归档原因 | `retired` | `entity.retired` |
| Claim | `draft` | `verify` | 至少一个有效 Evidence，冲突已处理 | `verified` | `claim.verified` |
| Claim | `verified` | `withdraw` | 事实失效、冲突或权利撤回 | `withdrawn` | `claim.withdrawn` |
| Evidence | `captured` | `validate` | 来源快照有效且定位信息完整 | `valid` | `evidence.validated` |
| Evidence | `valid` | `expire/revoke` | 来源快照或权利失效 | `expired/revoked` | `evidence.invalidated` |
| KnowledgeCore | `draft` | `activate` | 至少一个已验证版本 | `active` | `knowledge.core.activated` |
| KnowledgeCore | `active` | `retire` | 新知识核心替代或归档 | `retired` | `knowledge.core.retired` |
| KnowledgeCoreVersion | `draft` | `verify` | Claim/Evidence 集合完整且无未解决冲突 | `verified` | `knowledge.core_version.verified` |
| KnowledgeCoreVersion | `verified` | `supersede/withdraw` | 新版本生效或事实/权利撤回 | `superseded/withdrawn` | `knowledge.core_version.changed` |
| ContentVariant | `draft` | `activate` | 至少一个批准 VariantVersion 且 current pointer 原子更新 | `active` | `variant.created` |
| ContentVariant | `active` | `withdraw/retire` | 变体撤回或被新根对象替代 | `withdrawn/retired` | `variant.root_changed` |
| Asset | `draft` | `activate` | 至少一个批准 AssetVersion 且 current pointer 原子更新 | `active` | `asset.created` |
| Asset | `active` | `withdraw/retire` | 资产或权利撤回 | `withdrawn/retired` | `asset.root_changed` |
| DistributionTarget | `none` | `create` | Platform、市场、语言、渠道和环境通过唯一性校验 | `active` | `distribution.target.created` |
| DistributionTarget | `active` | `retire` | 有归档原因且没有未处理副作用任务 | `retired` | `distribution.target.retired` |
| DistributionTargetVersion | `none` | `create_draft` | Target 有效、目标/账号/能力字段完整且版本号递增；Policy 快照可在激活前补齐 | `draft` | `distribution.target_version.created` |
| DistributionTargetVersion | `draft` | `activate` | Policy 快照、能力快照和交付模式矩阵完整 | `active` | `distribution.target_version.activated` |
| DistributionTargetVersion | `active` | `retire` | 创建了替代版本或 Target 已退役 | `retired` | `distribution.target_version.retired` |
| RegionProfileVersion | `none` | `create_draft` | 区域字段和规则完整；Policy 快照可在激活前补齐 | `draft` | `region.profile_version.created` |
| RegionProfileVersion | `draft` | `activate` | 复核人批准且有效期、删除 SLA 和数据驻留规则完整 | `active` | `region.profile_version.activated` |
| RegionProfileVersion | `active` | `retire` | 创建替代版本或区域规则失效 | `retired` | `region.profile_version.retired` |
| PolicySnapshot | `none` | `create` | 子策略版本、输入哈希和作用对象完整 | `active` | `policy.snapshot.created` |
| PolicySnapshot | `active` | `expire` | 到达 `expires_at` 或复核期限 | `expired` | `policy.snapshot.expired` |
| PolicySnapshot | `active` | `revoke` | 规则撤回或发现非法输入 | `revoked` | `policy.snapshot.revoked` |
| RightsRecordVersion | `none` | `create` | SourceSnapshot 已登记且权利字段完整 | `pending` | `rights.version.created` |
| RightsRecordVersion | `pending` | `verify` | `source_snapshot_ids` 非空，至少一个许可证/合同/证据引用，`terms_snapshot_hash`、`policy_rule_version`、`verified_by`、`verified_at` 齐全，且范围/期限有效 | `verified` | `rights.version.verified` |
| RightsRecordVersion | `verified` | `expire` | 到达授权结束时间或复核期限；同事务更新父 `RightsRecord.current_version_id` | `expired` | `rights.version.expired` |
| RightsRecordVersion | `verified` | `revoke` | 权利人撤销授权；同事务清空或切换父当前指针 | `revoked` | `rights.version.revoked` |
| RightsRecordVersion | `verified` | `hold_complaint` | 收到版权投诉；冻结所有引用它的派生对象 | `complaint_hold` | `rights.version.complaint_hold` |
| RightsRecord | `pending/verified` | `project_version_state` | 仅由上述 RightsRecordVersion 事件投影；根据是否存在有效 current version 更新父状态和指针 | `verified/expired/revoked/complaint_hold` | 使用原 `rights.version.*` 事件，不产生第二个事实事件 |
| CanonicalContentVersion | `none` | `create` | 存在 `TopicBrief.status=approved` 且请求具备幂等键 | `draft` | `canonical.version.created` |
| CanonicalContentVersion | `draft` | `submit_evidence` | 存在 `TopicBrief.status=approved` 且 Claim 集合已创建 | `evidence_pending` | `canonical.evidence_requested` |
| CanonicalContentVersion | `evidence_pending` | `fact_check` | 所有高优先级 Claim 有有效 Evidence，且无未解决冲突 | `fact_checked` | `canonical.fact_checked` |
| CanonicalContentVersion | `fact_checked` | `approve` | 内容审批人批准 | `approved` | `canonical.version.approved` |
| CanonicalContentVersion | `approved` | `supersede` | 新版本已批准 | `superseded` | `canonical.version.superseded` |
| CanonicalContentVersion | `approved` | `withdraw` | 权利、事实或安全撤回 | `withdrawn` | `canonical.version.withdrawn` |
| VariantVersion | `planned` | `create_draft` | Canonical 版本已批准 | `draft` | `variant.draft_created` |
| VariantVersion | `draft` | `localize` | 有效的 `RegionProfileVersion` 和术语表存在 | `localized` | `variant.localized` |
| VariantVersion | `localized` | `request_qa` | 变体文本和结构完整 | `qa_pending` | `variant.qa_requested` |
| VariantVersion | `qa_pending` | `approve` | 内容审批和区域策略通过 | `approved` | `variant.approved` |
| VariantVersion | `approved` | `withdraw` | Canonical、权利或区域规则撤回 | `withdrawn` | `variant.withdrawn` |
| AssetVersion | `planned` | `render` | Variant 已批准、素材权利有效 | `rendering` | `asset.render_started` |
| AssetVersion | `rendering` | `submit_qa` | 文件完整、哈希已保存 | `qa_pending` | `asset.qa_requested` |
| AssetVersion | `qa_pending` | `approve` | 媒体 QA 和权利检查通过 | `approved` | `asset.approved` |
| AssetVersion | `approved` | `withdraw` | Variant、素材或权利撤回 | `withdrawn` | `asset.withdrawn` |
| AssetVersion | `planned/rendering/qa_pending` | `block` | 权利、策略或安全检查失败 | `blocked` | `asset.blocked` |
| PublicationIntent | `planned` | `prepare` | Variant/Asset 已批准，TargetVersion、RegionProfileVersion 和有效 Policy 快照存在 | `ready` | `publication_intent.ready` |
| PublicationIntent | `ready` | `export` | `manual_export` 模式 | `exported` | `export_package.created` |
| PublicationIntent | `ready` | `simulate` | `simulation` 模式且为 synthetic target | `simulated` | `delivery.simulated` |
| PublicationIntent | `ready` | `queue` | `draft_only` 或 `authorized_api`，连接授权/健康、Policy allow | `queued` | `publication.queued` |
| PublicationIntent | `queued` | `dispatch` | DeliveryAttempt 已创建 | `dispatched` | `publication.dispatched` |
| PublicationIntent | `planned` | `block` | Kill Switch、Policy deny 或权利撤回 | `blocked` | `publication.blocked` |
| PublicationIntent | `ready` | `block` | Kill Switch、Policy deny 或权利撤回 | `blocked` | `publication.blocked` |
| PublicationIntent | `queued` | `block` | 调用前重新计算失败 | `blocked` | `publication.blocked` |
| PublicationIntent | `ready/queued` | `cancel` | 操作者有权限且尚未产生外部副作用 | `cancelled` | `publication.cancelled` |
| DeliveryAttempt | `running` | `complete` | `PublicationRecord` 已在回查后确定为 `published` 或 `failed`，且已保存结果快照 | `succeeded` | `delivery.succeeded` |
| DeliveryAttempt | `created` | `start` | 幂等键未成功过且策略重新通过 | `running` | `delivery.attempted` |
| DeliveryAttempt | `running` | `unknown` | 超时、断网或平台结果无法确认 | `unknown` | `delivery.unknown` |
| DeliveryAttempt | `unknown` | `resolve_unknown` | 人工核查结果与 PublicationRecord 一致并保存证据 | `succeeded` 或 `failed` | `delivery.unknown_resolved` |
| DeliveryAttempt | `failed` | `retry` | `retryable=true`、未超过上限且 Policy 重新通过；创建新的 Attempt | `created`（新记录） | `delivery.retry_scheduled` |
| DeliveryAttempt | `running` | `fail` | 权限/政策/版权或超过重试上限 | `failed` | `delivery.failed` |
| DeliveryAttempt | `failed` | `dead_letter` | `retryable=false` 或已达到 `max_attempts` | `dead_letter` | `delivery.dead_lettered` |
| PublicationRecord | `none` | `record_attempt` | DeliveryAttempt 已创建且保存请求快照 | `attempted` | `publication.recorded` |
| PublicationRecord | `attempted` | `acknowledge` | 已收到平台或 Fake Adapter 回执，保存外部请求/对象快照 | `acknowledged` | `publication.acknowledged` |
| PublicationRecord | `acknowledged` | `confirm_published` | 回查确认平台对象存在 | `published` | `publication.published` |
| PublicationRecord | `acknowledged` | `confirm_failed` | 回查确认失败 | `failed` | `publication.failed` |
| PublicationRecord | `acknowledged` | `mark_unknown` | 无法确认外部结果，创建 `unknown_result` 人工任务 | `unknown` | `publication.unknown` |
| PublicationRecord | `unknown` | `resolve_unknown` | 人工核查并提供 `resolution_evidence_ref`；禁止自动执行副作用 | `published` 或 `failed` | `publication.unknown_resolved` |
| PublicationRecord | `published` | `remove` | 有下架/撤回依据且具备对应能力 | `removed` | `publication.removed` |
| ExportPackage | `available` | `expire` | 到达 `expires_at` | `expired` | `export_package.expired` |
| ExportPackage | `available` | `revoke` | 权利/策略撤回或人工撤回 | `revoked` | `export_package.revoked` |
| Approval | `pending` | `approve` | 目标版本未变、Policy 快照有效、达到 quorum 且审批人不等于创建人 | `approved` | `approval.approved` |
| Approval | `pending` | `reject` | 有拒绝原因 | `rejected` | `approval.rejected` |
| Approval | `pending` | `expire` | 到达审批期限 | `expired` | `approval.expired` |
| Approval | `approved` | `revoke` | 权利、事实、政策或目标快照失效；必须说明原因 | `revoked` | `approval.revoked` |
| HumanTask | `queued` | `claim` | 租约为空或已过期；使用乐观锁 | `claimed` | `human_task.claimed` |
| HumanTask | `queued` | `assign` | 指定责任人且任务仍有效 | `assigned` | `human_task.assigned` |
| HumanTask | `assigned` | `claim` | 租约为空或已过期；使用乐观锁 | `claimed` | `human_task.claimed` |
| HumanTask | `claimed` | `start` | 领取人身份匹配且输入版本未变 | `in_progress` | `human_task.started` |
| HumanTask | `in_progress` | `submit` | 结果、证据和输入版本完整 | `submitted` | `human_task.submitted` |
| HumanTask | `submitted` | `complete` | 审核人确认结果；审批任务满足 quorum | `completed` | `human_task.completed` |
| HumanTask | `claimed/in_progress` | `complete` | 结果和审批证据完整 | `completed` | `human_task.completed` |
| HumanTask | `queued/assigned/claimed/in_progress` | `reject` | 有退回原因 | `rejected` | `human_task.rejected` |
| HumanTask | `queued/assigned/claimed/in_progress` | `expire` | 到达 `due_at` | `expired` | `human_task.expired` |
| HumanTask | `queued/assigned/claimed/in_progress/submitted` | `escalate` | 有升级原因和接收队列 | `escalated` | `human_task.escalated` |
| HumanTask | `queued/assigned/claimed/in_progress/submitted/escalated` | `cancel` | 有取消原因且无不可逆外部副作用 | `cancelled` | `human_task.cancelled` |
| TaskJob | `queued` | `lease` | `available_at` 已到且租约可获得 | `leased` | `task_job.leased` |
| TaskJob | `leased` | `start` | Worker 身份匹配且租约有效 | `running` | `task_job.started` |
| TaskJob | `running` | `succeed` | 输出已持久化 | `succeeded` | `task_job.succeeded` |
| TaskJob | `running` | `fail` | 已分类错误且保存错误快照 | `failed` | `task_job.failed` |
| TaskJob | `failed` | `schedule_retry` | `retryable=true` 且未超过上限 | `retry_scheduled` | `task_job.retry_scheduled` |
| TaskJob | `retry_scheduled` | `enqueue` | `available_at` 已计算且未被取消 | `queued` | `task_job.queued` |
| TaskJob | `failed` | `dead_letter` | 不可重试或达到上限 | `dead_letter` | `task_job.dead_lettered` |
| TaskJob | `queued/leased/running` | `cancel` | 有取消原因且未产生不可逆副作用 | `cancelled` | `task_job.cancelled` |
| OutboxEvent | `pending` | `publish` | 事件信封和 Schema 校验通过 | `publishing` | `outbox.publish_started` |
| OutboxEvent | `publishing` | `ack` | Consumer 已确认且按 event_id 去重 | `published` | `outbox.published` |
| OutboxEvent | `publishing` | `fail` | 保存错误并达到重试判定 | `failed` | `outbox.failed` |
| OutboxEvent | `failed` | `retry` | 未超过上限 | `pending` | `outbox.retry_scheduled` |
| OutboxEvent | `failed` | `dead_letter` | 超过上限或 poison event | `dead_letter` | `outbox.dead_lettered` |
| MetricDefinition | `none` | `create_draft` | 指标键、类型、公式、维度、数据源和去重规则完整 | `draft` | `metric.definition.created` |
| MetricDefinition | `draft` | `activate` | 类型、公式、维度、数据源和去重规则完整 | `active` | `metric.definition.activated` |
| MetricDefinition | `active` | `retire` | 创建替代版本 | `retired` | `metric.definition.retired` |
| ApprovalDecision | `none` | `record` | reviewer 有审批权限、不是创建人，输入/Policy 快照未变 | `recorded`（不可变） | `approval.decision_recorded` |
| FeedbackItem | `proposed` | `approve` | 推荐理由、Observation 和责任人完整 | `approved` | `feedback.approved` |
| FeedbackItem | `proposed` | `reject` | 有拒绝原因 | `rejected` | `feedback.rejected` |
| FeedbackItem | `proposed` | `expire` | 到达 `expires_at` | `expired` | `feedback.expired` |
| FeedbackItem | `approved` | `mark_executed` | 关联 `FeedbackAction.status=executed` | `executed` | `feedback.executed` |
| FeedbackAction | `proposed` | `approve` | 目标版本仍有效且审批人有权限 | `approved` | `feedback.action_approved` |
| FeedbackAction | `proposed/approved` | `cancel` | 有取消原因且未产生外部副作用 | `cancelled` | `feedback.action_cancelled` |
| FeedbackAction | `approved` | `start` | 预算、Policy 和目标版本检查通过 | `executing` | `feedback.action_started` |
| FeedbackAction | `executing` | `complete` | 结果快照已保存 | `executed` | `feedback.action_executed` |
| FeedbackAction | `executing` | `fail` | 保存失败原因和补偿建议 | `failed` | `feedback.action_failed` |
| SitePageVersion | `draft` | `ready` | Canonical、区域版本、结构化数据和可抓取性检查通过 | `ready` | `site.page_version.ready` |
| SitePageVersion | `ready` | `publish` | 发布审批通过且构建产物哈希已保存 | `published` | `site.page_version.published` |
| SitePageVersion | `published` | `supersede` | 新版本已发布 | `superseded` | `site.page_version.superseded` |
| SitePageVersion | `published` | `rollback` | 有回滚原因且目标版本可用 | `rolled_back` | `site.page_version.rolled_back` |
| GeoQueryFixture | `created` | `activate` | 查询、区域和预期结果完整 | `active` | `geo.fixture.activated` |
| GeoQueryFixture | `active` | `retire` | 新 Fixture 已替代或规则失效 | `retired` | `geo.fixture.retired` |
| WebhookReceipt | `received` | `dedupe` | 外部事件 ID/签名校验完成 | `deduplicated` | `webhook.deduplicated` |
| WebhookReceipt | `deduplicated` | `process` | 对应平台事件 Schema 校验通过 | `processed` | `webhook.processed` |
| WebhookReceipt | `received/deduplicated` | `reject` | 签名或 Schema 无效 | `rejected` | `webhook.rejected` |
| WebhookReceipt | `deduplicated` | `dead_letter` | 多次处理失败或 poison event | `dead_letter` | `webhook.dead_lettered` |
| DeletionRequest | `requested` | `queue` | 删除范围和保留例外已确认 | `queued` | `deletion.queued` |
| DeletionRequest | `queued` | `start` | 删除 Worker 获得租约 | `running` | `deletion.started` |
| DeletionRequest | `running` | `complete` | 所有存储/索引目标均有确认 | `completed` | `deletion.completed` |
| DeletionRequest | `running` | `partial` | 部分目标失败并创建人工任务 | `partially_completed` | `deletion.partially_completed` |
| DeletionRequest | `running` | `fail` | 无法继续且保存失败证据 | `failed` | `deletion.failed` |
| KillSwitch | `active` | `pause` | 有原因、操作者和范围 | `paused` | `kill_switch.paused` |
| KillSwitch | `paused` | `resume` | 恢复条件满足并重新评估 Policy | `active` | `kill_switch.resumed` |
| AccountConnection | `unavailable` | `request` | 外部主体和授权联系人已登记 | `pending` | `account.connection_changed` |
| AccountConnection | `pending` | `connect` | OAuth 回调、Scope 和授权证据通过 | `connected` | `account.connection_changed` |
| AccountConnection | `connected` | `revoke` | 授权撤销或凭证失效 | `revoked` | `account.connection_changed` |
| AccountConnection | `expired/revoked` | `reauthorize` | 新 OAuth 授权和证据通过 | `authorized`（authorization_status） | `account.connection_changed` |
| AccountConnection | `degraded/restricted` | `recover` | 健康检查连续通过且无 Kill Switch | `healthy`（health_status） | `account.connection_changed` |

`unknown` 只表示外部结果无法确认，必须进入人工核查；在核查前不得再次执行可能产生副作用的发布。

`RightsRecord` 的父状态和 `current_version_id` 是 `RightsRecordVersion` 状态转换的同步投影，不另起一套人工可写状态机：`rights.version.verified/expired/revoked/complaint_hold` 事件在同一事务中更新父记录；如果没有其他有效版本则置为相应失效状态并清空指针，有有效版本时只切换到最新合规版本。

发布执行顺序固定为：

```text
PublicationIntent.ready
→ DeliveryAttempt.created
→ DeliveryAttempt.running
→ PublicationRecord.attempted
→ adapter acknowledged
→ requery（Webhook 或轮询）
→ PublicationRecord.published|failed|unknown
```

`PublicationIntent` 是编排状态，`dispatched` 只表示请求已交给适配器，不代表成功；最终业务结果唯一以 `PublicationRecord` 为准。`simulation` 必须创建完整 `DeliveryAttempt` 和 `PublicationRecord`；`manual_export` 只生成私有 `ExportPackage`（可以记录无副作用的导出尝试），不能把导出成功当作平台发布成功。`PublicationRecord.unknown` 只能通过 `resolve_unknown` 命令转为 `published` 或 `failed`，并同步更新对应 Attempt/Intent，核查前禁止自动副作用重试。

表中的状态拥有者是对象所属模块；API 层不能绕过模块用例直接修改状态。每次转换都要保存操作者、规则版本、输入版本、时间和事件 ID。

`PublicationIntent.dispatched` 只表示交付请求已送入对应适配器；是否真的创建草稿或发布成功，以 `PublicationRecord` 的回查结果为准。`exported` 表示导出包已经生成，`simulated` 表示 Fake Adapter 已完成模拟，不代表真实平台发布。Intent 不复制 Record 的成功/失败/unknown 终态，避免双写漂移；需要查询结果时通过 `publication_records` 投影。

### 4.6 最小字段契约

下面是 Codex 实现 M1 时必须保留的字段；可以增加字段，但不能删除或改名而不更新契约：

```json
{
  "TopicSignal": {
    "id": "uuid",
    "org_id": "uuid",
    "source_type": "manual|search|site|support|product|competitor",
    "source_ref": "string",
    "captured_at": "datetime",
    "locale": "locale-catalog-ref",
    "region": "region-catalog-ref",
    "usage_rights_status": "unknown|permitted|restricted|denied",
    "terms_snapshot_ref": "string|null",
    "license_ref": "string|null",
    "permitted_use": "topic_only|research|derivative|commercial|null",
    "confidence": 0.0,
    "normalized_question": "string",
    "snapshot_hash": "sha256"
  },
  "TopicOpportunity": {
    "id": "uuid",
    "org_id": "uuid",
    "signal_ids": ["uuid"],
    "topic_key": "string",
    "title": "string",
    "question": "string",
    "score_snapshot_id": "uuid|null",
    "score_snapshot_hash": "sha256|null",
    "owner_actor_id": "uuid|null",
    "priority": "low|normal|high|urgent",
    "due_at": "datetime|null",
    "editorial_plan_id": "uuid|null",
    "risk_level": "R0|R1|R2|R3|R4",
    "status": "captured|scored|approved|rejected|briefed|in_production|monitoring|refresh|retired"
  },
  "TopicBrief": {
    "id": "uuid",
    "org_id": "uuid",
    "opportunity_id": "uuid",
    "status": "draft|approved|rejected|deferred|superseded",
    "version_no": 1,
    "audience": "string",
    "problem": "string",
    "claim_specs": [
      {
        "claim_key": "string",
        "statement": "string",
        "priority": "low|normal|high",
        "evidence_plan_refs": ["string"]
      }
    ],
    "claim_ids": [],
    "evidence_plan": ["string"],
    "original_angle": "string",
    "locales": ["locale-catalog-ref"],
    "markets": ["market-catalog-ref"],
    "expected_channels": ["article"],
    "approved_by": "uuid|null",
    "approved_at": "datetime|null",
    "locked_at": "datetime|null",
    "locked_by": "uuid|null",
    "lock_hash": "sha256|null",
    "input_snapshot_hash": "sha256",
    "deferred_reason": "string|null"
  },
  "TopicScoreSnapshot": {
    "id": "uuid",
    "org_id": "uuid",
    "opportunity_id": "uuid",
    "formula_version": "string",
    "signal_inputs": {},
    "score_components": {},
    "total_score": 0.0,
    "reasoning": "string",
    "created_at": "datetime"
  },
  "CanonicalContent": {
    "id": "uuid",
    "org_id": "uuid",
    "topic_brief_id": "uuid",
    "stable_key": "string",
    "current_version_id": "uuid|null",
    "status": "draft|in_review|approved|archived",
    "created_by": "uuid",
    "created_at": "datetime",
    "updated_at": "datetime"
  },
  "CanonicalContentVersion": {
    "id": "uuid",
    "org_id": "uuid",
    "canonical_content_id": "uuid",
    "topic_brief_id": "uuid",
    "version_no": 1,
    "topic_brief_status": "locked|approved",
    "topic_brief_lock_hash": "sha256|null",
    "title": "string",
    "abstract": "string",
    "sections": [{"key": "stable-string", "position": 1, "content": {}}],
    "claims": [{"key": "stable-string", "position": 1, "claim_id": "uuid|null", "priority": "low|normal|high|urgent", "evidence_ids": ["uuid"], "rights_snapshot_ids": ["uuid"], "content": {}}],
    "code_blocks": [{"key": "stable-string", "position": 1, "content": {}}],
    "examples": [{"key": "stable-string", "position": 1, "content": {}}],
    "limitations": [{"key": "stable-string", "position": 1, "content": {}}],
    "source_snapshot_refs": ["uuid"],
    "knowledge_core_version": "uuid|null",
    "knowledge_core_version_id": "uuid|null",
    "input_snapshot_hash": "sha256",
    "content_hash": "sha256",
    "rights_snapshot_ids": ["uuid"],
    "supersedes_version_id": "uuid|null",
    "status": "draft|evidence_pending|fact_checked|approved|superseded|withdrawn",
    "created_by": "uuid",
    "created_at": "datetime"
  },
  "VariantVersion": {
    "id": "uuid",
    "org_id": "uuid",
    "content_variant_id": "uuid",
    "canonical_content_version_id": "uuid",
    "version_no": 1,
    "locale": "en-US",
    "market": "US",
    "audience": "developer",
    "tone": "string",
    "region_profile_version_id": "uuid",
    "source_variant_version_id": "uuid|null",
    "body": {
      "blocks": [
        {
          "block_id": "same-as-canonical-or-new",
          "localized_text": "string",
          "term_refs": ["term-id"],
           "disclosure": "string|null"
        }
      ]
    },
    "term_memory_version": "string",
    "disclosure": "string|null",
    "policy_snapshot_id": "uuid",
    "status": "planned|draft|localized|qa_pending|approved|withdrawn",
    "snapshot_hash": "sha256",
    "created_by": "uuid",
    "created_at": "datetime"
  },
  "ContentVariant": {
    "id": "uuid",
    "org_id": "uuid",
    "canonical_content_id": "uuid",
    "locale": "en-US",
    "market": "US",
    "audience": "developer",
    "current_version_id": "uuid|null",
    "status": "draft|active|withdrawn|retired"
  },
  "Asset": {
    "id": "uuid",
    "org_id": "uuid",
    "variant_id": "uuid",
    "current_version_id": "uuid|null",
    "status": "draft|active|withdrawn|retired"
  },
  "AssetVersion": {
    "id": "uuid",
    "org_id": "uuid",
    "asset_id": "uuid",
    "variant_version_id": "uuid",
    "version_no": 1,
    "media_type": "image|audio|video|subtitle|document|thumbnail",
    "format": "string",
    "aspect_ratio": "9:16|1:1|16:9|other|null",
    "storage_object_ref": "private-object-ref|null",
    "file_hash": "sha256|null",
    "rights_snapshot_ids": ["uuid"],
    "region_profile_version_id": "uuid",
    "policy_snapshot_id": "uuid|null",
    "status": "planned|rendering|qa_pending|approved|withdrawn|blocked",
    "created_by": "uuid",
    "created_at": "datetime"
  },
  "PublicationIntent": {
    "id": "uuid",
    "org_id": "uuid",
    "variant_version_id": "uuid",
    "asset_version_ids": ["uuid"],
    "distribution_target_version_id": "uuid",
    "delivery_mode": "manual_export|simulation|draft_only|authorized_api",
    "region_profile_version_id": "uuid",
    "payload_snapshot": {
      "title": "string",
      "body": {},
      "tags": ["string"],
      "disclosure": "string|null"
    },
    "payload_snapshot_hash": "sha256",
    "scheduled_at": "datetime|null",
    "policy_snapshot_id": "uuid|null",
    "capability_snapshot_hash": "sha256",
    "intent_key": "string",
    "derived_from_intent_id": "uuid|null",
    "status": "planned|ready|exported|simulated|queued|dispatched|blocked|cancelled",
    "created_by": "uuid",
    "created_at": "datetime",
    "updated_at": "datetime",
    "resolved_at": "datetime|null"
  },
  "DeliveryAttempt": {
    "id": "uuid",
    "org_id": "uuid",
    "publication_intent_id": "uuid",
    "account_connection_id": "uuid|null",
    "adapter_ref": "manual:export|fake:official@<version>|platform:<id>@<version>",
    "provider_mode": "manual|fake|sandbox|authorized",
    "environment": "dev|staging|prod",
    "policy_snapshot_id": "uuid",
    "execution_policy_decision_id": "uuid",
    "adapter_version": "string|null",
    "capability_snapshot": {},
    "idempotency_key": "string",
    "provider_idempotency_key": "string",
    "attempt_no": 1,
    "parent_attempt_id": "uuid|null",
    "status": "created|running|succeeded|failed|unknown|dead_letter",
    "retryable": false,
    "next_attempt_at": "datetime|null",
    "max_attempts": 3,
    "started_at": "datetime|null",
    "completed_at": "datetime|null",
    "external_request_id": "string|null",
    "external_object_id": "string|null",
    "account_connection_snapshot": {},
    "error_class": "string|null",
    "last_error_code": "string|null",
    "last_error_at": "datetime|null",
    "resolution_reason": "string|null",
    "resolved_by": "uuid|null",
    "resolved_at": "datetime|null",
    "created_at": "datetime"
  },
  "ExportPackage": {
    "id": "uuid",
    "org_id": "uuid",
    "publication_intent_id": "uuid",
    "storage_object_ref": "private-object-ref",
    "package_hash": "sha256",
    "content_version_refs": ["uuid"],
    "approval_refs": ["uuid"],
    "expires_at": "datetime",
    "revoked_at": "datetime|null",
    "download_count": 0,
    "status": "available|expired|revoked"
  },
  "PublicationRecord": {
    "id": "uuid",
    "org_id": "uuid",
    "publication_intent_id": "uuid",
    "delivery_attempt_id": "uuid",
    "provider_mode": "manual|fake|sandbox|authorized",
    "external_request_id": "string|null",
    "external_object_id": "string|null",
    "external_url": "string|null",
    "status": "attempted|acknowledged|published|failed|unknown|removed",
    "result_snapshot": {},
    "observed_at": "datetime",
    "last_observed_at": "datetime",
    "observation_source": "adapter|webhook|poll|manual",
    "unknown_reason": "string|null",
    "resolution_reason": "string|null",
    "resolved_by": "uuid|null",
    "resolved_at": "datetime|null",
    "resolution_evidence_ref": "string|null"
  },
  "Observation": {
    "id": "uuid",
    "org_id": "uuid",
    "source": "site|fake|manual|platform|geo|support|qa",
    "subject_type": "publication|content|variant|asset|topic|page|geo_run",
    "subject_id": "uuid",
    "metric_definition_id": "uuid",
    "metric_definition_version_no": 1,
    "metric_name": "string",
    "metric_type": "number|boolean|string|enum|json",
    "metric_value": 0,
    "observed_at": "datetime",
    "locale": "string|null",
    "region": "string|null",
    "data_quality": "raw|validated|estimated",
    "dedupe_key": "string",
    "source_snapshot_ref": "string|null",
    "observation_version": 1
  },
  "FeedbackItem": {
    "id": "uuid",
    "org_id": "uuid",
    "observation_ids": ["uuid"],
    "problem": "string",
    "recommendation_type": "refresh|revise|retire|reprioritize|channel_change|prompt_eval",
    "impact": "low|medium|high",
    "priority": "low|medium|high|urgent",
    "confidence": 0.0,
    "reasoning_snapshot": {},
    "owner_actor_id": "uuid|null",
    "due_at": "datetime|null",
    "approver_id": "uuid|null",
    "expires_at": "datetime|null",
    "created_action_id": "uuid|null",
    "status": "proposed|approved|rejected|executed|expired",
    "created_at": "datetime"
  },
  "Source": {
    "id": "uuid",
    "org_id": "uuid",
    "source_type": "url|file|api|manual|support",
    "canonical_url": "string|null",
    "status": "none|ingested|quarantined|usable|expired|revoked|blocked",
    "current_snapshot_id": "uuid|null",
    "created_at": "datetime"
  },
  "SourceSnapshot": {
    "id": "uuid",
    "org_id": "uuid",
    "source_id": "uuid",
    "captured_at": "datetime",
    "content_hash": "sha256",
    "storage_object_ref": "private-object-ref",
    "terms_snapshot_ref": "string|null",
    "status": "captured|quarantined|usable|expired|revoked|blocked",
    "created_at": "datetime"
  },
  "Entity": {
    "id": "uuid",
    "org_id": "uuid",
    "canonical_name": "string",
    "aliases": ["string"],
    "entity_type": "string",
    "status": "draft|active|retired",
    "version": 0,
    "content_hash": "sha256",
    "created_by": "uuid",
    "created_at": "datetime",
    "updated_at": "datetime"
  },
  "Claim": {
    "id": "uuid",
    "org_id": "uuid",
    "entity_ids": ["uuid"],
    "statement": "string",
    "fact_type": "string",
    "applicable_versions": ["string"],
    "applicable_regions": ["string"],
    "applicable_locales": ["string"],
    "valid_from": "datetime|null",
    "valid_to": "datetime|null",
    "review_due_at": "datetime|null",
    "supersedes_claim_id": "uuid|null",
    "freshness_status": "fresh|review_due|stale|withdrawn",
    "status": "draft|verified|withdrawn",
    "version": 0,
    "content_hash": "sha256",
    "created_by": "uuid",
    "created_at": "datetime",
    "updated_at": "datetime"
  },
  "Evidence": {
    "id": "uuid",
    "org_id": "uuid",
    "source_snapshot_id": "uuid",
    "claim_id": "uuid|null",
    "rights_record_version_id": "uuid|null",
    "evidence_type": "string",
    "quote": "string",
    "locator": "string|null",
    "applicable_versions": ["string"],
    "applicable_regions": ["string"],
    "applicable_locales": ["string"],
    "valid_from": "datetime|null",
    "valid_to": "datetime|null",
    "review_due_at": "datetime|null",
    "captured_at": "datetime",
    "status": "captured|valid|expired|revoked",
    "version": 0,
    "content_hash": "sha256",
    "created_by": "uuid",
    "created_at": "datetime"
  },
  "KnowledgeCore": {
    "id": "uuid",
    "org_id": "uuid",
    "topic_brief_id": "uuid|null",
    "current_version_id": "uuid|null",
    "status": "draft|validated|stale|archived",
    "needs_review": "boolean",
    "created_by": "uuid",
    "created_at": "datetime",
    "updated_at": "datetime"
  },
  "KnowledgeCoreVersion": {
    "id": "uuid",
    "org_id": "uuid",
    "knowledge_core_id": "uuid",
    "topic_brief_id": "uuid|null",
    "version_no": 1,
    "entity_ids": ["uuid"],
    "claim_ids": ["uuid"],
    "evidence_ids": ["uuid"],
    "conflict_set_ids": ["uuid"],
    "freshness_checked_at": "datetime|null",
    "snapshot_hash": "sha256",
    "content_hash": "sha256",
    "status": "draft|verified|superseded|withdrawn|needs_review",
    "supersedes_version_id": "uuid|null",
    "created_by": "uuid",
    "created_at": "datetime"
  },
  "Platform": {
    "id": "uuid",
    "key": "string",
    "display_name": "string",
    "kind": "site|official|fake|inbox",
    "status": "active|disabled",
    "policy_ref": "string|null",
    "adapter_key": "string|null"
  },
  "RightsRecord": {
    "id": "uuid",
    "org_id": "uuid",
    "source_id": "uuid",
    "current_version_id": "uuid|null",
    "status": "pending|verified|expired|revoked|complaint_hold",
    "created_at": "datetime",
    "updated_at": "datetime"
  },
  "RightsRecordVersion": {
    "id": "uuid",
    "org_id": "uuid",
    "rights_record_id": "uuid",
    "version_no": 1,
    "source_snapshot_ids": ["uuid"],
    "license_ref": "string|null",
    "contract_ref": "string|null",
    "evidence_object_refs": ["string"],
    "terms_snapshot_hash": "sha256|null",
    "rights_holder": "string",
    "permitted_regions": [],
    "permitted_locales": [],
    "permitted_media": [],
    "permitted_use": "research|derivative|commercial",
    "valid_from": "datetime|null",
    "valid_to": "datetime|null",
    "status": "pending|verified|expired|revoked|complaint_hold",
    "policy_rule_version": "string",
    "verified_by": "uuid|null",
    "verified_at": "datetime|null",
    "verification_reason": "string|null",
    "supersedes_version_id": "uuid|null",
    "snapshot_hash": "sha256",
    "created_by": "uuid",
    "created_at": "datetime"
  },
  "DistributionTarget": {
    "id": "uuid",
    "org_id": "uuid",
    "platform_id": "uuid",
    "market": "US",
    "locale": "en-US",
    "channel": "article|short_post|video",
    "environment": "dev|staging|prod",
    "status": "active|retired",
    "created_by": "uuid",
    "created_at": "datetime",
    "retired_at": "datetime|null"
  },
  "DistributionTargetVersion": {
    "id": "uuid",
    "org_id": "uuid",
    "distribution_target_id": "uuid",
    "version_no": 1,
    "platform_id": "uuid",
    "market": "US",
    "locale": "en-US",
    "channel": "article|short_post|video",
    "environment": "dev|staging|prod",
    "region_profile_version_id": "uuid",
    "account_profile_id": "uuid|null",
    "account_profile_snapshot": {},
    "account_connection_id": "uuid|null",
    "account_connection_snapshot": {},
    "synthetic_target_id": "string|null",
    "capability_snapshot": {},
    "policy_snapshot_id": "uuid|null",
    "eligible_delivery_modes": ["manual_export", "simulation"],
    "status": "draft|active|retired",
    "snapshot_hash": "sha256",
    "etag": "string",
    "created_by": "uuid",
    "created_at": "datetime",
    "retired_at": "datetime|null"
  },
  "AccountProfile": {
    "id": "uuid",
    "org_id": "uuid",
    "legal_name": "string",
    "brand_name": "string",
    "owner_actor_id": "uuid|null",
    "profile_kind": "planned|synthetic|real",
    "markets": ["market-catalog-ref"],
    "status": "planned|active|restricted|retired"
  },
  "AuthorizationEvidence": {
    "id": "uuid",
    "org_id": "uuid",
    "account_connection_id": "uuid",
    "evidence_type": "oauth_consent|sandbox_membership|owner_confirmation|policy_acceptance",
    "external_reference": "string|null",
    "scope_snapshot": {},
    "captured_at": "datetime",
    "valid_until": "datetime|null",
    "status": "pending|verified|expired|revoked"
  },
  "PolicyDecision": {
    "id": "uuid",
    "org_id": "uuid",
    "subject_type": "string",
    "subject_id": "uuid",
    "content_policy": "allow|deny|manual_review",
    "region_policy": "allow|deny|manual_review",
    "distribution_policy": "allow|deny|manual_review",
    "account_policy": "allow|deny|unknown|manual_review",
    "data_processing_policy": "allow|deny|manual_review",
    "model_policy": "allow|deny|manual_review",
    "final_decision": "allow|deny|manual_review",
    "reasons": ["string"],
    "policy_snapshot_id": "uuid",
    "decision_hash": "sha256",
    "decision_version": 1,
    "evaluated_at": "datetime",
    "expires_at": "datetime|null",
    "created_at": "datetime"
  },
  "AccountConnection": {
    "id": "uuid",
    "org_id": "uuid",
    "account_profile_id": "uuid",
    "platform_id": "uuid",
    "external_account_id": "string",
    "environment": "sandbox|prod",
    "connection_status": "unavailable|pending|connected|revoked",
    "authorization_status": "unknown|authorized|expired|revoked",
    "health_status": "unknown|healthy|degraded|restricted",
    "scope_snapshot": {},
    "secret_reference": "vault-ref|null",
    "token_lease_id": "uuid|null",
    "token_version": 1,
    "token_expires_at": "datetime|null",
    "last_health_check_at": "datetime|null",
    "last_refresh_error": "string|null",
    "revoked_at": "datetime|null",
    "revocation_reason": "string|null",
    "created_at": "datetime",
    "updated_at": "datetime"
  },
  "RegionProfile": {
    "id": "uuid",
    "org_id": "uuid",
    "region_code": "US",
    "current_version_id": "uuid|null",
    "status": "active|retired",
    "created_at": "datetime"
  },
  "RegionProfileVersion": {
    "id": "uuid",
    "org_id": "uuid",
    "region_profile_id": "uuid",
    "version_no": 1,
    "region_code": "US",
    "locales": ["en-US"],
    "timezone": "America/New_York",
    "date_number_format": "string",
    "units": "metric|imperial|mixed",
    "currency": "USD",
    "terminology_version": "string",
    "disclosure_rules": [],
    "restricted_topics": [],
    "data_residency": "string",
    "retention_days": 365,
    "deletion_sla_hours": 72,
    "platform_eligibility": [],
    "policy_snapshot_id": "uuid|null",
    "valid_from": "datetime|null",
    "valid_to": "datetime|null",
    "review_due_at": "datetime|null",
    "status": "draft|active|retired",
    "snapshot_hash": "sha256",
    "created_by": "uuid",
    "created_at": "datetime"
  },
  "PolicySnapshot": {
    "id": "uuid",
    "org_id": "uuid|null",
    "subject_type": "variant|asset|target_version|publication_intent|account|region",
    "subject_id": "uuid|null",
    "subject_ref": "string",
    "content_policy_version": "string",
    "region_policy_version": "string",
    "distribution_policy_version": "string",
    "account_policy_version": "string|null",
    "data_processing_policy_version": "string",
    "model_policy_version": "string",
    "policy_version_refs": ["uuid"],
    "precedence": ["content", "region", "data_processing", "model", "distribution", "account"],
    "input_hash": "sha256",
    "rules_hash": "sha256",
    "snapshot_hash": "sha256",
    "supersedes_snapshot_id": "uuid|null",
    "evaluated_at": "datetime",
    "effective_at": "datetime",
    "expires_at": "datetime|null",
    "review_due_at": "datetime|null",
    "status": "active|expired|revoked",
    "created_by": "uuid"
  },
  "MetricDefinition": {
    "id": "uuid",
    "org_id": "uuid|null",
    "key": "string",
    "version_no": 1,
    "metric_type": "number|boolean|string|enum|json",
    "unit": "string",
    "formula": "string",
    "dimensions": ["string"],
    "window": "string",
    "data_source": "string",
    "dedupe_rule": "string",
    "quality_rules": {},
    "owner_actor_id": "uuid|null",
    "status": "draft|active|retired",
    "effective_at": "datetime|null",
    "retired_at": "datetime|null",
    "snapshot_hash": "sha256"
  },
  "Approval": {
    "id": "uuid",
    "org_id": "uuid",
    "aggregate_type": "canonical|variant|asset|publication_intent|rights_version",
    "aggregate_id": "uuid",
    "aggregate_version": 1,
    "approval_type": "content|asset|distribution|rights",
    "status": "pending|approved|rejected|expired|revoked",
    "requested_by": "uuid",
    "reviewer_id": "uuid|null",
    "decision": "approved|rejected|withdrawn|null",
    "policy_snapshot_id": "uuid",
    "evidence_refs": ["uuid"],
    "input_snapshot_hash": "sha256",
    "quorum_required": 1,
    "quorum_reached": 0,
    "decision_ids": [],
    "reason": "string|null",
    "expires_at": "datetime|null",
    "created_at": "datetime",
    "decided_at": "datetime|null"
  },
  "ApprovalDecision": {
    "id": "uuid",
    "org_id": "uuid",
    "approval_id": "uuid",
    "reviewer_id": "uuid",
    "decision": "approved|rejected|withdrawn",
    "reason": "string|null",
    "input_snapshot_hash": "sha256",
    "policy_snapshot_id": "uuid",
    "created_at": "datetime"
  },
  "HumanTask": {
    "id": "uuid",
    "org_id": "uuid",
    "task_type": "approval|rights_review|policy_review|unknown_result|support_escalation",
    "aggregate_type": "string",
    "aggregate_id": "uuid",
    "input_version": 1,
    "workflow_run_id": "uuid|null",
    "approval_id": "uuid|null",
    "status": "queued|assigned|claimed|in_progress|submitted|completed|escalated|rejected|expired|cancelled",
    "assigned_to": "uuid|null",
    "claim_lease_until": "datetime|null",
    "priority": "low|normal|high|urgent",
    "sla_policy_id": "uuid|null",
    "due_at": "datetime|null",
    "input_snapshot": {},
    "result": {},
    "completed_by": "uuid|null",
    "override_expires_at": "datetime|null",
    "created_at": "datetime",
    "completed_at": "datetime|null"
  },
  "FeedbackAction": {
    "id": "uuid",
    "org_id": "uuid",
    "feedback_item_id": "uuid",
    "action_type": "refresh|revise|retire|reprioritize|channel_change|prompt_eval",
    "target_type": "topic_opportunity|canonical_content|variant|prompt",
    "target_id": "uuid",
    "target_version": 1,
    "status": "proposed|approved|executing|executed|failed|cancelled",
    "approved_by": "uuid|null",
    "approved_at": "datetime|null",
    "executed_at": "datetime|null",
    "result_snapshot": {},
    "created_at": "datetime"
  },
  "TaskJob": {
    "id": "uuid",
    "org_id": "uuid",
    "job_type": "string",
    "queue_name": "string",
    "aggregate_type": "string",
    "aggregate_id": "uuid",
    "aggregate_version": 1,
    "payload_ref": "private-object-ref",
    "status": "queued|leased|running|succeeded|failed|retry_scheduled|dead_letter|cancelled",
    "attempt_count": 0,
    "max_attempts": 3,
    "available_at": "datetime",
    "lease_until": "datetime|null",
    "locked_by": "string|null",
    "last_error": "string|null",
    "replayed_from_job_id": "uuid|null",
    "replayed_from_attempt_count": "integer|null",
    "replay_reason": "string|null",
    "idempotency_key": "string",
    "trace_id": "string",
    "created_at": "datetime",
    "updated_at": "datetime"
  },
  "OutboxEvent": {
    "event_id": "uuid",
    "event_type": "string",
    "event_schema_version": 1,
    "occurred_at": "datetime",
    "org_id": "uuid",
    "trace_id": "string",
    "correlation_id": "string|null",
    "causation_id": "string|null",
    "aggregate_type": "string",
    "aggregate_id": "uuid",
    "aggregate_version": 1,
    "actor_type": "user|service|system|worker",
    "actor_id": "uuid|null",
    "idempotency_key": "string",
    "payload": {},
    "payload_hash": "sha256",
    "published_at": "datetime|null",
    "attempt_count": 0,
    "last_error": "string|null",
    "status": "pending|publishing|published|failed|dead_letter",
    "available_at": "datetime",
    "lease_until": "datetime|null",
    "locked_by": "string|null"
  },
  "TaskFailure": {
    "id": "uuid",
    "org_id": "uuid",
    "job_id": "uuid",
    "attempt_count": "integer",
    "error_class": "deterministic|transient|unknown",
    "error_code": "string",
    "message_redacted": "string|null",
    "retryable": "boolean",
    "trace_id": "string",
    "occurred_at": "datetime"
  },
  "SitePageVersion": {
    "id": "uuid",
    "org_id": "uuid",
    "site_page_id": "uuid",
    "version_no": 1,
    "canonical_content_version_id": "uuid",
    "locale": "locale-catalog-ref",
    "region_profile_version_id": "uuid",
    "url_path": "string",
    "render_mode": "ssr|static",
    "status": "draft|ready|published|superseded|rolled_back",
    "snapshot_hash": "sha256",
    "published_at": "datetime|null",
    "created_at": "datetime"
  },
  "GeoQueryFixture": {
    "id": "uuid",
    "org_id": "uuid",
    "query": "string",
    "locale": "locale-catalog-ref",
    "region": "region-catalog-ref",
    "expected_entities": ["string"],
    "expected_claim_ids": ["uuid"],
    "status": "created|active|retired",
    "fixture_hash": "sha256",
    "created_at": "datetime"
  },
  "GeoRun": {
    "id": "uuid",
    "org_id": "uuid",
    "page_version_id": "uuid",
    "query_fixture_id": "uuid",
    "locale": "locale-catalog-ref",
    "region": "region-catalog-ref",
    "sample_count": 1,
    "parser_version": "string",
    "mention_count": 0,
    "citation_count": 0,
    "position_values": [],
    "correctness_values": [],
    "confidence": 0.0,
    "data_quality": "estimated|validated",
    "fixture_hash": "sha256",
    "status": "planned|running|succeeded|failed",
    "created_at": "datetime"
  },
  "WebhookReceipt": {
    "id": "uuid",
    "org_id": "uuid",
    "platform_id": "uuid",
    "external_event_id": "string",
    "signature_valid": true,
    "payload_hash": "sha256",
    "raw_payload_ref": "private-object-ref",
    "dedupe_key": "string",
    "status": "received|deduplicated|processed|rejected|dead_letter",
    "processing_attempts": 0,
    "last_error": "string|null",
    "replay_count": 0,
    "received_at": "datetime",
    "processed_at": "datetime|null",
    "rejected_at": "datetime|null"
  },
  "DeletionRequest": {
    "id": "uuid",
    "org_id": "uuid",
    "subject_type": "string",
    "subject_id": "uuid",
    "requested_by": "uuid",
    "status": "requested|queued|running|completed|failed|partially_completed",
    "requested_at": "datetime",
    "completed_at": "datetime|null"
  },
  "KillSwitch": {
    "id": "uuid",
    "org_id": "uuid|null",
    "scope": "global|platform|account|target|content",
    "scope_id": "uuid|null",
    "status": "active|paused",
    "reason": "string",
    "changed_by": "uuid",
    "changed_at": "datetime"
  }
}
```

上面的 JSON 是可读字段目录，不是可直接运行的 Schema。实现时必须为每个 M1-P0 对象在 `packages/contracts/jsonschema/` 生成独立文件，并至少包含 `$schema`、`$id`、`type`、`required`、`additionalProperties: false`、状态枚举、`oneOf` 跨字段约束、`metric_value` 类型分支和租户字段规则。每个文件都要在 `docs/task-registry.yaml` 以 `contract_ref` 登记，并由 CI 解析校验。

`CanonicalContentVersion.rights_snapshot_ids` 中的每个 ID 都必须引用 `rights_record_versions.id`，以便在许可证变更后仍能复现当时的全部权利依据；Claim 与权利版本的精确对应关系通过 `canonical_claims` 保存。`DistributionTarget` 不保存 `account_profile_id`、`account_connection_id` 或可变能力；这些字段只能出现在不可变的 `DistributionTargetVersion` 中。`PublicationIntent` 只保存 `distribution_target_version_id`。`account_connection_id` 只有在 `draft_only` 或 `authorized_api` 的 `DistributionTargetVersion` 中才允许非空；M1 的 `manual_export` 和 `simulation` 必须为空。平台注册表使用声明性的 `adapter_key`，实际执行的版本化实现只记录在 `DeliveryAttempt.adapter_ref`（例如 `manual:export`、`fake:official@v1` 或 `platform:<id>@<version>`）。synthetic target 通过 `DistributionTargetVersion.synthetic_target_id` 标识，不伪造真实连接。

`DistributionTargetVersion.account_profile_snapshot` 和 `account_connection_snapshot` 只能保存审计所需的脱敏字段（例如主体名称、外部账号 ID、Scope 哈希、授权/健康状态和检查时间），不得保存 Token、Secret Manager 值或原始授权码；快照哈希必须覆盖所有目标、账号、能力和政策字段。

为避免 `PolicySnapshot.subject_id` 与业务对象互相等待，创建顺序固定为：先创建 `draft/planned` 对象（此时 `policy_snapshot_id` 可为空），再以对象输入快照计算 `PolicySnapshot`，最后在同一事务把快照 ID 写入并激活/准备对象。进入 `ready`、`active`、`queued` 或任何副作用模式前，`policy_snapshot_id` 必须非空且有效，之后保持不可变。`PolicyDecision` 一旦写入正式决策，`policy_snapshot_id` 必须非空；账号缺失用 `account_policy=unknown` 表达，不能用空快照代替。`VariantVersion`、`AssetVersion`、`DistributionTargetVersion` 和 `PublicationIntent` 都必须保存所使用的不可变 `RegionProfileVersion`/`PolicySnapshot` 引用或哈希，不能运行时读取可变的 RegionProfile 根对象。

Schema 中 `eligible_delivery_modes` 的示例值只代表 M1 无账号场景；真实连接建立后，必须根据该 TargetVersion 的能力快照、账号状态和 Policy 决策重新计算，并创建新的 TargetVersion，可增加 `draft_only` 或 `authorized_api`，但不能在旧快照上追加模式。

TargetVersion 的跨字段约束必须写入 JSON Schema 和数据库检查：`manual_export` 要求 `account_connection_id=null`；`simulation` 要求 `account_connection_id=null`、`synthetic_target_id!=null` 且环境只能是 dev/staging；`draft_only`/`authorized_api` 要求真实 `account_profile_id` 和 `account_connection_id`、`synthetic_target_id=null`，并满足授权、健康、Scope、环境和平台能力。`platform_id` 必须引用 `platforms` 注册表，实际 `DeliveryAttempt.adapter_ref` 与平台/环境不匹配时拒绝执行。

`RightsRecord.status` 和 `current_version_id` 只能由权利版本用例更新；许可证、地区、媒体和期限等可审计字段以 `RightsRecordVersion` 为准。`Observation.metric_value` 必须按 `MetricDefinition.metric_type` 校验：`number` 使用数值、`boolean` 使用布尔值、`string`/`enum` 使用字符串、`json` 使用受 Schema 约束的 JSON；不能把所有指标强制存成数字。`Observation.metric_definition_id` 与 `MetricDefinition.version_no` 必须成对保存，指标定义一旦被使用不得覆盖。
`Observation.metric_value` 在实际 JSON Schema 中必须使用按 `metric_type` 分支的 `oneOf`/等效校验；示例中的 `0` 只是占位值，不是所有指标的固定类型。

`FeedbackItem` 至少包含：`id`、`org_id`、`observation_ids`、问题摘要、`recommendation_type`（refresh/revise/retire/reprioritize/channel_change/prompt_eval）、`impact`、`priority`、`confidence`、`reasoning_snapshot`、负责人、截止时间、`approver_id`、`expires_at`、`created_action_id`、`status` 和 `created_at`。Feedback 只提出动作，动作必须经过人工批准或明确的低风险规则后才执行。

---

## 5. 策略、事件和非功能基线

### 5.1 Policy 分层与合并规则

策略不要集中成一个无法解释的“大规则”。分别计算，再由 `PolicyDecision` 合并：

```text
ContentPolicy       内容事实、版权、原创性、披露和风险等级
RegionPolicy        语言、地区、单位、货币、法规、时区和数据驻留
DistributionPolicy  平台能力、内容格式、配额、排程和交付模式
AccountPolicy       账号授权、Scope、健康状态、负责人和 Kill Switch
DataProcessingPolicy 数据分类、供应商、数据地域、保留期限和删除传播
ModelPolicy         模型供应商条款、可发送字段、预算、日志和人工降级
                          ↓
                     PolicyDecision
```

规则要求：

- 账号缺失时 `AccountPolicy=unknown`，只能允许 `manual_export` 或 `simulation`，不能伪造 `healthy`。
- 策略在任务入队前、Worker 领取前和外部调用前重新计算，避免旧批准任务在账号接入后越权发送。
- 人工 override 必须记录理由、操作者、覆盖范围、创建时间和过期时间。
- Feedback 只能产生可解释的 Recommendation，不能直接修改生产规则或自动降低门槛。
- 合并顺序固定为 `Content → Region → DataProcessing/Model → Distribution → Account`；任何 `deny` 优先于 `manual_review`，任何 `manual_review` 优先于 `allow`，缺失的 Account 结果只能是 `unknown`。
- 每次合并生成不可变 `PolicySnapshot`，记录各子策略版本、规则哈希、输入哈希、评估时间、有效期和作用对象；`PolicyDecision` 必须引用该快照，不能只保存最终布尔值。

### 5.2 业务事件

事件表达已发生的业务事实，不把 Agent 内部思考过程当成公共事件：

```text
topic.opportunity.scored
topic.signal.created
topic_signal.rejected
topic.opportunity.created
topic.opportunity.approved
topic.opportunity.rejected
topic.brief.created
topic.brief.approved
topic.brief.rejected
topic.brief.deferred
topic.brief.superseded
topic.production.started
topic.monitoring.started
topic.refresh.started
topic.retired
source.ingested
source.quarantined
source.snapshot.quarantined
source.snapshot.usable
source.snapshot.expired
source.snapshot.revoked
source.snapshot.blocked
source.usable
source.blocked
source.expired
source.revoked
rights.version.created
rights.version.verified
rights.version.expired
rights.version.revoked
rights.version.complaint_hold
entity.created
entity.activated
entity.retired
claim.created
claim.verified
claim.withdrawn
claim.freshness.changed
evidence.captured
evidence.validated
evidence.invalidated
knowledge.core.activated
knowledge.core.retired
knowledge.core_version.verified
knowledge.core_version.changed
policy.snapshot.created
policy.snapshot.expired
policy.snapshot.revoked
distribution.target.created
distribution.target.retired
distribution.target_version.created
distribution.target_version.activated
distribution.target_version.retired
region.profile.created
region.profile_version.created
region.profile_version.activated
region.profile_version.retired
canonical.version.created
canonical.evidence_requested
canonical.fact_checked
canonical.version.approved
canonical.version.superseded
canonical.version.withdrawn
variant.created
variant.root_changed
variant.localized
variant.draft_created
variant.qa_requested
variant.approved
variant.withdrawn
asset.created
asset.root_changed
asset.render_started
asset.qa_requested
asset.approved
asset.withdrawn
asset.blocked
publication_intent.ready
export_package.created
delivery.simulated
publication.queued
publication.dispatched
publication.cancelled
delivery.attempted
delivery.succeeded
delivery.retry_scheduled
delivery.failed
delivery.unknown
delivery.unknown_resolved
delivery.dead_lettered
publication.blocked
publication.recorded
publication.acknowledged
publication.published
publication.failed
publication.unknown
publication.unknown_resolved
publication.removed
export_package.expired
export_package.revoked
metric.definition.created
metric.definition.activated
metric.definition.retired
observation.recorded
analytics.content.observed
analytics.asset.observed
analytics.publication.observed
analytics.interaction.observed
analytics.geo.observed
analytics.support.observed
analytics.qa.observed
analytics.cost.observed
analytics.risk.observed
analytics.kpi_snapshot.created
feedback.recommendation_created
refresh.requested
account.connection_changed
approval.requested
approval.recorded
approval.approved
approval.rejected
approval.expired
approval.revoked
human_task.created
human_task.assigned
human_task.claimed
human_task.started
human_task.submitted
human_task.completed
human_task.rejected
human_task.expired
human_task.escalated
human_task.cancelled
task_job.leased
task_job.started
task_job.succeeded
task_job.failed
task_job.retry_scheduled
task_job.queued
task_job.dead_lettered
task_job.cancelled
outbox.publish_started
outbox.published
outbox.failed
outbox.retry_scheduled
outbox.dead_lettered
approval.decision_recorded
feedback.approved
feedback.rejected
feedback.expired
feedback.executed
feedback.action_approved
feedback.action_cancelled
feedback.action_started
feedback.action_executed
feedback.action_failed
site.page_version.ready
site.page_version.published
site.page_version.superseded
site.page_version.rolled_back
geo.fixture.activated
geo.fixture.retired
webhook.deduplicated
webhook.processed
webhook.rejected
webhook.dead_lettered
deletion.queued
deletion.started
deletion.completed
deletion.partially_completed
deletion.failed
kill_switch.paused
kill_switch.resumed
agent_run.completed
model.call.started
model.call.succeeded
model.call.failed
```

每个事件都使用统一信封：`event_id`、`event_type`、`event_schema_version`、`occurred_at`、`org_id`、`trace_id`、`correlation_id`、`causation_id`、`aggregate_type`、`aggregate_id`、`aggregate_version`、`actor_type`、`actor_id`、`idempotency_key`、`payload`、`payload_hash`。事件不得包含 raw token、Secret Manager 值或未脱敏 PII。Outbox 采用 at-least-once；同一 aggregate 按 `aggregate_version` 有序，Consumer 按 `event_id` 去重，poison event 进入 DLQ，重放不能重复产生外部副作用。

`topic.signal.created`、`topic.opportunity.created`、`approval.*`、`policy.snapshot.*`、`region.profile*`、`metric.definition.*`、`human_task.*`、`agent_run.completed`、`observation.recorded`、`feedback.recommendation_created` 和 `account.connection_changed` 是 append-only record/config events，不一定对应状态机转换；事件注册表必须额外登记 producer、aggregate、Schema、幂等和重放策略。其余状态转换事件必须与 4.5 表一一对应。

事件注册最小字段（机器真源为 `packages/contracts/events/` 下的事件 Schema；`docs/contracts/event-registry.yaml` 只做索引和人工说明）：

| 事件类别 | 必须登记的内容 | 重放规则 |
|---|---|---|
| 状态转换事件 | producer、aggregate、旧/新状态、Schema `$id`、版本、幂等键 | 只重算内部投影；外部副作用复用原 provider 幂等键并先回查 |
| append-only 事实事件 | producer、事实对象、输入快照哈希、Schema、数据质量 | 可重建读模型，不得把事件改写成新的历史事实 |
| 运行控制事件 | `task_job`/`outbox` 状态、租约或投递结果、错误分类 | 允许重试和 DLQ；不得产生新的业务副作用 |

以下事件必须在注册表中逐条存在：`topic.brief.deferred`、`topic.brief.superseded`、`approval.revoked`、`approval.decision_recorded`、`human_task.assigned`、`human_task.started`、`human_task.submitted`、`human_task.cancelled`、`task_job.leased`、`task_job.started`、`task_job.succeeded`、`task_job.failed`、`task_job.retry_scheduled`、`task_job.queued`、`task_job.dead_lettered`、`task_job.cancelled`、`outbox.publish_started`、`outbox.published`、`outbox.failed`、`outbox.retry_scheduled`、`outbox.dead_lettered`、`feedback.approved`、`feedback.rejected`、`feedback.expired`、`feedback.executed`、`feedback.action_approved`、`feedback.action_cancelled`、`feedback.action_started`、`feedback.action_executed`、`feedback.action_failed`。脚本会检查事件是否有 producer、Schema 和 replay_policy，不能只依赖通配说明。

### 5.3 最小 API Catalog

API 先实现以下稳定用例；不要直接暴露数据库 CRUD：

| 方法 | 路径 | 所属模块 | 作用 |
|---|---|---|---|
| `POST` | `/v1/topic-signals` | topic | 导入一个 TopicSignal |
| `POST` | `/v1/topic-opportunities/{id}/score` | topic | 生成可解释评分 |
| `POST` | `/v1/topic-opportunities/{id}/approve` | topic | 批准选题机会，不自动创建 Brief |
| `POST` | `/v1/topic-opportunities/{id}/brief` | topic | 根据已批准机会创建 TopicBrief |
| `POST` | `/v1/topic-briefs/{id}/approve` | topic | 在同一事务内完成批准和锁定，写入 `locked_at/locked_by/lock_hash`；重复调用返回同一结果 |
| `POST` | `/v1/topic-briefs/{id}/defer` | topic | 延期并记录原因、负责人和下次复核时间 |
| `POST` | `/v1/sources` | provenance | 登记来源和快照 |
| `POST` | `/v1/rights-records/{record_id}/versions/{version_id}/verify` | provenance | 验证具体权利版本，并原子更新 current pointer |
| `GET` | `/v1/platforms` | distribution | 查询已登记的平台能力和适配器状态 |
| `POST` | `/v1/rights-records/{record_id}/versions` | provenance | 创建不可变权利版本快照；要求 If-Match 和递增 version_no |
| `POST` | `/v1/canonical-contents` | canonical_content | 创建 CanonicalContent |
| `POST` | `/v1/canonical-contents/{id}/versions` | canonical_content | 创建不可变版本 |
| `POST` | `/v1/variants` | production | 创建语言/地区变体 |
| `POST` | `/v1/content-variants/{variant_id}/versions/{version_id}/qa` | qa | 对具体 VariantVersion 执行 QA 并生成报告 |
| `POST` | `/v1/assets/{asset_id}/versions/{version_id}/qa` | qa | 对具体 AssetVersion 执行媒体 QA |
| `POST` | `/v1/approvals` | approval | 为指定 aggregate/version 创建审批任务 |
| `POST` | `/v1/approvals/{id}/approve` | approval | 在 If-Match、Policy 和 quorum 通过后记录人工批准 |
| `POST` | `/v1/approvals/{id}/reject` | approval | 记录人工拒绝和原因 |
| `POST` | `/v1/approvals/{id}/decisions` | approval | 写入一条不可变 `ApprovalDecision`；同一 reviewer 只能写一条 |
| `POST` | `/v1/approvals/{id}/revoke` | approval | 撤回已批准聚合并记录原因 |
| `POST` | `/v1/distribution-targets` | distribution | 创建稳定目标定义 |
| `POST` | `/v1/distribution-targets/{target_id}/versions` | distribution | 创建不可变 TargetVersion 快照 |
| `POST` | `/v1/distribution-targets/{target_id}/versions/{version_id}/activate` | distribution | 激活具体 TargetVersion |
| `POST` | `/v1/distribution-targets/{target_id}/versions/{version_id}/revalidate` | distribution | 重新计算能力/Policy 并创建新 TargetVersion，不修改旧快照 |
| `POST` | `/v1/publication-intents` | distribution | 创建目标特定的分发意图 |
| `POST` | `/v1/publication-intents/{id}/export` | distribution | 生成 Manual Export 包 |
| `POST` | `/v1/publication-intents/{id}/simulate` | distribution | 通过 Fake Adapter 模拟 |
| `POST` | `/v1/publication-intents/{id}/queue` | distribution | 受权限保护地创建真实/沙盒交付任务；不直接调用平台 |
| `GET` | `/v1/publication-records/{id}` | distribution | 查询发布结果和回查历史 |
| `POST` | `/v1/publication-records/{id}/resolve-unknown` | distribution | 人工核查 unknown 并保存证据 |
| `GET` | `/v1/delivery-attempts/{id}` | distribution | 查询单次交付尝试、重试和错误 |
| `GET` | `/v1/export-packages/{id}` | distribution | 查询私有导出包状态 |
| `POST` | `/v1/export-packages/{id}/revoke` | distribution | 撤回尚未过期的导出包 |
| `POST` | `/v1/region-profiles/{profile_id}/versions/{version_id}/activate` | geo_region | 激活具体 RegionProfileVersion |
| `POST` | `/v1/region-profiles/{profile_id}/versions/{version_id}/revalidate` | geo_region | 校验过期规则并创建新版本，不修改旧版本 |
| `POST` | `/v1/policy-snapshots/evaluate` | policy | 生成不可变 PolicySnapshot/Decision |
| `GET` | `/v1/metric-definitions` | analytics | 查询带版本的指标定义 |
| `POST` | `/v1/feedback-items/{id}/approve` | feedback | 批准推荐并创建/确认一个 `FeedbackAction` |
| `POST` | `/v1/feedback-actions/{id}/start` | feedback | 启动已批准的反馈动作 |
| `POST` | `/v1/feedback-actions/{id}/complete` | feedback | 保存结果快照并完成反馈动作 |
| `POST` | `/v1/feedback-actions/{id}/fail` | feedback | 记录动作失败和补偿建议 |
| `POST` | `/v1/feedback-actions/{id}/cancel` | feedback | 取消尚未执行的反馈动作 |
| `POST` | `/v1/observations` | analytics | 写入站点、QA、GEO、人工或 Fake Observation |
| `POST` | `/v1/kill-switches/{scope}/pause` | governance | 暂停指定范围的新副作用任务 |
| `POST` | `/v1/kill-switches/{scope}/resume` | governance | 恢复指定范围并记录操作者、原因和时间 |
| `GET` | `/v1/human-tasks` | workflow | 查询待处理人工任务 |
| `POST` | `/v1/human-tasks/{id}/assign` | workflow | 分派人工任务 |
| `POST` | `/v1/human-tasks/{id}/claim` | workflow | 领取人工任务 |
| `POST` | `/v1/human-tasks/{id}/start` | workflow | 开始处理并确认输入版本 |
| `POST` | `/v1/human-tasks/{id}/submit` | workflow | 提交结果、证据和待复核内容 |
| `POST` | `/v1/human-tasks/{id}/complete` | workflow | 完成人工任务并提交结果 |
| `POST` | `/v1/human-tasks/{id}/reject` | workflow | 退回人工任务并记录原因 |
| `POST` | `/v1/human-tasks/{id}/expire` | workflow | 按 SLA 使任务过期并重新分派 |
| `POST` | `/v1/human-tasks/{id}/escalate` | workflow | 升级到指定队列并记录原因 |
| `POST` | `/v1/human-tasks/{id}/cancel` | workflow | 取消尚未产生不可逆副作用的任务 |
| `GET` | `/v1/canonical-contents/{id}/versions` | canonical_content | 查询版本和 diff |
| `GET` | `/v1/canonical-contents/{id}/evidence` | knowledge | 查询 Claim/Evidence |
| `GET` | `/v1/feedback-items` | feedback | 查询反馈和推荐动作 |

所有写接口要求 `Idempotency-Key`；服务端按“组织 + 操作类型 + 业务对象”限定幂等作用域，并保存 payload hash。相同键但 payload 不同返回 `IDEMPOTENCY_KEY_REUSED`，相同键且 payload 相同返回第一次结果。审批、版本和状态修改还必须要求 `If-Match`/`expected_version`，版本不一致返回 `OPTIMISTIC_LOCK_CONFLICT`。`/versions/{version_id}/...` 中的 `version_id` 是状态拥有者，不能只传根对象 ID。审批记录必须带 `aggregate_type/id/version`、reviewer、Policy 快照和证据引用；R3/R4 的 quorum 由多个 approval decision 记录满足。`export`、`simulate`、`queue` 是受权限保护的 command，真正 dispatch 只能由内部 Worker 调用；`simulate` 同样必须经过 Policy 和 Kill Switch。返回统一的 `trace_id` 和错误码。真实平台发布接口在阶段 8 前不得开放。 `TopicBrief` 的公开 `approve` 命令必须原子写入批准和锁定字段，不提供可绕过批准状态的公开 `lock` CRUD；内部重试只能调用同一幂等用例。

以下命令是内部用例，不作为公开 HTTP CRUD；它们必须通过 `WorkflowPort`、模块用例或受限 Worker 调用，并使用同样的幂等、租约、审计和 Policy 检查：

| 内部命令 | 调用方 | 适用对象 |
|---|---|---|
| `submit_evidence`、`fact_check`、`approve`、`withdraw`、`supersede` | 内容/QA/审批用例 | CanonicalContentVersion |
| `create_draft`、`localize`、`request_qa`、`approve`、`withdraw` | Production/QA 用例 | VariantVersion |
| `render`、`submit_qa`、`approve`、`withdraw`、`block` | Media Worker/QA 用例 | AssetVersion |
| `quarantine`、`mark_usable`、`block`、`expire`、`revoke` | Provenance Worker/人工任务 | Source/SourceSnapshot |
| `approve`、`start`、`complete`、`fail`、`cancel` | Feedback 用例/受限 Worker | FeedbackAction |
| `lease`、`start`、`succeed`、`fail`、`schedule_retry`、`dead_letter`、`cancel` | Worker only | TaskJob |
| `publish`、`ack`、`fail`、`retry`、`dead_letter` | OutboxDispatcher only | OutboxEvent |
| `query`、`run`、`parse` | Scheduler + FakeGeo/合规采样接口 | GEO_CONTENT |
| `publish`、`rollback`、`revalidate` | Knowledge Site 发布器 | SitePageVersion |
| `verify`、`dedupe`、`replay` | WebhookPort | WebhookReceipt |

公开 API 只暴露经过权限和版本校验的业务命令；内部命令不能被前端直接拼接状态字段调用。

### 5.4 非功能基线

阶段 0 必须先填写真实目标；以下是表格字段，不是可以随意跳过的默认值：

| 指标 | 必须确定的内容 |
|---|---|
| 内容产量 | 每周主题数、Canonical 数、语言变体数、资产数 |
| 并发量 | 同时运行的研究、翻译、QA、渲染和发布任务数 |
| 延迟 | 选题到草稿、审批响应、任务排队和导出完成时间 |
| 预算 | 每篇内容、每个视频、每次 GEO 采样和每月模型成本上限 |
| 数据 | 数据地域、保留期、删除 SLA、备份周期 |
| 可靠性 | 任务成功率、可接受人工介入率、RPO、RTO |
| 人工能力 | 审核人数、每日处理量、R3/R4 审批 SLA |

账号数量不能替代容量指标。是否拆分 Worker、服务或存储，应依据任务量、媒体 CPU、第三方配额和人工吞吐量。

### 5.5 阶段 Gate 统一模板

每个阶段出口都必须同时提供四类证据：

- **代码出口**：指定模块、API、事件、迁移和契约文件存在并通过 Review。
- **数据出口**：seed、synthetic fixture、版本链和 Given-When-Then 场景可重复执行。
- **运行出口**：明确命令、健康检查、Worker 日志、指标、staging 演示和失败重放记录。
- **治理出口**：权限、审计、Policy、Kill Switch、成本、回滚和 Runbook 已补齐。

阶段存在以下任一情况，就不能进入下一阶段：迁移未验证、契约未锁定、关键状态不可重放、无审计记录、生产副作用未被环境策略阻断、或出口指标没有数据质量说明。

### 5.6 并行开发原则

阶段不是完全串行，但依赖必须明确：

```text
阶段 1 契约/事件/观测
       ├─ Topic Intelligence
       ├─ Provenance + Canonical
       └─ Internal IAM
                 ↓
Production + QA + Policy + Approval
                 ↓
GEO_CONTENT / GEO_REGION ── Media
                 ↓
Distribution Manual/Fake
                 ↓
真实 AccountConnection / Platform
                 ↓
Observations → Feedback Loop
```

Topic Intelligence 可以与来源和 Canonical 并行，但 `TopicBrief` 必须成为 Canonical 创建的输入。Analytics/Feedback 的事件契约在阶段 1 定义，完整实现可以后置。

### 5.7 账号后置接入的迁移工作流

账号后置是架构设计的一部分，不是把 `account_id` 留空后再临时补字段。无账号阶段先创建 `planned` 或 `synthetic` 的 `AccountProfile`、`DistributionTarget` 和不可变 `DistributionTargetVersion`；它们只允许 `manual_export` 或 `simulation`。真实账号到位后，按下面顺序迁移：

```text
外部依赖确认
→ 授权证据登记
→ AccountConnection 建立
→ Scope/健康/区域/能力检查
→ 新建真实 TargetVersion
→ 重新计算 PolicySnapshot/PolicyDecision
→ 创建 derived PublicationIntent
→ draft_only
→ 回查确认
→ 低频受控发布
```

每一步都必须产生审计事件和可回查证据。旧的 synthetic TargetVersion、审批记录和 PublicationIntent 永远不改写，也不能因为账号后来接入而自动获得真实发布能力。真实连接只通过短时 connection handle 进入适配器；Token 只存在 Secret Manager/KMS，数据库和日志只保存脱敏快照、Scope 哈希、版本和证据引用。

账号接入的最小门禁如下：

1. `EXT-ACCOUNT-001` 已满足，且主体、负责人、授权范围、区域和数据处理条件已登记。
2. Fake OAuth、Fake Adapter、Webhook 去重和未知结果测试已通过；真实平台先只开放 `draft_only`。
3. 只有新的 TargetVersion 通过 Account、Distribution、Region 和 Content Policy 后，才能创建新的真实 PublicationIntent。
4. 队列领取、外部调用、回查三个时点都重新检查 Kill Switch、Scope、账号健康和 Policy；任一检查失败则转 `blocked` 或人工任务。
5. 首次真实动作必须能通过外部 ID/URL 回查。未知结果只允许查询和人工确认，不得自动重复创建外部对象。

账号尚未到位时，阶段 0–7 的开发、测试和演示继续使用人工导出、Fake Provider、Fake Adapter、Fake Geo、Fake Inbox 和 synthetic fixtures；不得把这些结果标记为真实平台指标。

---

## 6. Codex 可准确执行的任务规范

### 6.1 每张任务卡必须包含

```text
任务 ID：例如 CANON-003
领域：canonical_content
目标：一句话说明要完成的行为
明确不做：列出本任务禁止扩大的范围
前置依赖：任务 ID、ADR、Schema 或 fixtures
允许修改目录：精确到目录
禁止修改目录：例如 adapters/platforms、prod 配置
输入：API、命令、事件或文件
输出：数据表、返回值、事件和页面
数据库：表、字段、约束、`packages/db/migrations` 迁移和回滚策略
状态转换：允许的旧状态→新状态
权限：谁能调用，谁不能调用
幂等：幂等键和重复请求行为
失败处理：错误码、重试、死信和人工升级
审计与指标：必须记录的事件、日志和指标
Given-When-Then：可执行验收条件
测试文件与命令：精确路径和命令
交付证据：代码、迁移、fixtures、测试输出、截图或报告
```

### 6.2 Codex 执行约束

- 每次只完成一个 `TASK-ID`，不要自行扩大到相邻模块。
- 开始前必须阅读目标模块 `README.md`、相关 ADR 和 `packages/contracts`。
- 先检查当前工作树和已有修改，不覆盖用户已有改动。
- 先写或更新 Schema、迁移和测试，再实现业务代码。
- 无真实账号阶段不得读取、生成或保存真实凭证，不得请求真实平台副作用。
- 真实平台适配器必须有 Fake Adapter 和契约测试后才能实现。
- 依赖缺失时报告具体阻塞项，不擅自换框架或引入新的基础设施。
- 完成后报告：修改文件、迁移、测试命令与结果、未完成项、风险和回滚方法。

每次交给 Codex 的执行消息建议固定为：

```text
请只完成 TASK-ID：<任务编号>。
先读取：目标模块 README、相关 ADR、packages/contracts、前置任务输出和当前工作树。
只修改“允许修改目录”；不要修改“禁止修改目录”，不要顺手重构相邻模块。
没有真实账号时只使用 Fake Provider、Fake Adapter、FakeInbox、FakeGeo 和 synthetic fixture；不得读取、生成或保存真实凭证，不得调用真实平台副作用。
先更新契约/迁移/测试，再实现代码；运行任务卡指定命令。
如果依赖、契约或验收条件不完整，先报告阻塞项并停止扩大范围。
完成后输出：修改文件、迁移、测试结果、审计事件/指标、已知限制和回滚方法。
```

### 6.3 任务依赖和并行边界

以下依赖是 Codex 开工前的最小检查，不满足时不能自行跨阶段补功能。表中的“任务组”只是阅读分组，由 `docs/task-registry.yaml` 展开为精确 ID；它不是可以复制到 `depends_on` 的通配符或范围表达式：

| 波次 | 任务组 | 必须先完成 | 可并行工作 | 不能提前做 |
|---|---|---|---|---|
| A | 治理任务（阶段 0） | 无 | 治理文档可并行评审 | 真实平台和真实凭证 |
| B | 底座、内部 IAM、无凭证 Target、Model/Agent/Workflow/Observation 契约 | 波次 A；排程还依赖 RegionProfile 基础契约 | 契约、数据库、观测、Fake Provider 可并行；同一 exclusive path 按 registry 串行 | 真实模型、OAuth、平台 HTTP |
| C | Topic、Provenance、Knowledge、Canonical | 波次 B；Canonical 必须有已批准且锁定的 TopicBrief | Topic、Provenance、Knowledge 可并行 | 未经 Brief 直接生产 Canonical |
| D | Agent 业务实现、Production、QA、Policy、Approval、Eval | 波次 C 的 Canonical 契约和波次 B 的 Agent/Model 基础 | QA、Policy、审批 UI 可并行；契约 owner 任务先行 | 自动发布、把 Agent 输出当最终批准 |
| E | Knowledge Site、GEO_CONTENT、GEO_REGION | 至少一个批准 Variant；FakeGeo 只使用离线 fixture | 站点、内容 GEO、区域规则可并行 | 把模拟采样解释成真实排名 |
| F | Media/Asset | 批准 Variant、有效素材权利和波次 D QA | 脚本、字幕、渲染可分任务 | 没有权利证据的素材发布 |
| G | Distribution、Manual Export、Fake Adapter、核心反馈观察 | 波次 D；TargetVersion、Policy、Workflow 和 Fake Adapter 契约 | Manual Export、Fake Adapter、重放测试可并行 | 真实账号、真实 Token、真实平台请求 |
| H | AccountConnection、OAuth、首个平台 | 波次 G 全部 Gate、`EXT-ACCOUNT-001` 已满足 | OAuth、账号健康和单平台适配器按平台分卡 | 批量账号和多平台同时上线 |
| I | Analytics、完整 Feedback、Support、Pilot | 波次 G；真实指标项依赖波次 H | 模拟观测、真实归因和客服草稿可分开 | 把 Fake/人工数据标成真实平台数据 |

“可并行”只表示文件和契约边界不冲突；每个任务仍须独立通过自己的测试和阶段 Gate。

`docs/task-registry.yaml` 至少使用以下字段；表中的 `*` 只允许出现在人工阅读的分组说明中，不能写进机器校验的依赖字段：

```yaml
- id: CANON-003
  phase: 3
  owner: team/canonical-content
  priority: critical
  tier: P0
  depends_on: [FOUND-009, TOPIC-004, PROV-001, PROV-002, KNOW-001, KNOW-002]
  contract_refs: [packages/contracts/jsonschema/canonical-content-version.schema.json]
  migration_refs: [packages/db/migrations/<revision>_canonical_content_versions.py]
  task_spec_ref: docs/tasks/CANON-003.md
  inputs: [approved_topic_brief, source_snapshot, rights_record_version, claim_evidence]
  outputs: [canonical_content_version, canonical.version.created, audit_log]
  acceptance:
    given: [approved TopicBrief, valid RightsRecordVersion, at least one Claim/Evidence]
    when: [POST /v1/canonical-contents/{id}/versions]
    then: [immutable incremented version, idempotent replay, explicit error on missing evidence]
  allowed_paths:
    - modules/canonical_content
    - packages/contracts
    - packages/db/migrations
    - tests/unit
    - tests/integration
  forbidden_paths:
    - adapters/platforms
    - deploy/environments/prod
  test_command: pytest tests/unit/canonical_content tests/integration/test_canonical_versions.py
  gate: canonical_version_is_immutable
  status: planned
```

每个任务还必须有 `docs/tasks/<TASK-ID>.md` 任务卡，记录明确不做、权限、状态转换、失败处理、审计指标和 Given-When-Then 细节；registry 的 `task_spec_ref` 必须指向该文件。没有任务卡的任务可以登记为 `planned`，但 Codex 不得开工。`contract_refs`、`migration_refs`、`inputs`、`outputs` 和 `acceptance` 不能为空；占位符只能出现在未开工的 `planned` 任务中，进入 `in_progress` 前必须替换。全量精细化可以按波次推进；执行单个任务前必须运行 `python scripts/check_task_card_precision.py --task <TASK-ID> --strict`，该任务卡通过后才能进入 `in_progress`。

CI 必须检查：ID 全局唯一、依赖 ID 存在、P0 不依赖 P1/M2/M3、依赖不能形成环、允许目录不为空、禁止目录不与允许目录重叠、`owned_paths`/`exclusive_paths` 在允许目录内、任务卡和契约引用存在、任务卡引用与 registry 一致、OpenAPI 的 `x-task-ids` 有效、测试命令可执行、同波次 exclusive path 冲突已由依赖串行化、任务状态只能按 `planned → in_progress → blocked|done` 变化。阶段清单是人的阅读入口，`docs/task-registry.yaml` 和任务卡才是 Codex 与 CI 的机器入口。

### 6.4 单任务示例

```text
任务 ID：CANON-003
领域：canonical_content
目标：创建 CanonicalContentVersion，并保证版本不可覆盖。
范围：实现版本创建用例、权利快照关联、Claim 关联、迁移、API 和契约测试。
明确不做：本任务不实现翻译、媒体、平台发布和真实账号连接。
前置依赖：FOUND-009、TOPIC-004（TopicBrief 已批准）、PROV-001、PROV-002、KNOW-001、KNOW-002。
允许修改：modules/canonical_content、packages/contracts、packages/db/migrations、tests/unit、tests/integration
禁止修改：adapters/platforms、deploy/environments/prod、modules/distribution
输入：已批准 TopicBrief、SourceSnapshot、RightsRecordVersion、Claim/Evidence、`Idempotency-Key` 和 `If-Match`。
输出：CanonicalContentVersion、`canonical.version.created` 事件、版本查询结果和审计记录。
数据库：`canonical_contents`、`canonical_content_versions`、`canonical_claims`；`(canonical_content_id, version_no)` 唯一；已批准版本禁止覆盖；迁移使用 expand/contract。
状态转换：`none → draft`；缺少已批准 TopicBrief 或权利快照时拒绝。
权限：内容编辑可创建草稿；审批人不能由创建人自动代替；跨组织访问一律拒绝。
幂等：同一组织、Canonical 和 `Idempotency-Key` 返回同一版本；Payload 不同返回 `IDEMPOTENCY_KEY_REUSED`。
失败处理：缺少 Brief 返回 `TOPIC_BRIEF_REQUIRED`；缺少证据返回 `CANONICAL_EVIDENCE_REQUIRED`；不重试确定性校验错误。
审计与指标：记录 `trace_id`、actor、输入版本、rights snapshot、事件 ID、创建耗时和拒绝原因。
Given：存在已通过 `RightsRecordVersion` 的 Source 和至少一个 Claim/Evidence
When：调用 POST /canonical-contents/{id}/versions
Then：创建递增版本，保存 source_snapshot_id、claim_ids、rights_snapshot_ids 和 author_id
And：相同 idempotency_key 重试只返回同一版本
And：缺少证据时返回 CANONICAL_EVIDENCE_REQUIRED，不改变状态
测试：pytest tests/unit/canonical_content tests/integration/test_canonical_versions.py
交付证据：迁移文件、OpenAPI/事件 Schema、测试输出、synthetic fixture 和一条可按 trace_id 重放的运行记录。
```

---

## 7. 优化后的分阶段开发清单

### 阶段 0：范围、决策和治理冻结

**建议时间**：3–5 个工作日  
**目标**：把第一版范围、技术基线、风险边界和验收口径冻结。

### 必须完成

- [x] `GOV-001` 锁定首个垂直领域 `AI 技术与应用工程`、`zh-CN/en-US`、文本内容、第一方知识站和手工导出；未完成范围锁定时不得进入阶段 2。
- [x] `GOV-002` 定义 Architecture MVP、Distribution Pilot、Scale 三个发布级别，并冻结每个级别的准入、允许能力、禁止能力、退出和回滚门禁。
- [x] `GOV-003` 建立 RACI、内部用户角色、审计责任人和事故联系人，并冻结版本化职责策略。
- [x] `GOV-004` 定义 R0–R4 内容/账号/隐私/安全风险和人工升级条件。
- [x] `GOV-005` 建立政策卡模板、证据链接、复核日期和责任人，并生成供 synthetic/dev 使用的基线 Policy 快照。
- [x] `GOV-006` 冻结默认技术栈，并写入 ADR-001《模块化单体与部署基线》。
- [x] `GOV-007` 定义数据分类、保留期限、删除传播和跨境处理规则。
- [x] `GOV-008` 定义成功指标、成本预算、SLO、RPO/RTO 和人工审批 SLA。
- [x] `GOV-009` 明确真实账号获取这个外部依赖的 Owner、最晚到位时间和无账号替代方案。
- [x] `GOV-010` 建立模型、媒体、存储和数据处理供应商清单，记录数据处理地域、保留期、合同/DPA、分包商和退出/删除证明。

### 必须做好的细节

- `manual_export`（人工导出）、`simulation`（模拟发布）、`draft_only`（只创建平台草稿）、`authorized_api`（授权 API 动作）是四种不同交付模式；代码、文档和测试不得再使用其他模式名。
- 账号证据缺失只能阻断真实发布，不能阻断无账号内容生产。
- 所有不可逆选择先写 ADR；未决技术选择不得同时开工。

### 阶段出口 Gate

- 具备 PRD、范围表、RACI、风险矩阵、数据分类表、指标表和 ADR。
- 产品、技术、版权/隐私责任人完成评审。
- 禁止进入：真实平台接入、真实凭证、批量账号管理。

### 阶段 1：模块化单体底座和可观测骨架

**建议时间**：1–2 周  
**目标**：让项目可以稳定启动、迁移、测试、记录事件并执行第一条 synthetic 工作流。

### 必须完成

- [x] `FOUND-000` 清点当前仓库、已有代码、依赖、迁移、环境变量、密钥占位、部署脚本和未提交修改，输出 `docs/repo-inventory.md`；若已有实现，只能兼容扩展，不得覆盖。只有确认仓库为空时，才采用本清单的默认技术栈。
- [x] `FOUND-001` 创建 V2 目录、README、CONTRIBUTING、CODEOWNERS 和分支保护。
- [x] `FOUND-002` 创建 API、Worker、Scheduler 三个后端运行入口，以及 Web Console/Knowledge Site 前端构建入口。
- [x] `FOUND-003A` 配置 PostgreSQL、本地健康检查和最小连接 fixture。
- [x] `FOUND-003B` 配置 S3 兼容对象存储和 Fake Storage 接口；保存对象哈希和私有访问策略。
- [x] `FOUND-003D` 建立 PostgreSQL `task_jobs` 队列表和 polling 配置；首个纵向切片不依赖 Redis。
- [x] `FOUND-004A` 建立 Alembic 迁移基线、expand/contract 规则和迁移检查。
- [x] `FOUND-004B` 实现业务状态与 Outbox 同事务提交及 OutboxDispatcher。
- [x] `FOUND-004C` 实现 task claim、租约、超时和崩溃后重新领取。
- [x] `FOUND-004D` 实现失败记录、重试上限、退避和死信队列。
- [x] `FOUND-004E` 实现单任务重放命令；重放必须复用原输入版本并生成新执行记录。
- [x] `FOUND-005` 建立统一 API 错误、`trace_id/request_id/org_id/actor_id` 和结构化日志。
- [x] `FOUND-006A` 建立健康检查、业务/技术指标基类和 Prometheus 暴露。
- [x] `FOUND-006B` 建立 OpenTelemetry Tracing、成本记录和统一 correlation fields。
- [x] `FOUND-007A` 创建 OpenAPI 基线、统一错误码和版本兼容规则。
- [x] `FOUND-007B` 创建业务事件 JSON Schema、事件版本和向后兼容检查。
- [x] `FOUND-007C` 创建 Agent 输出 Schema、拒绝未知字段和 Schema 版本迁移规则。
- [x] `FOUND-007D` 将核心对象契约落到 `packages/contracts/jsonschema/*.schema.json`：必须包含 `$schema`、`$id`、`type`、`required`、`additionalProperties:false`、枚举、`oneOf` 和跨字段约束；Markdown 只作说明，不能作为机器真源。
- [x] `FOUND-008` 创建 Feature Flag、统一交付模式枚举和最小可执行全局 Kill Switch；开关关闭时拒绝新副作用任务并写入审计。
- [x] `FOUND-009` 建立 fake clock、fixtures 和 Fake Storage；本任务不调用模型或平台适配器。
- [x] `FOUND-010` 定义 `Platform` 注册表、最小 `DistributionTarget`、不可变 `DistributionTargetVersion`、`PublicationIntent`、`DeliveryAttempt` Schema，以及空的 `ConnectionPort`、`PublisherPort`、`InboxPort`、`MetricsPort`；允许无连接的 `planned/synthetic` target，但要求绑定 synthetic Policy 快照，不实现平台行为。
- [x] `FOUND-011` 建立架构依赖检查、禁止跨模块直写检查、`org_id` 隔离测试和首个 smoke 命令。
- [x] `FOUND-012A` 在 CI 实现 lockfile 校验、格式、类型、单元测试、secret scanning、SAST 和依赖/CVE 扫描；CI 不得读取生产凭证。
- [x] `FOUND-013` 在 `FOUND-000` 清点结果基础上维护并校验已提交的 `docs/task-registry.yaml`：为每个任务登记唯一 ID、阶段、Owner、优先级、层级、精确依赖、允许/禁止目录、`owned_paths`/`shared_paths`/`exclusive_paths`、契约、测试命令、出口 Gate、外部依赖和状态；CI 检查 ID、依赖、环、路径冲突和文档对齐。
- [x] `FOUND-003C` 配置 Redis，仅用于缓存、短锁和速率限制；Redis 不承担事实数据，属于 P1 优化项，不阻塞上述底座任务。
- [x] `FOUND-012B` 在 CI 生成 SBOM、执行容器扫描并签名生产制品；失败时阻止合并，属于首个纵向切片之后的 P1 加固项。
- [x] `IAM-CORE-001` 建立 dev identity、organization、actor context 和最小 RBAC middleware，供 synthetic 审批使用。
- [x] `ACCOUNT-CORE-001` 建立无凭证的 `AccountProfile`、`DistributionTarget` 和 `DistributionTargetVersion` 引用模型；用 `profile_kind=planned|synthetic` 区分规划对象和测试对象，TargetVersion 的账号连接为空，只允许 `manual_export`/`simulation`，不允许真实副作用。
- [x] `GEO_REGION-CORE-001` 建立最小 `RegionProfile` 身份对象和不可变 `RegionProfileVersion`：region_code、locales、timezone、格式、单位、货币、保留期、删除 SLA、Policy 快照、有效期和 current pointer 原子更新。
- [x] `MODEL-CORE-001` 定义 `ModelPort`、供应商错误结构、脱敏入口、超时、预算和 Fake Model Provider。
- [x] `MODEL-CORE-002` 实现一个可替换的 Model Gateway：供应商配置、Prompt/模型版本、调用哈希、成本、超时和重试均可记录；本阶段只允许 Fake Provider。
- [x] `AGENT-CORE-001` 建立 `AgentDefinition`/Registry：版本、输入/输出 Schema、工具白名单、权限、成本上限、超时和人工升级条件。
- [x] `AGENT-CORE-002` 实现 `AgentRunner`：只依赖 `ModelPort`，校验结构化输出，拒绝越权工具调用和不符合 Schema 的结果。
- [x] `AGENT-CORE-003` 实现 `ToolGateway` 和外部输入隔离：网页、评论、附件和代码作为不可信数据，不得注入系统 Prompt。
- [x] `AGENT-CORE-004` 持久化 `AgentRun`/`ModelCall`：记录模型、Prompt、输入/输出哈希、成本、脱敏状态、重试和评审人。
- [x] `WORKFLOW-CORE-001` 定义 `WorkflowPort`、持久化状态机、人工任务、暂停、恢复、重试和重放接口。
- [x] `WORKFLOW-CORE-002` 实现 `workflow_runs`、`workflow_steps`、`human_tasks` 状态和到期扫描；人工节点必须可暂停、恢复和重放。
- [x] `WORKFLOW-CORE-003` 实现 `OutboxDispatcher`、任务租约、死信和重放命令；所有命令都有幂等键。
- [x] `FEEDBACK-CORE-001` 定义 `Observation`、`FeedbackItem`、推荐动作和评分版本 Schema；本任务只定义契约，不生成真实平台数据。
- [x] `SCHED-001`（前置依赖：`GEO_REGION-CORE-001`）定义 UTC 存储、按不可变 `RegionProfileVersion` 计算时区、DB lease/advisory lock 和唯一排程幂等键；重启不重复触发，暂停后不补发旧副作用任务。
- [x] `OBS-CORE-001` 实现追加式 AuditLog、trace 关联、最小指标和证据包引用；查询和导出也要留下审计记录。
- [x] `OBS-CORE-002` 实现数据库/对象存储备份、恢复命令和恢复后队列暂停；用 synthetic 数据验证 RPO/RTO。
- [x] `OBS-CORE-003` 实现删除传播任务：关系库、对象、向量、缓存和导出包逐项确认，失败进入人工队列。

### 必须做好的细节

- Postgres 是事实源；Redis 失效不能导致任务、审批或审计数据丢失。
- Worker 领取任务使用租约和超时；进程崩溃后任务可以再次领取但不会重复产生副作用。
- 所有外部 Provider 都经过 Port；业务模块不能直接导入供应商 SDK。
- 生产配置不允许启用 synthetic 的副作用操作。

### 阶段出口 Gate

- 干净环境按 README 启动成功。
- CI 通过格式化、类型、单测、迁移、依赖扫描和架构边界检查。
- synthetic 基础任务至少成功运行 3 次；失败一次后可重放且审计完整。
- 最小 Distribution contract、环境副作用阻断和 `org_id` 隔离测试通过。
- `ModelPort`、`WorkflowPort`、`Observation/FeedbackItem` 契约和 API/事件索引已提交到 `docs/contracts`；可执行 JSON Schema 和事件 Schema 位于 `packages/contracts/`。
- 人工任务、Outbox、任务租约、排程锁和重放命令有可重复的集成测试。
- AuditLog、trace、指标和证据包在 synthetic 运行中可从一个 `trace_id` 追到最终结果。
- 禁止进入：真实 OAuth、真实平台发布。

### 阶段 2：Topic Intelligence（选题智能）

**建议时间**：1 周  
**目标**：把“为什么做这个主题”变成可解释、可审批、可复盘的数据流程。

### 必须完成

- [x] `TOPIC-001` 建立主题分类、标签、技术版本和受众模型。
- [x] `TOPIC-002` 建立 `TopicSignal`，支持人工 CSV/JSON 导入；字段必须包含 `source_type`、`source_ref`、`captured_at`、`locale`、`region`、`usage_rights_status`、`terms_snapshot_ref`、`license_ref`、`permitted_use` 和 `confidence`。
- [x] `TOPIC-003` 建立 `TopicOpportunity` 和可解释评分：需求、相关性、证据可得性、差异化、时效，扣除成本和风险。
- [x] `TOPIC-004` 建立 `TopicBrief`：目标受众、问题、核心 Claim、证据计划、原创角度、语言/市场和预期渠道。
- [x] `TOPIC-005` 建立编辑日历、负责人、优先级、截止时间和人工覆盖理由。
- [x] `TOPIC-006` 实现主题状态机和拒绝/延期原因。
- [x] `TOPIC-007` 实现机会评分的输入快照，保证分数可以复算。
- [x] `TOPIC-008` 实现 `TopicBrief` 版本锁定：批准时原子写入 `version_no`、`locked_at`、`locked_by`、`lock_hash` 和 `input_snapshot_hash`；批准/锁定后禁止原地修改，修改必须创建新版本。

### 必须做好的细节

- 每个批准主题必须能回答：需求来自哪里、谁会看、为什么现在做、有什么独特证据、风险是什么。
- TopicSignal 也要有来源和使用权；未经授权的外部原文只能用于主题判断，不能直接进入 Canonical 或 Prompt。
- 评分不能只由 LLM 生成；基础分项使用确定性规则，LLM 只提供结构化建议。
- 人工修改评分必须记录旧值、新值、理由、操作者和过期时间。

### 阶段出口 Gate

- 输入 10 条人工 TopicSignal，系统能产生排序、解释和 TopicBrief。
- 至少批准 3 个主题并生成编辑日历；每个主题可追溯信号和决策人。
- 禁止进入：自动批量生成无主题依据的内容。

### 阶段 3：Provenance、Rights、KnowledgeCore 和 Canonical Content

**建议时间**：2 周  
**目标**：建立渠道无关的知识和内容真源。

### 必须完成

- [x] `PROV-001` 实现 Source、SourceSnapshot、抓取方式、原文哈希和可信度。
- [x] `PROV-002` 实现 RightsRecord 身份对象、不可变 RightsRecordVersion、授权范围、期限、地区、语言、媒体、商业使用和撤销事件。
- [x] `PROV-003` 实现无授权阻断、到期提醒、投诉冻结和派生内容反向追踪。
- [x] `KNOW-001` 实现 Entity、Claim、Evidence、适用版本/地区/时间和事实类型。
- [x] `KNOW-002` 实现 `KnowledgeCore`，保存结构化事实、证据关系、冲突和新鲜度。
- [x] `CANON-001` 实现 CanonicalContent：渠道无关的编辑叙事、章节结构、代码、示例和限制。
- [x] `CANON-002` 实现不可变 CanonicalContentVersion 和版本差异。
- [x] `CANON-003` 创建版本时强制引用已批准的 `TopicBrief`；没有 Brief 的请求返回 `TOPIC_BRIEF_REQUIRED`，不能绕过选题流程。
- [x] `CANON-004` 让每个高优先级 Claim 绑定至少一个 Evidence 和具体的 `RightsRecordVersion`。
- [x] `CANON-005` 实现内容新鲜度、版本过期、事实冲突和刷新队列。
- [x] `CANON-006` 建立 `canonical → variant → asset → publication` lineage 查询。

### 必须做好的细节

- `KnowledgeCore` 保存事实和证据；`CanonicalContent` 保存经审批的叙事结构，两者不能混成一个不可维护的大 JSON。
- Canonical Content 可以有主语言，但不能绑定平台、账号或渠道字段。
- 事实或权利撤销时，必须列出受影响的变体、资产和发布记录，并自动冻结后续动作。
- 原文、翻译、改编和修订均创建新版本，不能覆盖旧版本。

### 阶段出口 Gate

- 完成一条来源→Rights→KnowledgeCore→CanonicalContent v1 的全链路。
- 没有 `TopicBrief.status=approved` 时，创建 Canonical 版本必须失败并返回 `TOPIC_BRIEF_REQUIRED`。
- 任意 Claim 能在页面上反查 SourceSnapshot、具体 RightsRecordVersion、授权、审核人和适用版本。
- 修改 Canonical v1 生成 v2，旧版本仍可复现。
- 禁止进入：没有证据的原创标记、覆盖写入历史版本。

### 阶段 4：Production、Localization、QA、Policy 和 Approval

**建议时间**：2 周  
**目标**：从 Canonical Content 生成可审核的语言/地区变体。

### 必须完成

- [x] `AGENT-CORE-005A` 基于 AgentRunner 实现 Planner Agent；只输出结构化 Topic/Workflow Plan，不调用发布、授权或外部副作用工具。
- [x] `AGENT-CORE-005B` 基于 AgentRunner 实现 Research Agent；只输出带来源引用的候选事实和待核查项，不把模型判断直接写入 KnowledgeCore。
- [x] `AGENT-CORE-005C` 基于 AgentRunner 实现 Rights/Provenance Agent；只抽取许可证线索、范围和缺口，最终权利判断必须由规则或人工完成。
- [x] `AGENT-CORE-005D` 基于 AgentRunner 实现 Transform Agent；只生成 Variant 草稿，保留 Claim、术语、数字、代码和链接映射。
- [x] `AGENT-CORE-005E` 基于 AgentRunner 实现 QA Agent；只生成可解释检查结果和人工任务，不直接批准或发布。
- [x] `MODEL-001`（可选外部依赖，不得阻塞 M1）通过 `ModelPort` 接入一个经批准的非平台模型 Provider（仅 dev/staging）；记录供应商条款、数据地域、超时、成本和失败降级。没有模型凭证时继续使用 Fake Model 或固定人工 fixture，CI 始终不依赖真实模型。
- [x] `PROD-001` 通过可替换的 `TransformPort` 生成 Variant 草稿；M1 使用 Fake/规则实现，Transform Agent 接入属于后续 P1，不调用发布接口。
- [x] `PROD-002` 实现 `ContentVariant` 和 `VariantVersion`，字段包含 locale、market、audience、tone、disclosure 和来源版本。
- [x] `PROD-003` 实现术语表、Translation Memory、产品名锁定、数字/代码/链接保护。
- [x] `PROD-004` 实现 `GEO_REGION` 前置规则：语言、单位、货币、时区、法规、披露和市场限制。
- [x] `QA-001` 实现 Claim/Evidence、时效、数字、引用、术语、代码和链接检查。
- [x] `QA-002` 实现相似度、重复度、AI 标识、广告披露和素材权利检查。
- [x] `QA-003` 实现代码沙箱、静态检查、依赖锁定和危险命令阻断；沙箱使用临时工作区、无生产网络/密钥，记录输入哈希、运行镜像、命令白名单、资源上限和输出证据。
- [x] `POLICY-001` 实现确定性 Policy Gate：风险等级、来源权利、区域规则、审批要求和发布模式。
- [x] `POLICY-002` 实现政策卡过期和复核检查；`review_due_at` 到期后自动切换为人工模式并阻止新的副作用任务。
- [x] `APPROVAL-001` 实现人工审批台：版本 diff、证据面板、风险原因、批注、任务分派、审批期限和 override 过期时间。
- [x] `APPROVAL-002` 实现 `approval_decisions` 明细：每个审批人一条不可变投票，`(approval_id, reviewer_id)` 唯一；创建人不能审批自己的内容，R3/R4 必须由两名不同审批人达到 quorum。
- [x] `EVAL-001` 建立 LLM golden set、Prompt 版本、离线评测、模型成本和回归阈值。
- [x] `MODEL-003` 实现预算门禁：按组织、任务、模型和周期累计成本；超预算停止新模型任务并生成审计事件。

### 必须做好的细节

- 通过 QA 不等于允许发布；内容审批、资产审批和分发审批分别记录。
- R3/R4 内容必须双人审批；无法提供可靠证据时必须转人工。
- Agent 输出只能产生草稿、报告或人工任务，不能直接调用发布接口。
- Prompt、模型、阈值变更必须可回滚，并记录评测前后差异。

### 阶段出口 Gate

- 一条 Canonical Content 能生成 `zh-CN` 和 `en-US` 两个 Variant。
- 无权利、事实冲突、数字错译和高风险样本按预期阻断或转人工。
- 审批页面能显示“原文—变体—证据—规则—差异—审批人”。
- 禁止进入：自动发布、把翻译轻改标记为原创。

### 阶段 5：第一方知识中心、GEO_CONTENT 和 GEO_REGION

**建议时间**：1–2 周  
**目标**：让已批准内容可被人、爬虫和生成式引擎理解，同时正确适配地区。

### 必须完成

- [x] `SITE-001` 实现规范 URL、版本页、作者、审校者、更新时间、方法、证据、限制和 FAQ。
- [x] `SITE-002` 实现 SSR/预渲染、canonical、sitemap、RSS/Atom、robots、hreflang 和 `x-default`。
- [x] `SITE-003` 实现与可见内容一致的 Article、TechArticle、Organization、Person JSON-LD；仅在阶段 6 存在已批准视频资产时生成对应的 VideoObject。
- [x] `GEO_CONTENT-001` 建立实体一致性、Claim/Evidence 可追溯、引用就绪、内容新鲜度和抓取性规则。
- [x] `GEO_CONTENT-002` 建立 Prompt 测试集和合规采样接口，记录提及、引用、位置和正确性。
- [x] `GEO_CONTENT-003` 使用 `FakeGeo` 和离线答案 fixture 实现多次采样、解析、去重和置信度汇总；M1 只验收数据契约与解析稳定性，不宣称真实生成式搜索效果。
- [x] `GEO_REGION-001` 建立 locale/market 配置：术语、单位、货币、时区、法规、披露、数据地域和平台地区。
- [x] `GEO_REGION-002` 实现区域版本检查、hreflang、地区禁用内容和地域数据删除规则。
- [x] `SITE-004` 实现断链、重定向、HTTP 状态、性能、alt、字幕和动态渲染检查。

### 必须做好的细节

- `GEO_CONTENT` 的指标和 `GEO_REGION` 的指标分开保存、计算和解释。
- AI 答案必须多次采样；不得用单次回答判定提及或引用成功。
- 没有合规接口时只能人工采样或使用允许的服务，不做高频违规抓取。
- `/llms.txt` 只能作为实验项，不能当作排名、授权或安全开关。

`GEO_CONTENT-003` 的最小输入/输出契约：输入为 `page_version_id`、`query_fixture_id`、`locale`、`region` 和 `sample_count`；输出为带 `parser_version`、`sample_count`、`mention_count`、`citation_count`、`position_values`、`correctness_values`、`confidence` 和原始 fixture 哈希的 `Observation`。同一 fixture、同一解析器版本和同一采样配置必须可重复得到相同结果；FakeGeo 的结果只能标记为 `data_quality=estimated`。

### 阶段出口 Gate

- 中英页面可抓取，结构化数据与可见内容一致。
- 任意页面 Claim 能反查 Canonical、Evidence 和具体 RightsRecordVersion。
- 同一页面在目标市场通过语言、单位、法规和披露检查。
- `FakeGeo` 的离线 fixture 能重复运行多次采样，输出提及、引用、位置、正确性和置信度；报告明确区分模拟数据与真实平台/引擎数据。
- 禁止进入：把 GEO 指标解释成排名保证。

### 阶段 6：Media 和 Asset

**建议时间**：P1，1 周  
**目标**：从批准 Variant 生成可审阅、可重渲染和可追溯的媒体资产。

### 必须完成

- [x] `MEDIA-001` 实现 30/60/90 秒脚本模板、人工编辑和 Claim 引用。
- [x] `MEDIA-002` 实现分镜、镜头时长、素材、音乐、字体、配音和授权记录。
- [x] `MEDIA-003A` 实现单语和多语言字幕，保存时间轴、文本版本和可访问性字段。
- [x] `MEDIA-003B` 实现封面、关键帧和视觉素材引用，记录每项素材的 RightsRecordVersion。
- [x] `MEDIA-003C` 实现 9:16、1:1、16:9 输出规格校验，不在本任务执行渲染。
- [x] `MEDIA-004A` 实现渲染任务创建、输入版本锁定和中间产物保存。
- [x] `MEDIA-004B` 实现渲染失败重试、单镜头重渲染和死信；不得重复生成已确认的外部副作用。
- [x] `MEDIA-005A` 实现画面、音频、字幕和文件哈希 QA。
- [x] `MEDIA-005B` 实现数字、代码、版本、AI 标识和素材权利 QA。
- [x] `MEDIA-006` 实现 AssetVersion 与 Variant、Claim、RightsRecordVersion 的 lineage。

### 阶段出口 Gate

- 一条批准 Canonical 可生成 `zh-CN` 和 `en-US` 两个 Variant；每个已批准 Variant 可生成 9:16、1:1、16:9 三种比例的可审阅资产草稿。
- 字幕、代码、数字、音频和素材授权检查通过。
- 事实或权利撤回后，相关资产自动标记 `withdrawn` 或 `blocked`。

### 阶段 7：Distribution 抽象、Manual Export 和 Fake Adapter

**建议时间**：1 周  
**目标**：在没有真实账号时验证分发协议、状态、幂等和回滚边界。

### 必须完成

- [x] `DIST-001` 定义 `DistributionTarget`、不可变 `DistributionTargetVersion`、`PublicationIntent`、`ExportPackage`、`DeliveryAttempt`、`PublicationRecord`。
- [x] `DIST-002` 在阶段 1 最小契约基础上补齐四个 Port：`ConnectionPort`、`PublisherPort`、`InboxPort`、`MetricsPort`；不要把授权、发布、客服混成一个适配器。
- [x] `DIST-003A` 实现 `ManualAdapter` 导出标题、正文、媒体、标签、披露、检查清单和证据包。
- [x] `DIST-003B` 为 ExportPackage 实现私有对象存储、短期签名下载 URL、包过期/撤回、下载审计和版本哈希；不能默认生成公开链接。
- [x] `DIST-004` 实现 `FakeOfficialAdapter`：能力、草稿、上传、排程、发布、指标和错误码模拟。
- [x] `DIST-006A` 实现 Intent/Delivery 的幂等键和重复消费保护。
- [x] `DIST-006B` 实现上传状态、回查和 PublicationRecord 创建。
- [x] `DIST-006C` 实现未知结果、重试上限、死信和单任务重放；未知结果禁止自动副作用重试。
- [x] `DIST-007` 实现 `manual_export`、`simulation`、`draft_only`、`authorized_api` 四种唯一交付模式。
- [x] `DIST-008A` 实现平台、Target/TargetVersion 和快照不可变约束；Target 变更必须创建新 TargetVersion，不能修改已引用快照。
- [x] `DIST-008B` 实现 Intent 交付模式校验和全局/平台/账号范围 Kill Switch。
- [x] `DIST-009` 完成首个无账号纵向切片：Canonical→Variant→QA→Approval→PublicationIntent→Manual Export。
- [x] `DIST-010` 用 Fake Adapter 完成模拟发布、失败、死信、重放和重复消费测试。
- [x] `DIST-011` 定义 `WebhookPort` 和 `WebhookReceipt`：验签、外部事件去重、Schema 校验、回放和死信；M1 只实现 Fake/fixture ingress，不接真实平台 Webhook。
- [x] `DIST-005A` 实现 capability matrix 和平台字段 mapping；平台字段只能留在 adapter 层，属于 P1 扩展。
- [x] `DIST-005B` 实现配额、Retry-After、错误分类和人工升级策略，属于 P1 扩展。
- [x] `FEEDBACK-CORE-002` 写入 fake/manual `Observation`，生成可解释的 Refresh 或 Reprioritize 推荐；不修改生产规则。

### 必须做好的细节

- 平台特有字段只能存在于 adapter mapping，不能污染 Canonical 或核心 Variant。
- 模拟发布成功必须通过 Fake Adapter 回查确认，不以单次调用返回为准。
- 401/403、版权、政策、验证码和挑战错误不自动重试；429/5xx 按 Retry-After 退避。
- 手工导出包必须带内容版本、审批签名、权利摘要、区域规则和生成时间。
- `PublicationIntent` 按 TargetVersion 不可变；目标、账号、能力或政策变化时创建新 TargetVersion 和新 Intent，并保存 `derived_from_intent_id`。

### 阶段出口 Gate

- 无账号完成：Canonical→Variant→QA→Approval→PublicationIntent→Manual Export。
- 同一个 Intent 重复消费只产生一个模拟平台对象。
- 模拟失败可进入死信，修复后可重放；停发开关能阻止新 DeliveryAttempt。
- fake/manual Observation 能生成 FeedbackItem，但不会自动改变评分公式、Policy 或 Prompt。
- 禁止进入：连接真实平台、保存真实 Token。

### 阶段 8：真实 AccountConnection、OAuth 和首个平台连接

**前置条件**：阶段 0–4 与阶段 7 的 **P0 子集** Gate 全部通过；阶段 5/6 只在目标平台或内容形态需要时完成对应的 P1 任务；同时至少一个真实主体和授权联系人已准备好。  
**建议时间**：账号到位后 2–4 周  
**目标**：把真实账号作为 Distribution 的可插拔连接加入，不改变核心内容链。

阶段 1 已经定义无凭证的 `AccountProfile`/`DistributionTarget` 引用和 synthetic fixtures；本阶段只增加真实连接、授权证据、健康状态和平台副作用能力。

### 必须完成

- [ ] `ACCOUNT-001A` 在阶段 1 已有模型上增加真实 `AccountConnection` 和唯一约束；不改写既有 TargetVersion 或 Intent。
- [ ] `ACCOUNT-001B` 实现 `AuthorizationEvidence` 关联、证据完整性检查和 AccountPassport 只读汇总视图。
- [ ] `ACCOUNT-001C` 为每个真实连接创建新的不可变 `DistributionTargetVersion`，保存脱敏账号快照、能力快照和 Policy 快照。
- [ ] `OAUTH-001A` 定义真实 OAuth Provider 接口和授权状态机；先实现 Fake OAuth Provider 和契约测试。
- [ ] `OAUTH-001B` 实现真实 OAuth 回调的 State/PKCE、redirect URI 和 CSRF 校验；不在回调中直接发布内容。
- [ ] `OAUTH-001C` 实现 Scope 白名单、授权撤销和失效事件；未经允许的 Scope 必须拒绝。
- [ ] `OAUTH-002A` 将 Token 放入 Secret Manager/KMS，禁止进入日志、Prompt、普通数据库和截图。
- [ ] `OAUTH-002B` 实现单连接 active token lease、轮换、过期、撤销和可追溯审计事件。
- [ ] `ACCOUNT-002` 实现账号健康检查、到期、负责人变更、政策变更和自动 `restricted`。
- [ ] `IAM-CORE-002` 强化后台用户 RBAC/ABAC、MFA、审批权限和发布权限分离；不改变核心内容权限模型。
- [ ] `ACCOUNT-003` 在队列领取前、平台调用前和回查前各检查一次 Kill Switch。
- [ ] `PLAT-001` 先接入一个官方平台；每个平台一张独立任务卡和独立能力矩阵。
- [ ] `PLAT-002` 先实现草稿/人工确认，再开启排程或有限发布。
- [ ] `PLAT-003` 完成 fake server、Sandbox、契约、回查、配额和权限失效测试。

### 阶段出口 Gate

- 真实账号主体、授权范围、负责人和证据完整率 100%。
- `(platform_id, external_account_id)` 唯一，外部 ID 不作为内部主键。
- 撤销授权后，系统停止新动作，已有任务进入人工处理。
- 首个平台至少完成一次真实草稿或受控发布，并能回查外部 URL/ID。
- 真实发布遇到未知结果时不会自动重复发布。

### 阶段 9：Analytics、Feedback Loop 和 Support

**建议时间**：P1，真实或模拟观测数据可用后 1–2 周  
**目标**：让结果真正回到下一轮选题、刷新、渠道和模型改进。

### 必须完成

- [x] `ANALYTICS-001` 定义规范事件：内容、资产、发布、互动、GEO、客服、QA、成本和风险。
- [x] `ANALYTICS-002` 统一 `Observation`，记录来源、时间、市场、语言、版本和可信度；M1 允许站点、QA、GEO 和人工/fake 数据。
- [x] `ANALYTICS-003` 建立发布成功率、人工介入率、版权拒绝率、翻译通过率、误答率、成本和线索归因。
- [x] `ANALYTICS-004` 建立 GEO_CONTENT 与 GEO_REGION 分开的指标和数据质量检查。
- [x] `FEEDBACK-CORE-003` 建立 `FeedbackItem`：观察、问题、影响、建议动作、负责人、截止时间和状态；支持 synthetic/manual Observation。
- [x] `FEEDBACK-CORE-004` 把反馈回写 TopicOpportunity 评分、Refresh Queue、Variant/Channel 策略和 Prompt Eval，但只生成 Recommendation。
- [x] `FEEDBACK-CORE-005` 实现 `FeedbackAction` 执行事实：批准、启动、完成、失败、取消、结果快照和幂等；默认只允许内部内容刷新/重排命令，不得绕过 Policy、审批或版本锁定。
- [ ] `FEEDBACK-LIVE-001` 账号接入后增加真实平台归因、互动窗口、平台成本和线索质量观察。
- [x] `FEEDBACK-EXP-001` 建立实验模型：假设、分组、指标、时间窗、样本、结论和回滚。
- [x] `SUP-001` 在此基础上实现评论/私信去重、意图识别、低风险草稿和人工升级；没有真实 Inbox 连接时只使用 `FakeInbox`/人工导入，禁止发送。
- [x] `SUP-002` 高风险客服强制转人工：退款、合同、医疗、法律、金融、KYC、申诉、版权、隐私和安全漏洞。

### 阶段出口 Gate

- 一条站点、QA 或模拟发布记录产生 Observation；真实平台指标在账号接入后再验收。
- Observation 能生成一个可分派的 FeedbackItem，并更新下一轮选题或刷新任务。
- 低风险客服草稿显示证据和审批历史，高风险样本 100% 转人工；若无 Inbox 连接，验收使用 FakeInbox，不能把人工导入结果写成真实平台指标。

### 阶段 10：试点、灰度和规模化

### 试点顺序

```text
Account-free Architecture MVP
→ Manual Export / Fake Platform
→ 1 个真实账号、1 个真实平台
→ 低频草稿
→ 受控排程
→ 有限发布
→ 第二个平台
→ 更多账号和市场
```

### 必须完成

- [ ] `PILOT-001` 建立单账号内容日历、责任人、替补、发布上限和停发条件。
- [ ] `PILOT-002` 连续运行 2–4 周，记录质量、成本、平台健康、客服和 GEO 波动。
- [ ] `PILOT-003` 每周复核政策卡、授权期限、Token 状态、失败任务和投诉。
- [ ] `PILOT-004` 执行权限、版权、提示注入、故障注入、死信重放、备份恢复和 Kill Switch 演练。
- [ ] `PILOT-005` 形成问题清单、改进任务、指标基线和 Go/No-Go 报告。

### 扩容门槛

- 账号真实性证据完整率 100%。
- 官方 API/官方工具使用率 100%。
- 明文凭证数量为 0。
- 高风险内容人工审核率 100%。
- 版权证据和发布追溯率 100%。
- 连续 4 周无重大平台警告。
- 发布成功率、翻译审校通过率、客服误答率和成本达到预设目标。
- Kill Switch、备份恢复和事故演练通过。

---

### 时间安排说明

不要把“12 周内完成全部真实发布能力”作为承诺。建议按能力和外部依赖排期：

| 里程碑 | 预计周期 | 是否依赖真实账号 | 结果 |
|---|---:|---|---|
| M1-Core Account-free Architecture MVP | 6–8 周（按单一纵向切片） | 否 | 底座、Topic、Provenance/Knowledge/Canonical、Variant/QA/Policy/Approval、Manual Export/Fake、核心观察 |
| M1-Plus 可选扩展 | 1–3 周 | 否 | 第一方知识站、GEO_CONTENT/GEO_REGION、Media/Asset、离线评测；不阻塞 M1-Core |
| M2 Distribution Pilot | 账号到位后 2–4 周 | 是 | 一个真实账号、一个官方平台、草稿或受控发布 |
| M3 Scale | M2 稳定后再定 | 是 | 更多平台、账号、媒体、客服和市场 |

如果账号获取延迟，M1 继续使用 Manual/Fake/Simulation，不停工，也不把模拟结果写成真实平台指标。

---

## 8. 横切安全、可靠性和维护清单

### 安全与权限

- [ ] 内部 IAM 与 Account IAM 分离。
- [ ] RBAC + ABAC 按组织、模块、账号、市场、风险和动作授权。
- [ ] Agent 工具白名单，读取、写入、审批和发布权限分开。
- [ ] PII、凭证、外部 HTML、评论、附件和代码进入隔离区。
- [ ] 代码在沙箱运行，不访问生产密钥。
- [ ] Token 短租约、轮换、撤销和离职自动处理。

### 可靠性

- [ ] 所有任务都有幂等键、租约、超时、重试上限、死信和重放入口。
- [ ] 任务状态、Outbox 和审计写入同一事务边界或有明确补偿机制。
- [ ] 429/5xx 退避；权限、版权、政策和验证码错误不重试。
- [ ] 数据库迁移使用 expand/contract；生产不依赖“回滚迁移”解决应用问题。
- [ ] 应用镜像支持回滚；灾难恢复后队列默认暂停，禁止旧任务自动重发。

### 数据质量与删除

- [ ] 每条指标定义名称、公式、时间窗口、数据源、去重规则和责任人。
- [ ] 每个外部 ID、版本号、市场和语言都有格式校验。
- [ ] 删除请求传播到数据库、对象、向量、缓存、导出包和索引。
- [ ] 备份中的删除采用标记和到期清理策略，并保留最小审计证明。

### 测试最低要求

- [ ] 单元测试覆盖每个状态机的合法/非法转换、Policy 合并、幂等键和版本规则。
- [ ] 集成测试覆盖数据库事务、Outbox、任务租约、人工任务到期、Scheduler 锁和重放。
- [ ] 契约测试覆盖 API、事件、ModelPort、PublisherPort、MetricsPort 和 Fake Adapter。
- [ ] E2E 测试覆盖 `TopicSignal→TopicBrief→Canonical→Variant→QA→Approval→Manual Export/Fake`。
- [ ] 安全测试覆盖 `org_id` 越权、提示注入、外部链接、PII/Token 泄露、Agent 工具越权和 Kill Switch。
- [ ] LLM 测试使用固定 golden set 和 Fake Model；真实模型只作为单独评测，不作为每次 CI 的不稳定依赖。
- [ ] 负载测试覆盖任务并发、渲染资源、第三方配额和成本上限；账号数不作为唯一容量指标。
- [ ] 页面和字幕执行可访问性检查；公开内容不能只存在于图片、Canvas 或 JS 动态结果中。

### 可维护性

- [ ] Prompt、模型、阈值、政策卡、术语、区域规则和适配器 mapping 都版本化。
- [ ] 任何跨模块变更先更新 contracts 和 ADR。
- [ ] 每个模块有 Owner、README、单测、契约测试和 Runbook。
- [ ] 不创建无边界 `utils`；公共代码必须属于明确 package。
- [ ] 每个发布版本带 changelog、迁移说明、风险、回滚方法和观测指标。

---

## 9. 交付物分级

### M1-Core：Account-free Architecture MVP

- [ ] 模块化单体、API/Worker/Scheduler、PostgreSQL、Outbox、任务表、审计和观测。
- [ ] Topic Intelligence、Provenance、Rights、KnowledgeCore、Canonical Content。
- [ ] 中英 Variant、QA、Policy Gate 和人工审批。
- [ ] Manual Export、Fake Adapter、幂等、重试、死信和重放。
- M1 反馈范围说明：`FEEDBACK-CORE-001` 定义 Observation/Feedback 契约，`FEEDBACK-CORE-002` 使用站点、QA、GEO、人工和 Fake Observation 生成可解释的刷新/重排 Recommendation；`FEEDBACK-CORE-003` 和 `FEEDBACK-CORE-004` 在阶段 9 完成完整回写和分派。此行是范围说明，不是新的任务卡。
- [ ] synthetic 全链路证据和测试报告。

### M1-Plus（可选，不阻塞账号接入）

- [ ] 第一方知识中心和可抓取页面。
- `GEO_CONTENT`、`GEO_REGION` 基础检查与 FakeGeo 离线采样。
- [ ] Media/Asset、字幕和离线评测。

**M1 不宣称**：真实平台发布、真实账号健康、OAuth 配额、平台审核和多账号运营能力。

### M2：Distribution Pilot

- [ ] 一个真实主体、一个真实授权账号、一个官方平台。
- [ ] OAuth/Vault、Scope、账号健康、回查、停发和撤销。
- [ ] 低频草稿或受控发布、真实平台契约测试和事故演练。

### M3：Scale

- [ ] 更多平台、媒体、客服、实验和归因。
- [ ] 只有达到拆分阈值后才引入独立服务、分析仓库、流平台或 Kubernetes。
- [ ] 通过 Go/No-Go 后再增加账号和市场。

---

## 10. 最终执行顺序

```text
1. 冻结范围、技术基线、风险和指标
2. 建模块化单体、契约、迁移、Outbox、审计和 Fake Provider
3. 建 Topic Intelligence 和编辑决策
4. 建 Provenance、Rights、KnowledgeCore 和 Canonical Content
5. 建 Variant、翻译、本地化、QA、Policy 和人工审批
6. 建第一方知识中心、GEO_CONTENT、GEO_REGION
7. 建 Media/Asset（可延期）
8. 建 DistributionTarget、DistributionTargetVersion、PublicationIntent、Manual/Fake Adapter
9. 用 synthetic 数据跑通并反复重放整条链路
10. 用站点、QA、GEO、人工和 Fake Observation 跑通 FEEDBACK-CORE
11. 账号到位后再做 AccountConnection、OAuth、Vault 和首个平台
12. 接入真实平台 Observation、FEEDBACK-LIVE 和低风险 Support
13. 低频试点、复盘、灰度和规模化
```

### M1 必须跑通的验收场景

```text
Given：10 条带来源和许可信息的 TopicSignal，1 个已批准 TopicBrief，1 个可用 SourceSnapshot
When：创建 CanonicalContentVersion v1，绑定 Claim/Evidence，生成 zh-CN 和 en-US Variant
And：执行 QA、GEO_CONTENT、GEO_REGION 和人工审批
And：创建 `manual_export` PublicationIntent，生成私有 ExportPackage
And：从同一 Variant 创建独立的 `simulation` PublicationIntent（使用 synthetic TargetVersion），用 FakeOfficialAdapter 注入一次 429 和一次未知结果
Then：所有状态转换合法且可在 AuditLog 中按 trace_id 追踪
And：重复消费不产生第二个模拟平台对象
And：未知结果进入人工核查，不自动再次发布
And：写入 fake/manual Observation，生成一个 FeedbackItem 和刷新建议
And：整个流程不读取真实 Token、不调用真实平台、不修改已审批版本
```

这套顺序的核心是：**内容、知识、证据和工作流先独立成立；账号只是分发执行时插入的连接；平台差异被适配器隔离；每个对象有自己的生命周期；所有结果都能反馈到下一轮选题和刷新。**



