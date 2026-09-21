# FOUND-008 — Feature Flag、统一交付模式和全局 Kill Switch

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/foundation`  
优先级：`critical` / `P0`

## 目标

提供租户 Feature Flag、四种统一交付模式和最小可执行全局 Kill Switch。创建新任务前必须调用控制门禁；Feature Flag 关闭或全局开关暂停时，门禁拒绝相应请求并留下不可变审计事实。Kill Switch 状态、审计记录和 Outbox 事件使用同一数据库事务。

## 明确不做

- 不创建领域 TaskJob、PublicationIntent 或平台请求；调用方仍负责在门禁允许后用相同幂等语义创建业务事实。
- 不把 Feature Flag 当作 Policy、Rights、Region、Approval、AccountConnection 或 IAM 授权的替代品。
- 不调用真实平台、网络或凭证服务；`draft_only`/`authorized_api` 默认关闭。
- 不实现平台、账号、目标或内容级 Kill Switch；本任务仅实现全局状态。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-005`
- `FOUND-007D`

## 输入与输出

输入：已验证的 `TenantContext`（org_id、actor_id、trace_id）、`Idempotency-Key`、expected_version、任务 payload hash、交付模式与是否产生副作用。

输出：

- `infra/foundation/control_plane.py`：Feature Flag、Kill Switch 和创建前门禁。
- `packages/contracts/jsonschema/delivery-mode.schema.json`：唯一四值交付模式契约。
- `packages/contracts/jsonschema/feature-flag.schema.json`、`kill-switch.schema.json`。
- `packages/db/migrations/versions/20260918_found_008_control_plane.py`。
- `foundation_control_audit` 审计事实；暂停/恢复同时写入 `kill_switch.paused|resumed` Outbox 事件。
- `docs/foundation/FOUND-008-EVIDENCE.yaml`。

## 契约与迁移

- `packages/contracts/jsonschema/delivery-mode.schema.json`
- `packages/contracts/jsonschema/feature-flag.schema.json`
- `packages/contracts/jsonschema/kill-switch.schema.json`
- `packages/contracts/events/kill_switch-paused.schema.json`
- `packages/contracts/events/kill_switch-resumed.schema.json`
- `packages/db/migrations/versions/20260918_found_008_control_plane.py`

## 目录边界

拥有目录：`infra/foundation`。允许修改 `apps`、`packages`、`infra`、dev/staging 部署模板、`scripts`、`docs` 和测试目录。禁止真实平台适配器、production/secrets、密钥、Token 或证书文件。

## 实现规格

1. `DeliveryMode` 和 JSON Schema 均按固定顺序定义 `manual_export|simulation|draft_only|authorized_api`；`DistributionTargetVersion.eligible_delivery_modes` 引用该 Schema。无账号默认只打开前两种。
2. Feature Flag 按 `(org_id, flag_key)` 隔离，使用 expected_version；首次写入期望版本 0。命令按 `(org_id, idempotency_key)` 保存 payload hash 和响应；同键同命令返回原响应，同键不同命令拒绝。
3. 全局 Kill Switch 缺省状态为 `active/version=0`，只允许 `active→paused→active`；更改要求注入的 `global_authorizer` 明确返回 true，且 expected_version 匹配。
4. 暂停/恢复在同一事务写状态、审计、幂等结果和 Outbox。Outbox 使用调用租户作为事件租户、固定全局 aggregate ID、递增 aggregate_version；任何一步失败全部回滚。
5. `guard_new_task` 先验证交付模式、身份和 payload hash，再读取租户 Feature Flag 与全局状态。关闭的 Feature Flag 返回 `FEATURE_FLAG_DISABLED`；`requires_side_effect=true` 且全局暂停返回 `GLOBAL_KILL_SWITCH_PAUSED`。
6. 拒绝审计必须先提交再抛出确定性 `SideEffectRejected`；重复拒绝不增加事实。同一门禁幂等键若元数据或 payload hash 改变，返回 `IDEMPOTENCY_KEY_REUSED`。
7. 已允许门禁的同键重放返回 `replayed=true`，表示调用方只能返回既有任务结果，不能再次创建任务。全局暂停只阻止新副作用任务；`requires_side_effect=false` 的手工导出等安全路径仍可通过。
8. Feature Flag 是必要条件之一，不授予真实发布权限。后续调用方还必须分别通过 IAM、Policy、Rights、Region、Approval 和账号健康门禁。

## 权限、幂等、失败和审计

- org_id、actor_id 必须是 UUID；缺失身份不产生写入。
- Feature Flag 只能访问调用租户；全局控制必须经显式授权器。
- expected_version 冲突、非法转换、未知模式和非法 hash 都是确定性失败，不自动重试。
- 审计包含 trace、actor、输入/输出版本、控制快照、原因、payload hash、幂等键、耗时和成本占位；不得写正文、Token 或秘密。
- rejected 门禁事实提交后才返回错误；控制命令事务失败时状态、审计、命令回放记录和 Outbox 同时回滚。

## Given–When–Then

成功：Given 有效租户身份且 simulation 默认为 enabled，When 检查无副作用新任务，Then 返回 allow、写一条审计且不调用网络。

重复：Given 已成功的 Feature Flag/Kill Switch/门禁幂等键，When 原样重放，Then 返回原结果，门禁标记 replayed，且不新增审计、状态或事件。

非法转换/输入：Given stale expected_version、未知模式、非法 hash 或 naive datetime，When 执行命令，Then 返回稳定错误码并保持数据库不变。

权限与跨租户：Given 缺少 org/actor、未配置全局授权器或另一租户读取 Flag，When 执行，Then 拒绝写入；Flag 不跨租户可见。

依赖缺失：Given 全局授权器缺失，When 尝试 pause/resume，Then 返回 `GLOBAL_CONTROL_FORBIDDEN`；无真实平台依赖时仍可完成 synthetic 验收。

暂停、回滚与未知结果：Given 全局状态 active，When pause，Then 状态、审计与 paused Outbox 原子提交；Given Outbox 写失败，Then 三者全部回滚。Given paused，When 新副作用任务进入门禁，Then 提交 reject 审计后拒绝；无副作用路径仍允许。

## 验证

```text
python scripts/check_task_card_precision.py --task FOUND-008 --strict
python scripts/check_migrations.py --strict --json
python scripts/check_json_schemas.py
python scripts/check_event_compatibility.py --strict
python -m pytest tests/contract/test_found_008_control_plane.py tests/integration/test_found_008_control_plane_integration.py -q
python scripts/check_foundation_contracts.py
```

Gate：`found_008_acceptance`

## 外部依赖

无。验证仅使用 SQLite synthetic 数据库和 Fake/无网络路径。

## 回滚

先暂停新控制命令和副作用任务，保留现有审计及 Outbox。若还没有后续 revision，执行 `python -m alembic downgrade 20260916_found_007d` 删除 FOUND-008 四张控制表；该回滚会删除控制面事实，只能在已导出审计且无生产数据的受控环境执行。代码回滚不得改写已发布的事件 Schema 或历史事件。

## 完成证据

状态、迁移 head、Schema、专项/全量测试与边界声明见 `docs/foundation/FOUND-008-EVIDENCE.yaml`。
