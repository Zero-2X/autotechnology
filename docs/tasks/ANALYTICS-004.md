# ANALYTICS-004 — 建立 GEO_CONTENT 与 GEO_REGION 分开的指标和数据质量检查。

状态：`done`  
阶段：9（Analytics、Feedback Loop 和 Support）  
Owner：`team/analytics`  
优先级：`high` / `P1`

## 目标

建立 GEO_CONTENT 与 GEO_REGION 分开的指标和数据质量检查。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GEO_CONTENT-003`
- `GEO_REGION-002`
- `DIST-010`
- `ANALYTICS-002`
- `ANALYTICS-003`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `ANALYTICS-004.implementation`
- `ANALYTICS-004.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/observation.schema.json`
- `packages/contracts/jsonschema/analytics-geo-quality-snapshot.schema.json`

迁移：

- `packages/db/migrations/versions/20260921_analytics_004.py`
## 目录边界

拥有目录：

- `modules/analytics`

允许目录：

- `modules/analytics`
- `packages/contracts`
- `packages/db/migrations`
- `tests/unit`
- `tests/integration`
- `tests/contract`

禁止目录：

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

- `执行 ANALYTICS-004 的公开用例或内部命令`

Then：

- `建立 GEO_CONTENT 与 GEO_REGION 分开的指标和数据质量检查。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/analytics tests/integration --maxfail=1
```

Gate：`analytics_004_acceptance`

## 外部依赖

- 无

## 实现规格

1. `GeoQualityService` 只接受 schema-valid Observation，并按 `org_id + dedupe_key` 选择最高 `observation_version`，再应用 UTC 半开时间窗、region 和 locale 过滤。
2. `geo.content.*`/`geo_content.*` 与 `geo.region.*`/`geo_region.*` 使用固定 `analytics-004.v1` 别名表分别聚合；输出 `content` 和 `region_quality` 两个独立投影。
3. 未知值不进入分母；raw/estimated、缺失 locale/region、不支持指标和未知值写入 `quality_issues`，存在这些质量问题时快照为 `needs_review`。
4. account-free source（fake、manual、site、qa、geo、support）可直接计算；platform Observation 必须带已验证账号证据，否则返回 `EXT_ACCOUNT_UNAVAILABLE`。
5. 快照、命令、审计和 Outbox 只保存窗口、ID、状态和哈希，不保存 metric value；同组织同幂等键同 payload 重放，payload 改变返回 `IDEMPOTENCY_KEY_REUSED`。
6. SQLite/PostgreSQL 迁移保护快照与输入 Observation 的同租户绑定、哈希和 append-only 事实；降级只删除本任务表。

## 补充场景

- 同一 dedupe key 的旧版本在窗口内、新版本在窗口外时，只计入最新版本，因此结果不重复计数。
- 只有 GEO_CONTENT 或只有 GEO_REGION 输入时，另一侧仍返回空投影；不得把一侧结果复制到另一侧。
- 所有输入都不支持或不在窗口内时拒绝生成快照；跨租户输入、版本身份变化和非法时间窗确定性拒绝。
- 平台账号证据中的 token、secret、password、cookie 和 authorization 字段被拒绝。

## 回滚

停止新的 GEO 质量快照计算，保留既有 Observation 与已发事件；Alembic 降级到 `20260920_analytics_003` 删除本任务快照/命令表，不删除输入 Observation。
