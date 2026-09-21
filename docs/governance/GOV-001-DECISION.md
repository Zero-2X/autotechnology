# GOV-001 决策记录：首个 AI 技术内容纵向切片

## 决策

首个垂直领域锁定为 **AI 技术与应用工程**，首期重点覆盖 LLM、RAG、Agent、LangChain/LangGraph、Prompt、模型评测、AI 应用架构、部署、可观测性、安全、隐私、版权和合规工程。

语言锁定为 `zh-CN` 和 `en-US`，首期内容形态为文本，知识站使用第一方站点，分发只允许 `manual_export` 和 `simulation`。

## 选择依据

1. 用户的八项总体要求都围绕 AI 技术资料、内容生产、跨语言分发和反馈优化展开。
2. LLM/RAG/Agent/LangChain/LangGraph 是当前架构最直接的业务示例，能验证 Topic、Knowledge、Canonical、Variant、QA、Policy、Approval 和 Feedback 的完整链路。
3. 文本优先能在没有真实账号和生产级媒体基础设施时完成可验收的 M1-Core。
4. `manual_export` 和 `simulation` 保留未来真实账号接入所需的 PublicationIntent、TargetVersion、幂等和回查边界。

## 总体要求到首期范围的映射

| 总体要求 | 首期落点 | 后续阶段 |
|---|---|---|
| 自动发现和筛选选题 | TopicSignal、TopicOpportunity、TopicBrief | Feedback 回写和实验 |
| 采集资料并建知识库 | Source、Rights、Evidence、KnowledgeCore | Retriever 和增量刷新 |
| 生成、整合、翻译、本地化 | CanonicalContent、Variant、Production | 更多语言和区域 |
| 事实、版权、质量、合规检查 | QA、Policy、Approval | 平台政策和真实数据 |
| 图片、视频等多媒体 | 设计为 M1-Plus/M3 Asset 流程 | 生产级渲染和媒体平台 |
| 国家、语言、平台适配 | `zh-CN/en-US`、GEO_CONTENT、GEO_REGION、Fake Adapter | 真实平台适配器 |
| 账号发布、客服、监测 | 保留 Distribution/Support 契约，首期不执行真实副作用 | M2/M3 |
| 效果反馈和持续优化 | Observation、FeedbackItem、Recommendation | 真实平台归因和实验 |

## 不变式

- 范围文件不保存账号、Token、Cookie、密钥或真实平台 ID。
- 首期没有真实账号；任何真实 OAuth、Token、平台 HTTP 和真实指标都必须等 M2。
- 任何新增语言、内容形态、国家或平台都必须新建版本并重新执行 Policy、Rights、QA 和 Approval。
- 已锁定的 `scope_version: 1` 不能原地编辑；变更必须创建新版本并记录 supersedes。

## 验收证据

- 机器范围文件：`docs/governance/vertical-scope.yaml`
- 契约：`packages/contracts/jsonschema/vertical-scope.schema.json`
- 合并契约：`packages/contracts/jsonschema/governance.schema.json`
- 测试：`tests/contract/test_gov_001_scope.py`
- 迁移契约测试：`tests/contract/test_gov_001_migration.py`
- 范围文件 SHA-256：`4a663d60207bb542f14d290b6a1235c046a5fa193df9f9421fa56be5d2f3ce52`
- 迁移版本：`packages/db/migrations/versions/20260915_gov_001_governance_scope.sql`
- 审计事件：本决策由 `GOV-001`、`team/governance`、`locked_at` 和 scope 文件内容哈希共同标识；后续实现阶段应将相同标识写入 AuditLog。
