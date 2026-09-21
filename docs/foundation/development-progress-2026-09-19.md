# 开发进度复核 — 2026-09-19

机器注册表包含 157 项任务。`CANON-004` 状态漂移已关闭，`CANON-005`、`CANON-006`、`AGENT-CORE-005A`、`AGENT-CORE-005B`、`AGENT-CORE-005C`、`AGENT-CORE-005D`、`AGENT-CORE-005E`、`MODEL-001`、`EVAL-001`、`MODEL-003`、`SITE-001`、`SITE-002`、`SITE-003`、`SITE-004`、`GEO_CONTENT-001`、`GEO_CONTENT-002`、`GEO_CONTENT-003`、`GEO_REGION-001`、`GEO_REGION-002`、`PROD-001`、`PROD-002`、`PROD-003`、`PROD-004`、`QA-001`、`QA-002`、`QA-003`、`POLICY-001`、`POLICY-002`、`APPROVAL-001`、`APPROVAL-002`、`DIST-001`、`DIST-002`、`DIST-003A`、`DIST-003B`、`DIST-004`、`DIST-005A`、`DIST-005B`、`DIST-006A`、`DIST-006B`、`DIST-006C`、`DIST-007`、`DIST-008A`、`DIST-008B`、`DIST-009`、`DIST-010`、`DIST-011` 与 `FEEDBACK-CORE-002` 已实现；同步注册表后为 117 项 `done`、40 项 `planned`，没有 `blocked`。

## 本轮关闭的问题

