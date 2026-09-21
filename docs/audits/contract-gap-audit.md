# V2.3 契约闭环审计

审计基线：`AI跨境技术内容自动化工作流开发清单_审计与优化版.md`、`docs/task-registry.yaml`、`docs/contracts/event-registry.yaml`，以及 `packages/contracts/` 和 `packages/db/migrations/planned/`。

## 结论

当前文件可以作为规划基线，不能作为“立即编码”的完整机器构建基线。任务 ID、任务卡索引和事件索引已经形成；对象与事件 Schema 已补齐文件索引，但迁移仍未落地，状态机、事件和 API 仍有若干边界需要在编码前冻结。

## 已确认的缺口

| 优先级 | 证据 | 影响 | 修复要求 |
|---|---|---|---|
| P0 | 157 个任务的 `migration_refs` 均指向不存在的 `packages/db/migrations/planned/*.sql` | 任务卡无法据此创建可执行数据库结构，状态机无法持久化验收 | 每个 M1-P0 任务进入 `in_progress` 前创建真实 Alembic revision；任务注册表改为引用具体 revision 或迁移文件；禁止把 README 规划路径当作已完成迁移 |
| P0 | Schema 文件已生成并被 manifest 索引，但必须持续校验路径、JSON 可解析性和 `$id` 唯一性 | 只登记文件而不验证内容，消费者仍无法安全生成 | CI 必须执行路径存在、Schema 可解析、`$id` 唯一，以及事件 `$id` 与 `schema_ref` 一致性检查 |
| P0 | 状态机表中的 `source.snapshot.*`、`entity.*`、`claim.*`、`evidence.*`、`knowledge.core*`、`variant.created`、`variant.root_changed`、`asset.created`、`asset.root_changed` 等事件未进入事件注册表 | 状态转换表、Outbox、事件 Schema 和回放范围不闭合 | 对每个状态转换逐条决定：登记为公共业务事实事件，或明确标注为内部投影；若是公共事件，加入 5.2、事件注册表和 Schema；若是投影，删除“公共事件”语义并在投影规则中登记 |
| P1 | 事件注册表有 `agent_run.completed`、`approval.requested`、`approval.recorded`、`feedback.recommendation_created`、`human_task.created`、`observation.recorded`、`region.profile.created`、`topic.opportunity.created`、`topic.signal.created` 等 append-only 事件，但状态转换表不逐条体现 | 事件会有多个来源语义，回放和消费者容易误判为状态转换 | 在注册表增加 `event_kind: append_only`、事实对象/输入快照哈希、是否更新投影；状态机事件增加 `event_kind: transition` 和 `from_state/to_state` |
| P1 | `AccountConnection` 将 `authorization_status` 与 `health_status` 写在同一行状态转换中 | 容易实现成单一枚举，导致 `revoked/degraded/restricted` 的恢复路径互相覆盖 | 在 Schema、表和用例中拆成两个独立状态轴；每次变更记录 `connection_status`、`authorization_status`、`health_status` 的旧值/新值，且定义组合约束和恢复路径 |
| P1 | `WorkflowPort`、公开 API Catalog 和事件清单均已描述，但没有 `packages/contracts/openapi/` 实际 OpenAPI 文件 | Codex 无法准确生成路由、请求/响应模型和错误码 | 阶段 1 先提交 OpenAPI 基线；每个写接口声明幂等键、If-Match、错误码、权限、事件和审计要求；真实发布 API 在阶段 8 前保持未暴露 |
| P1 | 事件注册表当前统一使用 `idempotent_internal_replay`，未区分外部回执、控制事件和事实事件 | 外部副作用事件重放边界不够精确 | 为事件增加 `event_kind`、`replay_policy`、`external_side_effect`、`ordering_key`、`consumer_dedupe_key`；外部副作用只能由原始 provider 幂等键和回查流程执行 |
| P1 | API Catalog 有 58 条方法/路径，但 OpenAPI 当前覆盖 20 个操作，仍有 38 个操作未映射；状态表还出现未逐条登记的通配事件 `rights.version.*` | Codex 依据 Catalog 生成接口时会遇到缺失路由；通配事件无法作为可验证 Schema 引用 | 明确 Catalog 分期：将未实现端点标记 `planned` 或补齐 OpenAPI；所有事件必须使用具体 event type，不能使用通配名 |

## 已完成的低风险修订

`scripts/generate_event_registry.py` 现在对 `publication_intent.ready` 显式登记 `PublicationIntent`，对不可变投票事件 `approval.decision_recorded` 显式登记 `ApprovalDecision`，并登记模型调用事件的 `ModelCall` 聚合，避免仅按事件名前缀推断聚合类型。`scripts/check_plan_consistency.py` 现在会检查事件的 `producer`、`aggregate_type`、重复 `event_type` 以及事件 Schema 路径必须位于 `packages/contracts/events/`；使用 `--strict-contracts` 时会提示尚未创建的事件 Schema。

迁移 manifest 现在为每项记录 `status`、`path_kind`、`exists` 和 `verification_status`，并提供统一生命周期说明。OpenAPI manifest 通过解析每个操作的 `x-task-ids` 建立精确任务映射，不再用字符串包含关系推断关联。

## 建议的闭环顺序

1. 冻结事件分类和聚合类型，补齐状态机表与事件注册表的逐条映射。
2. 为 M1-P0 对象创建真实 JSON Schema、事件 Schema 和 OpenAPI 基线。
3. 创建对应 Alembic migration，并将任务卡引用更新到具体文件。
4. 对每个状态机实现合法/非法转换、幂等、乐观锁、Outbox 同事务提交和回放测试。
5. 通过契约测试后再实现业务模块；账号和真实平台仍保持在 Distribution 后置阶段。
