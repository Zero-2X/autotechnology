# 开发进度复核 — 2026-09-20

机器注册表包含 157 项任务。完成 `SUP-001/SUP-002` 后为 **137 项 `done`、20 项 `planned`、0 项 `blocked`**；阶段 6 的 Media/Asset 清单已全部完成，阶段 9 的 account-free Analytics/Feedback/Support 已收口。阶段 8 的 Account/OAuth 无凭证实现已具备接入条件，但真实验收仍受 `EXT-ACCOUNT-001` 门禁。

## 本轮关闭的问题

- `MEDIA-001` 原任务卡仍为 `in_progress`，且清单、注册表和迁移清单仍指向不存在的 planned migration；已同步任务卡、开发清单、生成器、注册表、contract/migration manifest 和专项证据。
- 新增 `MediaScriptService`，只接受调用方指定的同租户 approved VariantVersion；30/60/90 秒模板使用固定时间线、75/150/225 口播单元预算和无事实断言 CTA。
- 每个脚本事实块必须绑定 verified/fresh、有效期内且适用于当前 Variant 的 Claim；Claim 撤回或过期后新建/编辑失败，历史 ScriptVersion 不改写。
- 人工编辑只改 segment 文本，按 expected version 追加不可变版本；时间线、segment kind、source block 和 Claim 引用保持逐字段一致，幂等冲突和并发冲突均确定性返回。
- 新增 `media_scripts`、`media_script_versions`、`media_script_claim_refs`、`media_script_commands` 迁移；SQLite/PostgreSQL 约束覆盖租户复合引用、approved Variant、fresh Claim、追加式事实和敏感 provider 字段阻断，降级保留前置事实。
- `MEDIA-002` 已收口：新增 `MediaStoryboardService` 和 storyboard/version/shot/asset-ref/command 五类追加式投影；镜头按脚本 segment 连续覆盖 30/60/90 秒，AssetVersion 必须 approved 且精确绑定 Variant/Region/Policy，所有素材引用必须通过 verified/current、适用且允许 derivative/commercial 的 RightsRecordVersion 门禁。
- `MEDIA-002` 明确保持边界：不生成字幕、不执行渲染、不调用模型、网络或平台，也不保存二进制、Token 或供应商原始响应。
- `MEDIA-003A` 已收口：新增 subtitle root/version/track/cue/command 五类追加式投影；单语和多语 locale track 共享确定性 cue 校验、文本版本、方向和可访问性 profile，支持字幕版本修订而不回写历史。
- `MEDIA-003A` 明确保持边界：不翻译、不调用模型或平台、不执行渲染，也不保存音视频二进制或供应商原始响应。
- `MEDIA-003B` 已收口：新增 visual asset-set root/version/item/command 四类追加式投影；cover、thumbnail、keyframe 逐项锁定 approved AssetVersion、文件哈希、alt text 和适用 RightsRecordVersion，支持可审计修订。
- `MEDIA-003B` 明确保持边界：不生成关键帧、不执行输出规格校验、不渲染、不调用模型或平台，也不保存二进制媒体。
- `MEDIA-003C` 已收口：新增 `MediaOutputSpecService`、输出规格和版本契约以及四张追加式迁移表；profile 的比例、尺寸、帧率、编码、音频和字幕引用在服务与数据库双重校验，版本指针只按下一版本推进。
- `MEDIA-004A` 已收口：新增 `MediaRenderService`，按同租户具体版本锁定脚本、可选分镜/字幕、视觉素材集合和输出规格的 id、快照哈希、Policy/Region 与 profile；目标 AssetVersion 的文件哈希和版本号在存在时一并锁定。Worker 通过 `RendererPort` 生成 bytes，私有 `StoragePort` 经 head/get 核验后只登记 private object ref、SHA-256、大小、content type、stage/shot 和输入哈希；幂等、并发领取、审计、Outbox 和 unknown 结果都保留稳定边界。
- `MEDIA-004A` 迁移新增 `media_render_jobs`、`media_render_job_inputs`、`media_render_artifacts`、`media_render_commands`，SQLite/PostgreSQL 约束覆盖租户复合引用、来源快照、private ref、产物自然键和追加式事实；降级只移除本任务表。
- `MEDIA-004B` 已收口：`MediaRenderRetryService` 记录三类脱敏失败事实，按封顶指数退避创建并原子领取 retry schedule；超过上限进入死信，unknown 只创建唯一人工核查任务。单镜头按 stage/shot/profile 稳定自然键重渲染，同哈希和已写入未确认的 private object 先 head/get 恢复，禁止覆盖已确认外部副作用。
- `MEDIA-004B` 迁移新增失败、schedule、命令和 shot target 四类表，并为 render job 增加 retry/pending 字段；SQLite/PostgreSQL 同时保护租户范围、哈希、自然键、状态推进和追加式事实，降级回 `MEDIA-004A` 保留既有输入与产物。
- `MEDIA-005A` 已收口：新增 `MediaAssetQAService`（兼容 `MediaQAService`/`MediaRenderQAService` 别名），以可替换 `MediaProbePort` 和私有 `StoragePort` 执行画面、音频、字幕 cue 及文件哈希四组检查；确定性不匹配为 `failed`，探针或存储未知结果为 `needs_review`，报告只保存脱敏事实和哈希。
- `MEDIA-005A` 迁移新增 `media_qa_reports`、`media_qa_findings`、`media_qa_commands`，租户复合外键、哈希/敏感字段门禁和追加式触发器已覆盖，降级回 `MEDIA-004B` 保留渲染与重试事实。
- `MEDIA-005B` 已收口：新增 `MediaContentRightsQAService`，通过离线 TextExtraction/Rights Port 检查数字、代码、版本 token、AI/广告披露及素材权利范围；未知文本或权利结果为 `needs_review`，确定性差异为 `failed`。
- `MEDIA-005B` 迁移新增 `media_qa_content_evaluations` 追加式投影，记录来源/观察/权利快照哈希并保护敏感原始文本，降级回 `MEDIA-005A` 保留 QA 报告与 finding。
- `MEDIA-006` 已收口：新增 `MediaAssetLineageService`，将 AssetVersion 精确绑定 VariantVersion、Claim 和 RightsRecordVersion 的 id/hash 快照；依赖撤回、过期或范围变化时确定性返回 blocked/withdrawn，显式撤回只推进当前状态投影，不覆盖不可变资产版本。
- `MEDIA-006` 迁移新增 lineage edge、decision、command 三类追加式事实表，source_org_id 租户门禁、SHA-256、关系类型和 SQLite/PostgreSQL append-only 触发器均已覆盖。
- 修正任务注册表的外部依赖推导：阶段 8、`FEEDBACK-LIVE-*` 和 `PILOT-*` 继续受 `EXT-ACCOUNT-001` 约束；阶段 9 的 Analytics、核心 Feedback、实验和 Fake/人工 Support 不再因阶段号被错误阻塞。
- `ANALYTICS-001` 已收口：新增九类规范事件目录与严格事件 Schema，通用事件消费者仍可解析 aggregate-only payload，Analytics 摄取边界再校验完整观察字段；`source=platform` 没有账号证据时确定性拒绝。
- 新增 `MetricDefinitionService`，支持租户/全局 scope、不可变版本、draft/active/retired 状态事实、替代版本后退役、幂等重放、乐观并发和审计/Outbox；全局定义写入与状态修改使用显式 privileged 入口。
- `ANALYTICS-001` 迁移新增 `metric_definitions`、`metric_definition_state_events`、`analytics_metric_definition_commands`，版本序列、scope、状态顺序、替代版本、哈希和 append-only 守卫覆盖 SQLite/PostgreSQL。
- `ANALYTICS-002` 已收口：新增 `ObservationService`，将每条 Observation 精确绑定 active MetricDefinition 的 ID/版本/key/type，规范化 `region`/`locale`，按 `data_quality` 保存可信度分级，并按 value schema 校验 number/boolean/string/enum/json。
- Observation 使用 `org_id + dedupe_key + observation_version` 做业务去重；同版本同快照复用，修订要求下一版本与 expected version，旧值和旧事件保持不可变。成功写入同时产生不含 metric value 的 `observation.recorded` 和对应九类 Analytics 事件。
- `ANALYTICS-002` 迁移新增 `observations`、`analytics_observation_commands`；active 指标绑定、版本连续性、来源快照、平台账号证据哈希、敏感键和 append-only 守卫覆盖 SQLite/PostgreSQL。
- `ANALYTICS-003` 已收口：新增 `AnalyticsKpiService`，从同租户 Observation 的最高版本按 UTC 半开窗口和 region/locale 过滤，确定性生成七类 KPI 与去标识化线索归因；unknown、raw/estimated、零分母和不支持指标均登记质量问题。
- `ANALYTICS-003` 对平台来源执行账号证据门禁；account-free 输入标记为 `account_free`。快照、命令、审计和 Outbox 均为追加式/幂等，输入 metric value 与线索原文不进入审计或事件。
- `ANALYTICS-003` 迁移新增 `analytics_kpi_snapshots`、`analytics_kpi_snapshot_commands`，SQLite/PostgreSQL 均保护租户输入绑定、哈希和 append-only 约束；降级只移除本任务表。
- `ANALYTICS-004` 已收口：新增 `GeoQualityService`，分别聚合 GEO_CONTENT 与 GEO_REGION Observation，选择最新版本后应用 UTC 半开窗口和 region/locale 过滤；未知值、低质量来源、缺失维度和不支持指标显式进入质量问题。
- `ANALYTICS-004` 迁移新增 `analytics_geo_quality_snapshots`、`analytics_geo_quality_commands`，保护输入 Observation 同租户绑定、快照哈希和 append-only 事实；审计/Outbox 不携带 metric value。
- `FEEDBACK-CORE-003` 已收口：新增 `FeedbackItemService`，支持 synthetic/manual Observation、负责人/截止时间/置信度和追加式状态转换；所有命令带幂等键与 expected version，跨租户和真实平台来源在 M1 受阻断。
- `FEEDBACK-CORE-003` 迁移新增 `feedback_items`、`feedback_item_commands`，绑定同租户 Observation 并保护版本、哈希和 append-only 事实。
- `FEEDBACK-CORE-004` 已收口：新增 recommendation-only 投影，将 FeedbackItem 映射到 TopicOpportunity、Refresh Queue、Variant、Channel 和 Prompt Eval 目标；保存规则/证据哈希，明确不修改生产规则。
- `FEEDBACK-CORE-004` 迁移新增 `feedback_recommendations`、`feedback_recommendation_commands`，绑定同租户 FeedbackItem 并保护 append-only 事实。
- `FEEDBACK-CORE-005` 已收口：新增 `FeedbackActionService` 生命周期和有限结果快照，Policy/审批/版本/幂等门禁均在动作事实层执行，明确不触发外部副作用。
- `FEEDBACK-CORE-005` 迁移新增 `feedback_actions`、`feedback_action_commands`，绑定同租户 FeedbackItem 并保护版本、哈希和 append-only 事实。
- `FEEDBACK-EXP-001` 已收口：新增 account-free 实验模型，记录假设、分组、指标、窗口、样本、结论和回滚；真实平台样本仍受账号证据门禁。
- `FEEDBACK-EXP-001` 迁移新增 `feedback_experiments`、`feedback_experiment_samples`、`feedback_experiment_commands`，样本与实验同租户绑定并保持追加式。
- `SUP-001` 已收口：新增 Fake/manual Inbox 服务，完成消息去重、意图识别、低风险草稿和人工升级；正文不进入事实存储，发送恒定禁用。
- `SUP-002` 已收口：高风险客服类别自动升级人工并阻止自动草稿，覆盖退款、合同、医疗、法律、金融、KYC、申诉、版权、隐私和安全漏洞。
- `SUP-001/SUP-002` 迁移新增 support thread/message/command 与 escalation 表，SQLite/PostgreSQL 追加式和同租户约束已登记。
- 阶段 8 的无凭证 Account/OAuth 基础已实现：`InMemoryAccountService` 提供唯一的 AccountConnection、AuthorizationEvidence、完整性计算、健康检查、restricted 自动门禁、不可变 TargetVersion 快照和三个阶段的 Kill Switch 重检；连接投影不接收 Token。
- 新增 `OAuthService`、`OAuthProvider`、`FakeOAuthProvider`、`InMemorySecretManager` 和 `TokenLeaseService`。Fake 流程覆盖 State 哈希、PKCE S256、精确 redirect URI、CSRF、Scope 白名单、一次性 code、撤销和单连接 active lease；回调只有授权与连接投影，没有发布调用路径。
- Account/OAuth 快照契约补充了受限的 scope、能力和脱敏连接字段；原始 Token 仅存在测试 Secret Manager 的私有值存储，审计、事件、普通投影和 TargetVersion 均只保存引用或版本。
- `docs/foundation/ACCOUNT-OAUTH-IMPLEMENTATION-READINESS.yaml` 登记了 10 个实现就绪任务、16 个专项测试和剩余外部证据清单；这些任务仍保持 `planned`，因为阶段 8 不能用 synthetic 账号替代真实主体、Scope 和回查证据。

