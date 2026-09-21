# GEO_REGION-001 — locale/market 配置与不可变区域版本

状态：`done`  
阶段：5（第一方知识中心、GEO_CONTENT 和 GEO_REGION）  
Owner：`team/geo_region`  
优先级：`high` / `P1`

## 目标

建立租户范围的 `RegionProfile` 根对象和不可覆盖的 `RegionProfileVersion` 配置版本，统一保存 locale、市场、术语版本、单位、货币、IANA 时区、法规/披露规则、受限主题、数据地域、保留/删除 SLA 和平台地区资格。下游只引用具体激活版本，不在运行时读取可变根对象。

## 明确不做

- 不实现 GEO_REGION-002 的页面区域检查、hreflang、地区禁用内容或地域删除执行。
- 不修改 Production/Site 前置事实，不调用真实平台、账号、网络或凭证。
- 不把区域配置解释为法律意见；规则只提供可复现的配置快照和门禁输入。
- 不在激活版本上覆盖业务配置；变更创建新的 draft 版本。

## 前置依赖

- `GEO_REGION-CORE-001`
- `PROD-002`
- `PROD-003`

## 精确输入

- `tenant_context` 或 `org_id`、actor、`trace_id`、非空 `idempotency_key`。
- Profile：规范化 `region_code`（同租户唯一），可选显式 UUID。
- Version：`region_profile_id`、唯一 locale 列表、IANA `timezone`、`date_number_format`、`units`、ISO 风格三字母 `currency`、`terminology_version`。
- 规则：`disclosure_rules`、`restricted_topics`、`platform_eligibility`，以及非空 `data_residency`。
- 生命周期：非负 `retention_days`、`deletion_sla_hours`，可空 Policy/有效期/复核日期；激活时 Policy、有效区间、正数删除 SLA 和数据地域必须完整。
- 版本写入携带当前 Profile 指针预期值；激活/退役携带 `expected_version` 或 `If-Match`。
- 可选 `predecessor_artifacts` 与 `policy_snapshot`；任意深度的租户标记和就绪状态均失败闭合。

## 精确输出

- `RegionProfile`：`id`、`org_id`、`region_code`、`current_version_id`、`status`、`created_at`。
- `RegionProfileVersion`：`packages/contracts/jsonschema/region-profile-version.schema.json` 声明的全部字段；`snapshot_hash` 覆盖规范化业务配置，不包含 clock、actor、trace、状态或幂等键。
- 兼容投影只为现有 PROD-004 只读 Port 提供字段别名，不改变闭合契约输出。
- 审计和注册事件：`region.profile.created`、`region.profile_version.created`、`region.profile_version.activated`、`region.profile_version.retired`。

## 实现规格

### 生命周期

- Profile：`none → active → retired`；只有同租户 Owner 用例可移动 current pointer。
- Version：`none → draft → active → retired`。激活新版本时原 current active 版本以替代原因为由退役，并原子切换 Profile 指针。
- draft 可以在激活命令中补齐 Policy/有效期；一旦 active，业务配置和 snapshot hash 不可修改。
- 退役当前版本时清空 Profile current pointer；退役理由必填。

### 校验

- locale 采用结构化 BCP-47 形式并规范化，列表非空、大小写无关去重；时区必须由 `zoneinfo.ZoneInfo` 识别。
- units 只允许 `metric|imperial|mixed`；currency 为三个大写字母；整数不接受布尔值或负数。
- `valid_from`、`valid_to`、`review_due_at` 必须带时区；有完整有效期时 `valid_to > valid_from`，复核日期不得早于生效时间。
- 规则数组只接受非空字符串或带可识别名称的有限 JSON 对象；平台列表只接受非空唯一字符串。
- 输出在每个写入边界通过闭合 JSON Schema；数据库复合外键和 SQLite 触发器执行同租户引用。

### 幂等、并发与审计

- 命令 hash 覆盖租户、规范化业务 payload、前置 hash 和 Policy hash，不包含 clock、actor、trace 或生成时间。
- 同租户/命令命名空间/幂等键的相同 payload 重放原对象；不同 payload 返回 `IDEMPOTENCY_KEY_REUSED`。
- Profile 唯一性、version_no 分配、current pointer 和状态转换在同一 `RLock` 临界区完成。
- 拒绝、成功与替代退役均记录 trace、actor、输入/输出版本与 hash、Policy hash、原因、耗时和成本；事件 envelope 使用 event_id 去重语义。

## 契约与迁移

- Profile 契约：`packages/contracts/jsonschema/region-profile.schema.json`。
- Version 契约：`packages/contracts/jsonschema/region-profile-version.schema.json`。
- Union：`packages/contracts/jsonschema/geo_region.schema.json`。
- 迁移：`packages/db/migrations/versions/20260920_geo_region_001.py`。
- 迁移创建 `region_profiles` 和 `region_profile_versions`，为 Profile current pointer、Version→Profile、SitePageVersion→RegionVersion 建立同租户引用，并阻断身份覆盖、非法状态迁移、删除和 `INSERT OR REPLACE`。

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

## Given–When–Then

Given：

- 前置任务完成，同租户 Profile、TenantContext、trace 和幂等键可用；
- draft 包含可验证的 locale/market 配置，激活所需 Policy、有效期、删除 SLA 和数据地域完整。

When：

- 创建 Profile、创建 draft、激活或退役 Version，并使用相同/冲突幂等 payload 重放。

Then：

- 输出通过闭合 Profile/Version Schema，snapshot hash 与业务配置一致；
- version_no 单调递增，current pointer 原子切换，旧 active 版本退役且历史仍可审计；
- 跨租户、陈旧指针/版本、非法状态、缺失激活字段和无效配置均以稳定错误码拒绝；
- 相同 payload 在 clock、actor、trace 变化后仍重放原对象，不重复事件。

## 补充场景

- 同租户重复 region_code、显式 ID 冲突、跨租户 ID 复用和跨租户读取均拒绝且不泄露数据。
- locale 重复、未知时区、小写/超长 currency、非法 units、布尔整数、倒置有效期和畸形规则均不得进入存储。
- 同一幂等键跨 Profile/Version 命令命名空间可复用；同一命名空间不同 payload 必须冲突。
- 激活新版本自动退役旧 current；退役非 active 版本、缺少原因或错误 If-Match 均拒绝。
- PostgreSQL 声明复合 FK；SQLite 在默认未启用 PRAGMA FK 时仍通过触发器拒绝缺失或跨租户父记录。

## 回滚

- 停止新的区域配置命令，并在降级前导出 Profile、Version、事件和审计到受控证据归档。
- 移除 SitePageVersion 的 RegionVersion 约束后降级到 `20260920_geo_content_003`；数据库内区域表被删除，其他模块事实保持不变。
- 恢复任务注册表与契约/迁移清单，并用归档支持历史复核。

## 验证

```text
python -m pytest tests/unit/geo_region tests/integration/test_geo_region_001.py tests/contract/test_geo_region_001_contract.py -q
python scripts/check_json_schemas.py
python scripts/check_migrations.py --strict --json
python scripts/check_task_card_precision.py --task GEO_REGION-001 --strict
```

Gate：`geo_region_001_acceptance`

## 外部依赖

- 无；实现和验收完全离线。
