# ADR-001：模块化单体、部署基线与 LangGraph 编排边界

**状态**：Accepted  
**日期**：2026-09-15  
**适用范围**：AI 跨境技术内容自动化工作流 V3

**机器可读基线**：`docs/governance/tech-stack-baseline-v1.yaml`

## 决策

采用 **Modular Monolith + API/Worker/Scheduler + LangGraph** 的组合：

- **LangGraph** 只负责有状态工作流的编排：节点顺序、条件路由、重试边界、人工中断、恢复和运行上下文。
- **LangChain Core/Provider Packages** 负责模型调用、Prompt、Retriever、Tool、结构化输出解析和文档转换。
- **Domain/Application 层**继续保存 Topic、Rights、Knowledge、Canonical、Variant、QA、Policy、Approval、Distribution、Feedback 等业务规则。
- **PostgreSQL** 是业务事实、不可变版本、审批、审计和 Outbox 的真源。
- **LangGraph Checkpointer** 只保存图运行所需的 checkpoint，用于恢复和人工审批续跑；不替代业务数据库。
- **Scheduler** 只创建或唤醒 GraphRun，不在图内实现定时调度。
- **外部平台副作用**只能由 Distribution Adapter 执行，并且必须先有 PublicationIntent、PolicySnapshot、幂等键和 Kill Switch 检查。

## 模块化单体与部署基线

首期使用一个仓库、一个领域模型和一套共享契约，但按运行职责提供独立入口：

- `apps/api`：HTTP、认证后的 TenantContext、输入校验、幂等和并发版本检查。
- `apps/worker`：领取 TaskJob、运行 GraphRun、处理租约、重试、死信和 Outbox；首个纵向切片使用 PostgreSQL polling，不依赖 Redis。
- `apps/scheduler`：只创建或唤醒任务，不实现领域规则，也不在调度器内复制图逻辑。
- `apps/web-console` 与 `apps/knowledge-site`：分别作为运营/审批后台和第一方知识站构建入口；它们通过公开 API/契约访问业务能力。

这些入口可以作为独立进程扩缩容，但仍属于同一个模块化单体。只有满足清单中的独立扩缩容、故障隔离、合规驻留或团队所有权阈值，并新增 ADR 后，模块才可拆成独立服务。

## 固定技术栈

- Python 3.12、FastAPI、SQLAlchemy 2、Alembic。
- PostgreSQL 保存业务事实、不可变版本、审批、AuditLog、Outbox 和生产 Checkpointer。
- S3 兼容私有对象存储保存正文、媒体和原始载荷，必须带租户命名空间、对象哈希与删除传播策略。
- LangGraph 负责运行编排；LangChain Core 加一个供应商集成包负责模型组件。
- OpenTelemetry 提供 tracing，Prometheus 兼容接口提供运行指标。
- pytest 覆盖 unit、contract、integration、e2e 和 replay；CI 使用 Fake Provider 与 synthetic fixture。
- Redis 是 P1 可选缓存、短锁和速率限制设施，不保存业务事实，也不阻塞 M1-Core。

具体组件、版本策略、环境范围和升级证据以机器可读基线为准；实现阶段必须用依赖锁文件固定精确版本。

## 环境与部署边界

- dev/test 只能使用 Fake Model、Fake Storage、Fake Adapter、FakeGeo、FakeInbox 和 synthetic fixture；不得要求真实账号或真实平台凭证。
- staging 可以进行官方 Sandbox 或契约测试，但真实连接必须等待 M2 Go/No-Go 和授权证据。
- production 的业务事实与 checkpoint 可以共用 PostgreSQL 集群，但必须使用不同 schema/table namespace、权限和备份策略；checkpoint 不能成为审批或审计真源。
- 所有环境默认私有网络和最小权限；平台 SDK/HTTP 只能从 Distribution Adapter 发起。

## 初期明确排除

首期不引入 LangGraph Server、Temporal、Kafka、Kubernetes、多个模型供应商或多个真实平台。新增技术必须有明确问题、Owner、ADR、契约兼容测试、成本评估和回滚证据；“未来可能增加账号”本身不构成引入分布式基础设施的理由。

## 版本和升级规则

- 每个运行依赖固定主/次版本范围，并在实现锁文件中固定精确版本与哈希。
- 常规依赖按 30 天窗口评审；安全修复最迟 7 天内评估和落地，若无法升级必须记录风险接受与补偿控制。
- LangGraph/LangChain 的具体兼容窗口由 `GRAPH-GOV-002` 冻结；GOV-006 只确定架构技术类别和部署边界。
- 升级必须提供兼容测试、锁文件差异、迁移/回滚评估以及成本和可观测性影响。

## 为什么适用

本项目包含长流程、分支、人工审批、失败后恢复、版本锁定和反馈回写。LangGraph 能把这些运行时行为显式化，减少手写状态机的重复代码。LangChain 能统一模型、Prompt、Retriever 和结构化输出接口，便于替换供应商和做离线评测。

## 明确不交给 LangGraph/LangChain 的内容

1. 版权事实、证据和许可判断。
2. Policy 决策、审批事实、账号授权、Token/Vault 管理。
3. 数据库事务、版本不可变规则、Outbox 一致性。
4. 外部平台最终发布结果、平台配额和账号健康事实。
5. 完整正文、Token、PII 或其他大对象的长期存储。

## 运行约束

- Graph State 只存 ID、版本号、状态、引用、错误和恢复信息；正文和二进制内容存对象库/数据库。
- 每个 Node 只能调用模块公开的 Use Case/Port，不得直接写 ORM 或调用平台 SDK。
- Agent/LLM Node 只能产生候选、草稿、报告或 HumanTask；不能直接发布。
- 所有副作用都通过 Outbox/Adapter，使用 `PublicationIntent` 和 provider 幂等键。
- `interrupt()` 恢复时必须重新读取最新版本、Policy、Rights、Region 和 Kill Switch。
- Graph 重放必须证明不会重复创建外部对象；未知外部结果进入人工核查。
- 第一阶段固定一个模型供应商、一个向量库实现和一个 Fake Provider；真实平台延后到 M2。

## 被否决的方案

- **只用 LangChain Agent**：隐式循环和副作用边界难以审计，不适合本项目的审批与发布链。
- **LangGraph 取代领域层**：会把业务事实塞进可变运行状态，导致审计、迁移和回放困难。
- **一开始拆微服务/上 Kubernetes/Temporal/Kafka**：当前账号数量和吞吐不足以抵消运维复杂度。
- **首期同时接入多个模型和平台**：无法稳定评估质量、成本和故障责任。

## 迁移策略

V2.4 继续作为业务契约和安全规则基线；V3 只增加编排层和 LangChain 组件。先实现无账号的文本纵向切片，再接入真实账号。任何 V2.4 任务的 Policy、Approval、Audit、Outbox、版本不可变规则不得因引入 LangGraph 而删除或弱化。

## Go/No-Go 门槛

进入 M1-Core 前必须通过：

- 图状态 Schema、节点输入输出 Schema 和版本策略已冻结。
- 一个 GraphRun 可从 checkpoint 恢复并完成 `TopicSignal→Canonical→Variant→QA→Approval→Manual Export/Fake`。
- 重放、重复消费、unknown 外部结果和人工中断均有自动化测试。
- Trace ID 能贯穿 API、GraphRun、Node、Model Call、Outbox 和 AuditLog。