- `CANON-004` 的代码、任务卡和迁移已经存在，但开发清单仍为未勾选，机器注册表仍为 `planned`，注册表仍引用不存在的 planned migration，且缺少专项证据文件。已同步清单、生成器、注册表、contract/migration manifest 和 `CANON-004-EVIDENCE.yaml`。
- `FOUND-000` 清点报告指纹因上一轮文件变化失效，已重新生成并通过只读校验。
- 全量回归发现清点器会扫描 pytest 正在使用的 `.tmp` 工作目录并在 Windows 上触发占用错误；已把该瞬态目录加入清点忽略集并新增回归用例。
- 新增 `CANON-005` 的 freshness check 与 refresh queue，补齐版本过期、事实冲突、刷新入队和 Worker 租约生命周期；历史版本保持追加式不可变。
- 架构表所有权已登记 `canonical_freshness_checks` 和 `canonical_refresh_queue`，避免跨模块写入误报。
- `CANON-006` 建立租户范围的只读 lineage 查询，沿 Canonical 版本、Variant、Asset 和 Publication 查询 Port 组装确定性节点与边。下游实体服务尚未实现时返回 `unavailable_stages`；受控 Port 测试覆盖完整链路和无素材文本发布。
- 查询快照、摘要、actor 与 trace 追加保存在 `canonical_lineage_queries`，同租户同幂等键重放首次结果；跨租户和跨根下游投影被拒绝。历史版本可查询且标记为非当前。
- `AGENT-CORE-005A` 基于现有 AgentRunner 实现 Planner Agent。它按租户读取锁定的 TopicBrief，输出受 Schema 约束的 Topic/Workflow Plan；工具白名单为空，步骤依赖校验阻止越序建议，幂等重放不重复模型调用。模型调用与运行证据仅以哈希和元数据进入现有内存 Ledger。
- `AGENT-CORE-005B` 基于 AgentRunner 实现 Research Agent；只读装载 usable SourceSnapshot 受控摘录，逐项校验候选引用，输出候选事实和待核查项并强制人工复核，不创建 Claim 或修改 KnowledgeCore。
- `AGENT-CORE-005C` 基于 AgentRunner 实现 Rights/Provenance Agent；只读校验不可变 RightsRecordVersion，把模型线索约束到版本已登记引用及受控摘录，输出许可线索、候选范围和缺口并固定最终结论为 deferred，不验证版本、不写授权决定。
- `AGENT-CORE-005D` 基于 AgentRunner 实现 Transform Agent；只读装载 Canonical 版本，生成待人工复核的 Variant 草稿，逐项保留 Claim、术语、数字、代码和链接映射，不创建持久化 Variant 或发布事实。
- `AGENT-CORE-005E` 基于 AgentRunner 实现 QA Agent；只读运行确定性 QA 投影，逐项解释 finding 并提出 `qa_review` 人工任务，固定 review_only，不批准、不发布、不创建 Approval。
- `MODEL-001` 增加经完整供应商证据门禁的外部 ModelPort：仅限 dev/staging 和批准地域，安全 secret ref 存在时才走注入式 transport；缺凭证或暂时故障确定性回退 Fake，并记录条款、地域、实际 provider、成本、耗时和降级原因。
- `EVAL-001` 增加租户隔离的 Prompt、synthetic golden set 与回归阈值追加版本；离线运行只经 Model Gateway，按 case 保存输出/期望 hash、ModelCall、成本和耗时，对同一 dataset baseline 检查质量下降与成本增长，达到绝对成本上限后停止新调用。
- `MODEL-003` 增加版本化 BudgetPolicy、org/task/model 与 UTC task/day/month 累计账本；Gateway 在 Provider 前并发预占 request budget，按实际成本结算，超限返回 `BUDGET_EXCEEDED`、不调用 Provider 并写入 deny 审计。
- `SITE-001` 建立租户隔离的 SitePage 稳定根和不可变 SitePageVersion 投影；规范化 URL/locale，保存作者、审校者、更新时间、方法、证据、限制、FAQ 和可见内容快照。Repository Port 不直接写 SQL，数据库迁移以复合外键、唯一版本号和追加式触发器保护历史。
- `SITE-002` 增加离线、确定性的 SSR/预渲染投影：安全转义 HTML、canonical、按 locale 的 hreflang 与 x-default、sitemap、RSS/Atom、robots；公开页面选择 ready/published，sitemap/feed 仅使用 published，保存 SitePublication manifest/哈希并支持租户隔离和幂等重放。
- `SITE-003` 增加离线 JSON-LD 投影：从同一 SitePageVersion 可见快照生成 Article/TechArticle、Organization 和 Person 节点，安全转义脚本分隔符；VideoObject 同时要求阶段 6 与已批准同租户视频资产。结果、manifest、请求和输出哈希可重复，拒绝路径只记录错误码与版本 ID。
- `SITE-004` 增加离线站点质量审计：页面 HTTP 200、断链/fragment、重定向环与跳数、LCP/CLS/INP/TTFB/总字节预算、非装饰图片 alt、逐媒体字幕、SSR 主内容和可选动态 DOM 一致性均输出稳定检查码。默认不访问网络或浏览器，未知观测转人工复核；持久层只追加保存哈希、指标和检查，不保存 HTML、DOM、响应正文或凭证。
- 发现 `PROD-001` 任务卡仍要求依赖 Transform Agent，与开发清单、机器注册表的 M1 `TransformPort` 规则实现不一致。已修正任务卡并实现 `RuleTransformPort`；生成的是待人工复核的瞬态 Variant 草稿，持久化 `ContentVariant`/`VariantVersion` 留给 `PROD-002`。
- `PROD-002` 建立稳定 `ContentVariant` 根、追加式 `VariantVersion`、幂等命令和审计事件。只读 Canonical 与 Region Port 审核来源/地区；旧版不可更新，当前指针需 expected version。新增租户范围的 Variant lineage Port，并与 `CANON-006` 查询集成验证。
- `PROD-003` 追加租户范围的不可变术语表版本与已批准翻译记忆；内存查询仅按源哈希查 TM。保护检查逐块报告数字、代码、URL、产品名和术语缺失，不自动批准或发布。
- `PROD-004` 增加 `RegionRuleService`，在 Variant 写入前检查有效期、locale、market、单位、货币、时区、数据地域、平台资格、受限主题和必需披露；区域规则阻断时事务不写入 Variant 事实。
- `QA-001` 增加只读 `QAService`，按租户校验 Variant/Canonical 投影、Claim/Evidence 状态和时效、quote/locator/source snapshot、Claim-Evidence 关联、source map 映射，以及数字、代码和 URL 保护；术语检查通过可替换 Port 接入，报告支持稳定排序、幂等重放和审计哈希。
- `QA-002` 增加只读 `AdvancedQAService`，按阈值执行确定性相似度、既有 Variant 重复度和重复块检查；AI/广告 disclosure 与素材权利检查支持可替换评分/权利 Port、租户隔离、有效期、地域、语言、媒体和用途约束，临时 Port 故障转人工复核。
- `QA-003` 增加 `SandboxService`，仅接受结构化 argv，在临时工作区用最小环境执行白名单命令；静态阻断 shell/网络/生产/secret 路径和内容，校验依赖锁哈希与资源上限，超时/失败保留私有输出哈希，并按输入、镜像和命令集复用可复现结果。
- `POLICY-001` 增加 `PolicyGateService`，校验版本化 PolicySnapshot 的租户、subject、有效期和 hash 字段，按风险、QA、Rights、Region、审批、发布模式、账号、数据处理和模型事实确定性聚合 PolicyDecision；deny 优先于 manual_review，未知状态不自动放行，决策支持幂等重放和审计哈希。
- `POLICY-002` 增加 `PolicyExpiryService`，按 Snapshot 的 effective/expiry/review_due/status 生成生命周期决策；到期复核自动切换所有副作用 policy 为 manual_review、创建租户范围且幂等的 policy_review HumanTask，并在审计中记录阻断，过期/撤回/未生效直接 deny。
- `APPROVAL-001` 增加 `ApprovalDeskService`，冻结输入快照哈希、稳定版本 diff、证据面板和风险原因；支持分派、批注、expected version、1/2 人 quorum、追加 ApprovalDecision、期限和 override 到期撤销，所有命令按租户幂等重放。
- `APPROVAL-002` 补齐 reviewer authorization Port、创建人隔离、(approval, reviewer) 唯一投票和 R3/R4 自动双人 quorum；公共 Decision Schema 保持闭合，评论/evidence 继续由审批台视图保留。
- `DIST-001` 建立租户范围的 DistributionTarget、不可变目标版本和 PublicationIntent；manual export 只生成私有 ExportPackage，simulation 通过无网络 FakePublisher 写入 simulated PublicationRecord 与事件，Policy/Approval 不满足时不生成投递事实。
- `DIST-002` 在 FOUND-010 Port 形状上补齐 DistributionPortSet 和 PublisherCapabilityRegistry；四个端口职责独立，能力版本不可覆盖，幂等重放、租户隔离、审计和事件契约均已验证。
- `DIST-003A` 增加确定性的 ManualAdapter；它将标题、正文、媒体、标签、披露、检查清单和证据摘要组装成私有 manifest 和 ExportPackage，拒绝公开媒体 URL，并写入导出事件与审计摘要。
- `DIST-003B` 增加 ExportPackageStorage 和 InMemoryPrivatePackageStore；包与文件按租户私有引用登记，下载 URL 使用有上限的 HMAC TTL，过期/撤回、If-Match、篡改签名和跨租户读取均阻断并保留审计。
- `DIST-004` 增加无凭证 FakeOfficialAdapter；能力、草稿、媒体上传、排程、模拟发布、指标和固定错误码均可离线复现，DeliveryAttempt/PublicationRecord 经过契约校验。
- `DIST-005A` 增加 CapabilityMatrix 和 adapter-only 字段映射；核心 payload 只接受标准字段，矩阵版本按租户不可覆盖并追加事件审计。
- `DIST-005B` 增加 RetryPolicyService；配额时间窗、Retry-After、transient/exhausted/deterministic/unknown 分类和人工升级事件均按租户幂等记录，不执行隐式重试。
- `DIST-006A` 增加 DeliveryIdempotencyService；PublicationIntent、DeliveryAttempt 和 EventEnvelope 均按 tenant/payload hash 去重，重复消费不再次调用 handler，冲突 attempt 和跨租户事件被拒绝。
- `DIST-006B` 增加 PublicationReconciler；上传、确认、发布、失败和未知回查均校验 DeliveryAttempt/PublicationRecord，已发布状态不可回退，未知结果必须保留原因且不伪造成功。
- `DIST-006C` 增加 DeliveryDeadLetterService；未知结果创建唯一 unknown_result HumanTask，达到重试上限进入死信，人工解析要求证据，单任务重放保留原幂等键且不触发外部副作用。
- `DIST-007` 扩展 DistributionService 的四种唯一交付模式；manual_export 保持私有包、simulation 使用 FakePublisher，draft_only/authorized_api 校验连接后进入 queued attempt，不调用真实平台。
- `DIST-008A` 补齐 Target/TargetVersion 快照不可变与生命周期命令；Target 字段变更拒绝原地更新，版本激活/退役使用 ETag，退役需替代版本或已退役 Target。
- `DIST-008B` 增加 global/platform/account/target Kill Switch 与 Intent mode gate；暂停模式在创建 DeliveryAttempt 前阻断，manual_export 保持无外部副作用的私有导出路径。
- `DIST-009` 增加 ManualExportVerticalSliceService，串联 Canonical freshness、Variant approved、QA passed、Approval approved、Policy allow、PublicationIntent 和私有 ExportPackage。
- `DIST-010` 增加 FakeDeliveryWorkflowService，把 FakeOfficialAdapter、RetryPolicy、DeliveryIdempotency、PublicationReconciler 和 DeadLetterService 串成无凭证发布回归；覆盖模拟成功、暂时失败、重试耗尽、死信、人工重放和重复事件消费。
- `DIST-011` 增加独立 WebhookPort 和 FakeWebhookPort；fixture ingress 覆盖 HMAC 验签、EventEnvelope/租户校验、外部事件去重、处理失败死信和仅限已验签收据的人工重放，全程不接真实 Webhook。
- `FEEDBACK-CORE-002` 增加 FeedbackRecommendationService；只读版本化阈值把 fake/manual Observation 转成带 rule/scoring version、阈值和证据的 refresh/reprioritize 提案，raw/未触发数据仅记录事实，不创建 action 或修改生产规则。
- `GEO_CONTENT-001` 增加离线确定性的内容就绪规则，覆盖实体可见性、Claim/Evidence 双向追溯、来源与权利状态、freshness、canonical 和 robots；空知识或不可验证来源不会被标记为 citation-ready。
- `GEO_CONTENT-002` 增加租户范围的 Prompt Fixture、`created → active → retired` 追加式生命周期与离线合规采样 Port；采样记录 mention、citation、position、correctness，未知/人工复核状态不会被误判为通过。
- `GEO_CONTENT-003` 增加 FakeGeo 离线多次采样、结果哈希去重和置信度汇总；Run 保留原始 Fixture hash，固定标记为 estimated，全部未知样本进入 failed/人工复核，且不持久化原始答案正文；运行入口现在还校验注入式 Fixture 的租户和 ID 绑定，迁移层阻断未就绪页面、乱序位置和任意 payload。
- `GEO_REGION-001` 已完成租户隔离的 RegionProfile/RegionProfileVersion 服务、闭合契约、draft→active→retired 生命周期、幂等和 If-Match/current-pointer 并发保护；SQLite/PostgreSQL 迁移重复执行复合租户引用、身份不可变、状态转换和 SitePageVersion 绑定，专项 24 passed，区域回归 42 passed。
- `GEO_REGION-002` 已增加精确 RegionProfileVersion 资格决策、稳定拒绝码、地区禁用与 hreflang 过滤，以及从不可变版本派生的保留/删除计划。站点渲染在生成 HTML、sitemap、RSS 和 Atom 前失败闭合地过滤不合格页面；迁移只追加保存非敏感决策投影，不改写区域或页面事实。
- GEO Fixture 的幂等 hash 排除时钟、actor 和 trace，并校验持久投影完整性；跨租户嵌套前置快照、篡改 Fixture、错误采样器绑定、空退役原因和冲突版本均被拒绝并留下租户可查询审计。