## 验证

- MEDIA-001 专项（单元、端到端 Port、迁移、契约）：**14 passed**。
- Schema：`schema_errors=0`。
- 架构：`architecture_errors=0`。
- 迁移图：`revision_count=109; head=20260920_media_003b; errors=0`。
- 计划一致性：`validated=157; errors=0`。
- 迁移升级/降级：完整 Alembic 链 disposable SQLite 通过。
- MEDIA-002 专项（单元、端到端 Port、迁移、契约）：**18 passed**。
- MEDIA-003A 专项（单元、端到端 Port、迁移、契约）：**10 passed**。
- MEDIA-003B 专项（单元、端到端 Port、迁移、契约）：**8 passed**。
- 全量回归：**941 passed**（含 MEDIA-003B 改动；首次回归仅因 FOUND-000 清单指纹过期失败，顺序刷新清单后 `inventory valid`，FOUND-000 清单测试 6 项通过）。
- MEDIA-003C 专项与最终全量：**13 passed；955 passed**。
- MEDIA-004A 专项（服务、Worker、迁移、契约、PostgreSQL 离线 SQL）：**12 passed**。
- MEDIA-004A 最终全量回归：**967 passed in 213.45s**；刷新清单后 `inventory valid`，FOUND-000 清单测试 **6 passed**。
- MEDIA-004B 专项（重试策略、失败幂等、到期领取、unknown 人工核查、死信、单镜头恢复、迁移和契约）：**13 passed**；完整回归 **979 passed**，随后只剩仓库清单指纹待刷新。
- MEDIA-004B 静态门禁：`checked=157 errors=0`、`scoped=93 precise=93 gaps=0`、`schema_errors=0`、`revisions=112 heads=['20260920_media_004b'] errors=0`、`architecture_errors=0`、`secret_findings=0`、`validated=157 errors=0`、`events=167 baseline_events=162 errors=0`。
- MEDIA-005A 专项（四类 QA、租户/版本/幂等、迁移和契约）：**19 passed**；迁移图 `revisions=113 heads=['20260920_media_005a']`，离线 PostgreSQL SQL 与回滚顺序通过。
- MEDIA-005B 专项（数字/代码/版本、披露、权利、租户/版本/幂等、迁移和契约）：**26 passed**（含 005A 与既有 QA 兼容回归）；迁移图 `revisions=114 heads=['20260920_media_005b']`，离线 PostgreSQL SQL 与回滚顺序通过。
- MEDIA-006 专项（lineage 快照、依赖撤回传播、显式撤回、迁移和契约）：**7 passed**；迁移图 `revisions=115 heads=['20260920_media_006']`，离线 PostgreSQL SQL 与回滚顺序通过。
- MEDIA-006 最终全量：**1001 passed**；唯一初始失败为清单指纹过期，刷新后清单测试 **6 passed**。
- ANALYTICS-001 专项：**10 passed**；Foundation 事件/指标、核心 Schema、Feedback 和 Analytics 兼容回归 **143 passed**。
- ANALYTICS-001 全量回归：**1011 passed**；唯一失败为预期的仓库清单指纹过期，代码、迁移和契约测试无失败。
- ANALYTICS-001 静态门禁：`checked=157 errors=0`、`scoped=93 precise=93 gaps=0`、`schema_errors=0`、`revisions=116 heads=['20260920_analytics_001'] errors=0`、`architecture_errors=0`、`secret_findings=0`、`validated=157 errors=0`、`events=176 baseline_events=162 errors=0`。
- ANALYTICS-002 专项：**9 passed**；Analytics/Foundation Observation/Feedback/事件兼容回归 **88 passed**。
- ANALYTICS-002 全量回归：**1020 passed**；唯一失败为预期的仓库清单指纹过期，代码、迁移和契约测试无失败。
- ANALYTICS-002 静态门禁：`checked=157 errors=0`、`scoped=93 precise=93 gaps=0`、`schema_errors=0`、`revisions=117 heads=['20260920_analytics_002'] errors=0`、`architecture_errors=0`、`secret_findings=0`、`validated=157 errors=0`、`events=176 baseline_events=162 errors=0`。
- ANALYTICS-003 专项（服务、迁移、契约）：**11 passed**；Analytics/Observation/Feedback 兼容回归 **31 passed**。
- ANALYTICS-003 静态门禁：`schema_errors=0`、`revisions=118 heads=['20260920_analytics_003'] errors=0`、`validated=157 errors=0`；PostgreSQL 仍仅完成离线 SQL 生成及回滚顺序验证。
- ANALYTICS-004 专项（服务、迁移、契约）：**6 passed**；迁移图 `revisions=119 heads=['20260921_analytics_004']`，`schema_errors=0`，计划一致性 `validated=157 errors=0`。
- FEEDBACK-CORE-003 专项（服务、迁移、契约及 CORE-002 兼容）：**6 passed**。
- FEEDBACK-CORE-004 专项（推荐服务、迁移、契约）：**4 passed**。
- FEEDBACK-CORE-005 专项（动作生命周期、迁移、契约）：**4 passed**。
- FEEDBACK-EXP-001 专项（实验生命周期、迁移、契约）：**4 passed**。
- SUP-001/SUP-002 专项（Inbox、分类、迁移、契约）：**6 passed**。
- Account/OAuth 专项（Fake OAuth 安全流、连接/证据/TargetVersion 契约、健康和 Kill Switch 门禁）：**16 passed**；`schema_errors=0`、`architecture_errors=0`、`secret_findings=0`。

## 下一步

阶段 6 已完成，阶段 9 的 account-free 路径已完成。阶段 8 的真实 AccountConnection/OAuth/平台任务等待 `EXT-ACCOUNT-001` 的真实主体、授权和账号证据；当前已把可独立开发的安全边界和 Fake 契约做完，未伪造真实验收状态。PostgreSQL 验证为离线 SQL 生成及回滚顺序，尚未执行实机测试。

下一步是取得 `EXT-ACCOUNT-001` 的八类证据后，执行真实 Sandbox 连接、Scope/健康回查和首个平台 draft-only 验收；在证据到位前，不能安全完成平台副作用、真实指标和 2–4 周 Pilot 运行任务。
