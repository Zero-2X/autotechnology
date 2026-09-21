# 开发进度复核 — 2026-09-21

## 全部范围

- V2.4：157 项任务，137 done、20 planned。阶段 8、FEEDBACK-LIVE-001 和 Pilot 尚未验收。
- V3：38 项 Graph/LC 任务中 34 done、4 blocked。blocked 项均依赖 EXT-ACCOUNT-001，
  其余 account-free 编排底座已完成本地验收。
- 当前完整交付尚未完成；既有 done 状态也不代表生产环境已经部署或验收。

## 本轮代码

Account/OAuth 的本地连接、证据、Scope、PKCE、State、secret reference、lease、
健康与 Kill Switch 检查保留；专项证据见 ACCOUNT-OAUTH-IMPLEMENTATION-READINESS.yaml。

新增 IAM 的 fixture MFA 与审批/发布授权检查。发布授权仅接受服务已登记且未修改的
审批，绑定组织、请求人、目标对象与 distribution 类型；实时复核执行者、审批者的
权限和状态，审批者与执行者分离。此实现是开发环境 fixture，并未实现生产 TOTP、
WebAuthn、会话级 step-up、持久化授权记录或身份提供商接入。

新增 `adapters/fake/official_server.py` 的 FakeOfficialServer：本地草稿、发布、配额、Scope、权限撤销、回查和 Fake 指标。
同租户不同平台账号之间禁止读取或发布对方对象；丢失响应后平台对象仍只创建一次，
同键重放复用结果，新键二次发布被拒绝。该服务没有官方 HTTP/SDK 接入。

Live Feedback 增加归因、互动窗口、平台成本和线索质量四类 Observation 转换。
通过注入的 ObservationPort 复用 Analytics 公开命令；移除了跨模块内部导入，
也移除了重复的本地 Observation 存储实现。缺失租户或连接绑定的证据被拒绝；
部分写入失败后可用原幂等键恢复，完成后才登记窗口审计。

V3 account-free 编排底座已实现：`orchestration/` 提供版本化 GraphRegistry、
GraphRunner、租约、内存/SQLite Checkpointer、最小 State、状态迁移、Reducer、Router、
HumanTask interrupt/resume、ReplayGuard、TaskJob 映射、内容纵向图、反馈桥接、拓扑检查、
Golden Set 评估和 Trace/Audit/Outbox 投影。`integrations/langchain/` 提供不绑定供应商
安装的 ModelPort/FakeModel、Prompt 版本、结构化 Parser、租户/证据过滤 Retriever 和
带 Schema/超时/副作用门禁的 ToolRegistry；组合入口通过 Port 注入，Domain 不导入 SDK。
Graph State Schema、GraphRun/Attempt/Node/Interrupt/Model/Prompt/Retrieval/Tool Schema
已加入 contracts，V3 任务精细化检查已能正确读取独立注册表。`requirements-v3.lock`
锁定 LangGraph/LangChain provider profile，`orchestration/langgraph_adapter.py` 提供真实
StateGraph 组合入口；生产账号和部署托管 PostgreSQL 仍需外部环境证据。

## 验证

专项命令：

```text
python -m pytest tests/unit/feedback/test_live_feedback_service.py tests/contract/test_feedback_live_contract.py tests/unit/iam tests/unit/platform_adapter tests/unit/distribution_oauth tests/unit/distribution_account tests/contract/test_oauth_contracts.py tests/integration/test_account_connection_models.py -q
```

结果：42 passed。涵盖实际 ObservationService 的失败恢复、审批伪造/挪用拒绝、
权限撤销、账号隔离、Scope 拒绝与未知结果去重。

静态检查：architecture_errors=0、secret_findings=0、schema_errors=0；
迁移图 revisions=125、head=20260921_sup_002、errors=0；任务卡引用 checked=157、errors=0。
全量回归：**1121 passed**，1 个 Starlette 弃用警告；失败为 0。

V3 开工命令修复：`check_task_card_precision.py --task GRAPH-GOV-001 --strict`
现会选择 V3 注册表；此前只读取 V2.4，导致合法 GRAPH/LC 任务报 unknown。
新增专项测试验证独立注册表选择、规格缺失拒绝及未知任务拒绝，1 passed。

V3 编排专项：**24 passed**；覆盖 GraphRunner 幂等/租约/Checkpoint/人工等待/恢复、
State 敏感字段和大小门禁、并行冲突、ReplayGuard provider 幂等、TaskJob 租户映射、
内容图节点、Feedback bridge、拓扑回归、FakeModel/Prompt/Parser/Retriever/Tool 端口。
契约 Schema、架构和 secret 门禁均通过。

全量检查识别出 Fake 服务误放真实平台目录；已迁回既有 `adapters/fake`，
未修改目录保护测试。目录基线及 Fake 平台回归合计 12 passed。

## 接下来的实施顺序

1. 保持 V3 任务卡、注册表和交付证据同步；account-free 的 Graph/State/LC 实现已完成，
   CI 会安装并校验 `requirements-v3.lock` 后运行真实 LangGraph 组合测试。
2. V2.4 账号任务仍为 planned；本地 fixture 准备不替代官方适配器、生产 Vault/MFA、
   持久化接入、真实 Sandbox 回查和平台指标验收。
3. EXT-ACCOUNT-001 仍 missing，缺真实主体、联系人、官方应用/Sandbox、批准 Scope 与
   八类证据。生产模型和存储外部依赖同样仍 missing；其本地替代只用于开发验收。
4. Pilot 必须有真实运行证据、2–4 周观察、周复核、演练和 Go/No-Go；当前未执行，
   需要 EXT-ACCOUNT-001 和部署环境状态变化后继续。

回滚边界：本轮新模块及 IAM 增量未新增数据库迁移，生产接入仍未开放。