## 验证

- CANON-006 专项：5 passed；Canonical 与迁移升级回归：20 passed。
- Planner 专项：4 passed；Agent 与迁移升级回归：22 passed。
- Research Agent 专项、Agent 单元与集成回归：132 passed。
- Rights/Provenance Agent 专项、Agent 单元与集成回归：137 passed。
- Transform Agent 专项、Agent 单元与集成回归：142 passed。
- QA Agent 专项、Agent 单元与集成回归：147 passed。
- MODEL-001 专项、Model Gateway 单元与集成回归：129 passed。
- EVAL-001 专项：7 passed；Evaluation 单元与全部集成回归：126 passed。
- MODEL-003 专项：16 passed；Model Gateway 单元与全部集成回归：136 passed。
- SITE-001 专项：14 passed；站点单元与全部集成回归：134 passed。
- SITE-002 专项：20 passed；SITE-001/SITE-002 迁移与站点集成回归：20 passed。
- SITE-003 专项：6 passed；SITE-001/SITE-002/SITE-003 站点单元与迁移集成回归：27 passed。
- SITE-004 专项：14 passed；Knowledge Site、可访问性和迁移模块回归：43 passed。
- PROD-001 单元与真实 Canonical Port 集成：5 passed。
- PROD-002、Production 单元与迁移升级回归：17 passed。
- PROD-003、Production 全部专项与迁移升级回归：22 passed。
- PROD-004、Production 全部专项与迁移升级回归：28 passed。
- QA-001 专项：4 passed；QA、Production 与迁移升级回归：31 passed。
- QA-002 专项：7 passed；QA、Provenance 与迁移升级回归：35 passed。
- QA-003 专项：11 passed；QA、Provenance 与迁移升级回归：39 passed。
- POLICY-001 专项与治理契约、迁移回归：20 passed。
- POLICY-002 专项与治理契约、迁移回归：23 passed。
- APPROVAL-001 专项、Approval 契约与迁移回归：26 passed。
- APPROVAL-002 专项、Approval 契约与迁移回归：27 passed。
- DIST-001 专项、Distribution/Platform 契约与迁移回归：39 passed。
- DIST-002 专项、Distribution/Platform 契约与迁移回归：42 passed。
- DIST-003A 专项、Distribution/Platform 契约与迁移回归：45 passed。
- DIST-003B 专项、Distribution/Storage 契约与迁移回归：118 passed。
- DIST-004 专项、Distribution/Platform 契约与迁移回归：42 passed。
- DIST-005A 专项、Distribution/Platform 契约与迁移回归：44 passed。
- DIST-005B 专项、Distribution 契约与迁移回归：43 passed。
- DIST-006A 专项、Distribution 契约与迁移回归：45 passed。
- DIST-006B 专项、Distribution 契约与迁移回归：48 passed。
- DIST-006C 专项、Distribution/核心契约与迁移回归：53 passed。
- DIST-007 专项、Distribution 单元与集成回归：142 passed。
- DIST-008A 专项、Distribution 单元与集成回归：145 passed。
- DIST-008B 专项、Distribution 单元与集成回归：149 passed。
- DIST-009 专项、Distribution 单元与集成回归：151 passed。
- DIST-010 专项、Distribution 单元与集成回归：153 passed。
- DIST-011 专项、Distribution 单元与集成回归：158 passed。
- FEEDBACK-CORE-002 专项、Feedback 单元与集成回归：121 passed。
- GEO_CONTENT-001 专项：29 passed；包含实体可见性、Claim/Evidence 双向追溯、来源/权利状态与过期、robots noindex、canonical 安全校验、租户隔离、幂等冲突及迁移升级/降级。
- GEO_CONTENT-002 专项：44 passed（在加入 GEO_CONTENT-003 测试前的模块命令）；包含 Fixture hash/唯一性、跨租户与深层前置隔离、幂等命名空间、If-Match、追加式版本、退役原因、离线采样、人工复核及适配器输出绑定。
- GEO_CONTENT-003 专项：22 passed；GEO_CONTENT 模块回归：66 passed。覆盖多次采样、答案去重、置信度、未知结果失败闭合、跨租户与深层答案隔离、端口 hash 绑定、退役后幂等复放，以及迁移升级/回滚。
- GEO_REGION-001 专项：24 passed；GEO_REGION + Production + Region 集成回归：42 passed；全仓：861 passed、2 warnings。
- GEO_REGION-002 专项：49 passed；GEO_REGION + Knowledge Site 模块回归：73 passed。
- 最新全库回归：899 passed。
- 最新静态门禁：任务引用 `checked=157 errors=0`、Schema `schema_errors=0`、架构 `architecture_errors=0`、迁移图 `revision_count=105; head=20260920_site_004; errors=0`、SITE-004 任务精度 `scoped=1 precise=1 gaps=0`、密钥检查为 0 错误；计划一致性验证 157 项无错误。

## 未完成的外部门禁

真实 PostgreSQL 并发、真实对象存储和生产恢复演练仍是上线前独立验证，不由本地 SQLite 合成测试替代。

## 下一步

阶段 5 已按清单完成本地实现与专项验证。下一项按开发清单为阶段 6 的 `MEDIA-001`，进入 30/60/90 秒脚本模板、人工编辑和 Claim 引用的任务卡细化与实现阶段。


