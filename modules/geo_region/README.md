# geo_region

## 职责

Region, language, units, currency, retention and residency profiles.

## 固定布局

- domain/：实体、值对象、状态机和纯规则。
- application/：公开用例、命令、事务边界和权限检查。
- ports/：外部接口抽象和 DTO。
- infrastructure/：本地实现、仓储和事件发布器。
- projections/：可重建的只读投影。

## 表

- `region_profiles`：租户内唯一的区域身份与当前激活版本指针。
- `region_profile_versions`：不可删除的 locale/market 配置快照；只允许 `draft → active → retired`。
- `region_policy_decisions`：GEO_REGION-002 页面资格决策与地域删除计划的追加式、非敏感投影。

迁移 `20260920_geo_region_001` 还为 `site_page_versions.region_profile_version_id` 增加同租户引用保护。

## 公开接口

`modules.geo_region` 导出：

- `InMemoryRegionService` / `GeoRegionService` / `RegionProfileService`
- `InMemoryRegionStore`
- `RegionProfile` / `RegionProfileVersion`
- `RegionEligibilityService` / `RegionCheckDecision`
- `RegionDeletionService` / `RegionDeletionPlan`
- `InMemoryRegionPolicyStore`
- `RegionError`

服务提供 Profile 创建/退役、Version draft/激活/退役、租户隔离查询、幂等命令、If-Match/current-pointer 并发保护和审计事件。`RegionProfileVersion.as_contract()` 返回闭合契约；`as_compatibility_projection()` 只为旧 Production 只读 Port 提供字段别名。

`RegionEligibilityService` 按调用方明确指定的不可变版本检查有效期、locale/market、数据地域、平台、地区禁用、受限主题和披露要求，并提供确定性的 hreflang 过滤。`RegionDeletionService` 从同一版本计算保留期和删除 SLA，只把合格计划交给现有五阶段删除传播 Port；缺失策略和 legal hold 进入人工复核，不物理删除区域、页面或审计事实。

## 事件

- `region.profile.created`
- `region.profile_version.created`
- `region.profile_version.activated`
- `region.profile_version.retired`

事件使用公共 envelope、确定性 event id 和 payload hash；同一幂等命令重放不会重复发出事件。

## 权限

所有租户业务调用必须经过 TenantContext 和授权检查。

## 公开边界

接口、事件和权限由对应任务卡与 JSON Schema 登记；本目录不得直接依赖其他模块的 infrastructure、FastAPI、ORM 或供应商 SDK。

## 禁止事项

不得保存 Token、完整 PII 或二进制；无账号阶段不得调用真实平台。

## 验证

```text
python -m pytest tests/unit/geo_region tests/integration/test_geo_region_001.py tests/integration/test_geo_region_002_migration.py tests/integration/test_geo_region_002_site_render.py tests/contract/test_geo_region_001_contract.py tests/contract/test_geo_region_002_contract.py -q
python scripts/check_json_schemas.py
python scripts/check_migrations.py --strict --json
python scripts/check_task_card_precision.py --task GEO_REGION-002 --strict
```
