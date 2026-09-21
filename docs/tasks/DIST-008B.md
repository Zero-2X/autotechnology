# DIST-008B — 实现 Intent 交付模式校验和全局/平台/账号范围 Kill Switch。

状态：`done`  
阶段：7（Distribution 抽象、Manual Export 和 Fake Adapter）  
Owner：`team/distribution`  
优先级：`critical` / `P0`

## 目标

实现 Intent 交付模式校验和全局/平台/账号范围 Kill Switch。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `FOUND-008`
- `POLICY-001`
- `POLICY-002`
- `DIST-007`
- `DIST-008A`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `DIST-008B.implementation`
- `DIST-008B.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/publication-intent.schema.json`
- `packages/contracts/jsonschema/kill-switch.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_dist_008b.py`

## 实现规格

- `DistributionKillSwitchService` 实现 global/platform/account/target 四级 Kill Switch，状态切换使用 expected version，返回严格符合 `kill-switch.schema.json` 的投影。
- Kill Switch 支持 blocked_delivery_modes；匹配 scope、mode 且需要副作用时拒绝 Intent，未匹配 scope/模式返回允许；global 使用全局键，scoped switch 按租户隔离。
- `DistributionService.execute` 在生成 DeliveryAttempt 前执行 mode gate；manual_export 可在暂停时继续生成私有包，simulation/draft_only/authorized_api 受对应开关阻断，拒绝时不写入 attempt、package 或 PublicationRecord。
- Intent 创建继续校验 TargetVersion eligible_delivery_modes、synthetic/connected 资格、Policy snapshot 和 Approval；执行路径记录 gate 审计、拒绝原因、trace、input/output hash 和 EventEnvelope。
- 同一 Kill Switch/guard 幂等键和同一 payload 重放返回原结果，换 payload 或错误版本拒绝；本切片不读取凭证、不调用网络或平台 API。
## 目录边界

拥有目录：

- `modules/distribution`

允许目录：

- `modules/distribution`
- `adapters/contract`
- `adapters/manual`
- `adapters/fake`
- `tests/replay`
- `packages/contracts`
- `packages/db/migrations`
- `tests/unit`
- `tests/integration`
- `tests/contract`

禁止目录：

- `adapters/platforms`
- `deploy/environments/prod`
- `deploy/environments/prod/secrets`
- `secrets`
- `**/*.pem`
- `**/*secret*.json`
- `**/*token*.json`

## 权限、幂等、失败和审计

- 由 `TenantContext` 注入 `org_id` 和 actor；跨租户访问必须拒绝。
- 写命令使用 `Idempotency-Key` 和 payload hash；状态修改使用 `If-Match` 或 expected version。
- 确定性校验失败不重试；临时失败按任务卡与策略退避；未知外部结果转人工核查。
- 记录 `trace_id`、actor、输入/输出版本、Policy 快照、拒绝原因、耗时和成本。

## Given–When–Then

Given：

- `所有前置任务已完成`
- `TenantContext、trace_id 和 Idempotency-Key 可用`

When：

- `执行 DIST-008B 的公开用例或内部命令`

Then：

- `实现 Intent 交付模式校验和全局/平台/账号范围 Kill Switch。`
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- global/platform/account/target 任一匹配的 paused switch 只阻断其 blocked_delivery_modes；不同租户的同一 account/platform ID 不互相影响。
- simulation、draft_only 和 authorized_api 被暂停时不创建 attempt；manual_export 作为无外部副作用的安全路径仍可生成私有包。
- Kill Switch paused/resumed 事件、版本、scope、blocked modes 和审计哈希可重放；幂等键换参数返回 `IDEMPOTENCY_KEY_REUSED`。
- TargetVersion 未声明的 delivery mode、无连接的 connected mode、Policy deny、Approval 缺失和跨租户访问均在写入前拒绝。

回滚：

- 关闭 Distribution mode gate 和 Kill Switch 命令入口，保留原 Intent、DeliveryAttempt、ExportPackage、PublicationRecord、事件和审计事实。
- 本 revision 不创建业务表，gate 使用内存投影；若需回退迁移，执行 `python -m alembic downgrade 20260919_found_dist_008a`。

## 验证

```text
python -m pytest tests/unit/distribution tests/integration --maxfail=1
```

Gate：`dist_008b_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
