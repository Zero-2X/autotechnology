# GEO_REGION-CORE-001 — 建立最小 `RegionProfile` 身份对象和不可变 `RegionProfileVersion`：region_code、locales、timezone、格式、单位、货币、保留期、删除 SLA、Policy 快照、有效期和 current pointer 原子更新。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/geo_region`  
优先级：`critical` / `P0`

## 目标

建立最小 `RegionProfile` 身份对象和不可变 `RegionProfileVersion`：region_code、locales、timezone、格式、单位、货币、保留期、删除 SLA、Policy 快照、有效期和 current pointer 原子更新。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `GOV-007`
- `FOUND-000`
- `FOUND-004A`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `GEO_REGION-CORE-001.implementation`
- `GEO_REGION-CORE-001.tests`
- `audit_evidence`

## 实现规格

`RegionProfile` 字段：`id`、`org_id`、`region_code`、`status=active|disabled`、`current_version_id`。`RegionProfileVersion` 字段：`id`、`profile_id`、`version_no`、`locales[]`（BCP-47）、`timezone`（IANA）、`date_format`、`number_format`、`units`、`currency`、`retention_days`、`deletion_sla_hours`、`policy_snapshot_ref`、`valid_from`、`valid_to`、`content_hash`。版本不可变；同一 profile 仅允许一个 current pointer，更新在同一事务中完成；`valid_to > valid_from`。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/region-profile.schema.json`
- `packages/contracts/jsonschema/region-profile-version.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_geo_region_core_001.py`
## 目录边界

拥有目录：

- `modules/geo_region`

允许目录：

- `modules/geo_region`
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

- `执行 GEO_REGION-CORE-001 的公开用例或内部命令`

Then：

- `建立最小 `RegionProfile` 身份对象和不可变 `RegionProfileVersion`：region_code、locales、timezone、格式、单位、货币、保留期、删除 SLA、Policy 快照、有效期和 current pointer 原子更新。`
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- 非法 IANA timezone、BCP-47 locale 或 ISO-4217 currency 返回 `REGION_PROFILE_INVALID`。
- 并发发布两个版本时只有一个 current pointer 生效，另一事务返回 `VERSION_CONFLICT`。
- 删除 profile 前必须无未完成 workflow 引用，否则返回 `REGION_IN_USE`。


## 验收证据

- `modules/geo_region` 提供租户范围内 RegionProfile、不可变版本、IANA timezone/BCP-47 locale/ISO-4217 currency 校验和 current pointer 乐观并发检查。
- 版本有效期、保留期、删除 SLA 和 content_hash 固化在版本记录；无效配置、跨租户访问和旧 pointer 更新分别返回明确错误码。
- 单元测试覆盖版本单调性、pointer 冲突、格式校验和租户隔离；迁移为无业务表 no-op。

## 回滚与运行说明

- 通过任务级 feature flag 关闭新命令；已提交的业务事实和审计记录不删除。
- 迁移按 expand/contract 顺序执行；验证失败时停止后续任务，保留兼容字段，不执行破坏性回滚。
- 如产生可重试任务，先暂停对应队列，再按原幂等键重放；任何外部未知结果必须转人工核查。

## 验证

```text
python -m pytest tests/unit/geo_region tests/integration --maxfail=1
```

Gate：`geo_region_core_001_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
