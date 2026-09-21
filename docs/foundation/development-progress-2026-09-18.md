# 开发进度复核 — 2026-09-18

机器注册表共 157 项，当前 69 项 done、88 项 planned，无 in_progress 或 blocked。阶段 0 与 Foundation 底座已完成；阶段 1 已完成 IAM、账号引用、区域、模型、Agent、Workflow、Feedback 契约、Scheduler 与 OBS-CORE-001～003。阶段 2 已完成 TOPIC-001～008；阶段 3 已完成 PROV-001～003、KNOW-001～002 与 CANON-001～003。下一项按注册表顺序为 CANON-004。

## 本轮完成

GOV-007 冻结了 `baseline-synthetic-data/v1` 数据处理策略：六类数据的项目默认保留期限、较短适用期限优先、删除传播八步与八类目标、备份/外部接收方验证，以及跨境默认拒绝与合成公开内容的审查边界。新增 JSON Schema、本地确定性判定和 Alembic 策略版本表；专项契约测试覆盖合法路径与拒绝路径。

GOV-008 冻结了 `operational-targets/v1`：成功率、零越权动作、USD 预算上限、SLO、RPO/RTO 和 R0～R4 人工首响 SLA。新增 JSON Schema、本地预算/截止时间/恢复判定和 Alembic 版本表；专项契约测试验证与既有风险策略数值一致。

GOV-009 明确真实账号仍不可用：`platform_operator` 负责取证、`governance_owner` 对门禁负责，证据最晚到位时间为 2026-12-31 17:00（北京时间）。每周复核，提前 30 天升级；未到位时只运行手工导出与模拟，Distribution Pilot 持续 No-Go。

GOV-010 建立四类外部数据处理供应商清单。真实供应商均未选择；地域、保留期、合同/DPA、分包商、退出和删除证据以明确缺失状态登记，缺失时保持真实处理 No-Go。

FOUND-011 新增 Python AST 架构边界检查和离线 smoke 命令，覆盖跨模块导入、常量 SQL 直写、API 存活与共享 FakeStorage 租户隔离；静态检查不能证明变量构造 SQL 安全，后续模块实现仍需代码审查与集成测试。

FOUND-012A 建立了精确锁定的 Python/CI 工具依赖、GitHub Actions 双 Job、锁文件与 CI 配置校验、本地秘密扫描，并接入 Ruff、mypy、Bandit、Gitleaks、pytest、pip-audit 和前端 frozen-lockfile 构建。工作流只授予 `contents: read`，不读取生产凭证。

FOUND-013 将严格任务注册表检查接入本地和 CI 门禁，覆盖 157 个任务的唯一 ID、依赖环、阶段层级、路径冲突、契约引用和 Markdown 对齐，并加入循环依赖与路径重叠负例测试。
WORKFLOW-CORE-002 完成 workflow run/step 与 human task 的契约字段、租户隔离、expected version、人工任务领取/提交/完成、到期扫描暂停 run、重放和 outbox 审计，并补充 API 集成测试。

## 剩余外部验证

真实 PostgreSQL 并发仍未验证。当前 SQLite 门禁只证明本地迁移和契约行为，不作为生产并发证据；上线前需在独立 PostgreSQL 环境完成多 Worker、隔离、锁超时、连接中断和 Outbox 并发测试。

## 下一步

继续按注册表进入 CANON-004。

## 后续开发核验

WORKFLOW-CORE-003 增加 OutboxDispatcher 的发布、任务租约、死信和重放命令。FEEDBACK-CORE-001 冻结 Observation、FeedbackItem 与评分版本契约。SCHED-001 增加 UTC 排程、区域版本绑定与租约回收。

OBS-CORE-001 将审计记录、查询和导出留痕写入 SQLite 追加式存储；重启后的幂等结果仍可读取，数据库拒绝底层修改和删除。OBS-CORE-002 在 synthetic SQLite 与私有对象上完成真实镜像备份、摘要校验和恢复；恢复出的队列持续暂停，Worker 不领取任务也不派发 Outbox，达标后才放行。OBS-CORE-003 持久化删除请求、五阶段状态和人工复核任务；每个目标通过独立缺失检查后才记录证据引用。TOPIC-001 建立并持久化分类、标签、技术版本、受众和状态机，验证重启后的记录与命令幂等。

TOPIC-002 实现最多 1,000 行的 JSON/CSV 导入；逐行校验但在同一事务内保存合法信号、拒绝事件和批次幂等结果。来源与授权契约已按任务卡修正，去重键包含租户和 UTC 采集时间；只有授权已核实、有证据且用途为 editorial/commercial 的记录可进入可发布查询。

TOPIC-003 增加版本固定的七分项评分、逐信号权利与证据扣分解释、可验证的评分内容哈希；同租户同主题在有效期内只保留一个活动机会。评分命令只生成 proposed，shortlist 需显式人工命令、预期版本与理由；过期机会不能进入 TopicBrief。

TOPIC-004 建立带受众、问题、核心 Claim、证据计划、原创角度和渠道的 TopicBrief。创建后先为 draft；只有 shortlisted opportunity、完整必需证据计划和 Policy 通过时才能锁定。锁定版本不可变，supersede 会保留旧版并生成新的 locked 版本。

TOPIC-005 建立版本化编辑计划：负责人、优先级和 UTC 截止时间会与机会的乐观版本一起原子更新；重复排期被拒绝，人工覆盖必须带理由并生成 superseded 历史与追加式审计记录。

TOPIC-006 增加机会状态机：reject/defer/expire/resume 均使用显式版本与幂等命令，reject/defer 必须记录理由；已有锁定 Brief 的机会不能被回退，状态事件按租户和 sequence 追加保存。

TOPIC-007 将评分时的信号输入、逐信号摘要、评分公式、权重、分项和扣分固化为不可变快照；`recompute_snapshot` 校验内容摘要、输入聚合摘要和加权总分，`verify_snapshot` 对当前信号生成漂移报告并以租户级幂等键追加保存。快照篡改、信号变更、跨租户访问和核验记录更新/删除均有专项拒绝测试。

TOPIC-008 增加公开 TopicBrief 批准命令：批准事务同时写入 approved 状态、版本、锁定时间/人员、输入快照哈希和可复算的 lock_hash；`If-Match` 与租户幂等键防止并发重复批准。创建人不能批准自己的版本，已批准版本只能通过 supersede 生成新的 draft，数据库触发器拒绝直接篡改。

PROV-001 建立 Source 与 SourceSnapshot 的租户范围存储：抓取方式和可信度通过契约校验，原文只以 `private://` 对象引用保存并用 SHA-256 摘要验证；ingest 原子写入首个快照、幂等命令和 `source.ingested`，快照状态迁移使用 expected version、终态原因和追加式事件，跨租户访问、哈希/身份篡改与审计事件修改均被拒绝。SQLite 文件重启恢复和 API 内部命令已覆盖专项测试。

PROV-002 建立 RightsRecord 与不可变 RightsRecordVersion：授权版本绑定同一 Source 的 SourceSnapshot，保存许可证/合同/证据、条款摘要、地区/语言/媒体/商业用途和有效期；只有 usable 快照、完整证据和 Policy 规则才能人工验证。verified 版本的过期、撤回和投诉冻结均要求原因并写入追加式 rights 事件，父身份指针同步投影，跨租户和版本篡改被拒绝。

PROV-003 增加使用前授权判定、到期提醒和到期迁移、投诉冻结与多层派生 lineage 反向追踪；allow/deny、reminder、lineage 和 block 均有租户隔离、幂等和追加式证据，未验证或已过期/撤回/投诉的权利默认阻断。

KNOW-001 建立 Entity、Claim、Evidence 及关系表，验证状态、新鲜度、来源和权利引用，并以租户幂等命令与追加式事件保存事实变更。KNOW-002 将已验证 Claim/Evidence 固化为 KnowledgeCore 不可变版本，检测冲突集合、刷新 supersedes 链和 needs_review 状态。CANON-001 在锁定 TopicBrief 和输入快照门禁下建立 CanonicalContent 根与不可变编辑版本，支持稳定 key/position 的章节、Claim、代码、示例和限制数组；重复 content_hash 返回既有版本，版本与审计事件追加保存。
CANON-002 在版本写入只读约束上增加租户范围的版本历史查询和稳定 key/position diff：新增/删除/替换操作按确定顺序计算并以不可变 diff 快照留痕；重复查询返回同一 diff_hash。
CANON-003 将锁定/批准 TopicBrief 的状态、lock_hash 和 input_snapshot_hash 固化到 CanonicalContentVersion；Brief 缺失、跨租户或仍为 draft 时在事务写入前返回 `TOPIC_BRIEF_REQUIRED`。

KNOW-001 建立 Entity、Claim、Evidence 及 Entity↔Claim、Claim↔Evidence 关系的租户范围存储；保存事实类型、适用版本/地区/语言、有效期和复核新鲜度，Evidence 验证要求可用来源与定位信息，Claim 验证要求有效 Evidence。创建和状态命令具备 payload hash 幂等、expected version、追加式事件与不可变触发器，API 与 SQLite 重启、跨租户、篡改拒绝专项测试均已通过。

KNOW-002 建立 KnowledgeCore 与不可变 KnowledgeCoreVersion：版本快照绑定 Entity、Claim、Evidence、冲突集和新鲜度，验证只接受 verified/fresh Claim、valid Evidence、usable SourceSnapshot 与 verified 且未过期的 RightsRecordVersion。冲突自动落 ConflictSet 并标记 needs_review；refresh 通过新版本保留旧快照，所有命令租户隔离、幂等且有序审计，API、迁移和篡改拒绝专项测试均已通过。

以上均是离线合成数据与本地 SQLite 的开发证据。真实 PostgreSQL 并发、对象存储和生产恢复演练仍属上线前独立验证。
