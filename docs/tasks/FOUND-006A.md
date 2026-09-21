# FOUND-006A — 建立健康检查、业务/技术指标基类和 Prometheus 暴露。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/foundation`  
优先级：`critical` / `P0`

## 目标

建立无外部网络副作用的健康检查注册表、业务/技术指标基类和 Prometheus 0.0.4 文本暴露端点，为 API、Worker、Scheduler 和后续业务模块提供统一且低基数的观测接口。

## 明确不做

- 不实现 FOUND-006B 的 OpenTelemetry tracing、模型成本记录或跨进程 trace exporter。
- 不接入 Grafana、Alertmanager、Pushgateway 或远程 Prometheus 服务。
- 不持久化指标样本，不把 PostgreSQL、Redis 或对象存储作为指标事实源。
- 不把 `org_id`、`actor_id`、`trace_id`、`request_id`、对象 ID、凭证或任意 payload 放进 metric label。
- 不修改任务注册表中的禁止目录，不调用真实平台或读取真实凭证。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-005`

## 输入

- `infra/foundation/database.py` 的非秘密配置健康快照。
- `infra/foundation/observability.py` 的 API composition/middleware 边界。
- `apps/api/main.py` 的 `/health/live`、`/health/ready` 入口。
- `docs/governance/tech-stack-baseline-v1.yaml` 的 Prometheus-compatible metrics 约束。

## 输出

- `infra/foundation/metrics.py`：HealthCheck/HealthRegistry、Counter/Gauge/Histogram、MetricRegistry 和 Prometheus 文本编码。
- `apps/api/main.py`：统一 readiness 评估、API 技术指标采集和 `/metrics` 暴露。
- `docs/foundation/metrics-health-baseline-v1.yaml`：健康和指标安全基线。
- `packages/contracts/jsonschema/metrics-baseline.schema.json`：基线机器契约并纳入 foundation union。
- `packages/contracts/openapi/openapi.yaml`：health 任务归属和 `/metrics` 契约。
- `packages/db/migrations/versions/20260916_found_006a_health_metrics.py`：不新增持久化表的连续可逆检查点。
- `tests/contract/test_found_006a_metrics.py`、`tests/integration/test_found_006a_metrics_integration.py`。
- `docs/foundation/FOUND-006A-EVIDENCE.yaml`：验证、副作用和回滚证据。

## 实现规格

1. `HealthRegistry` 接受命名的同步检查函数；每个函数返回 `HealthCheckResult(component, status, critical, details)`。允许状态为 `ready|configured|degraded|unavailable|invalid_configuration|not_configured`。liveness 只证明进程可响应，不调用依赖；readiness 聚合检查结果，critical 的 invalid/unavailable 优先，其次 degraded/not_configured/configured/ready。
2. 默认 database check 只调用 `DatabaseSettings.from_env()` 和 `database_health()`；未显式注入 probe 时不得访问网络。所有 details 都必须是非秘密快照。
3. `MetricDefinition` 明确 `scope=technical|business`、`kind=counter|gauge|histogram`、help、label 名和 histogram buckets。名称及 label 必须符合 Prometheus 标识符规则；禁止高基数/敏感 label，尤其任何 `*_id`、token、secret、credential、password、payload、prompt、content 和 query。
4. `Counter` 只能增加有限非负数；`Gauge` 接受有限数字；`Histogram` 只观察有限非负数并输出累计 bucket、sum 和 count。label 集必须与定义精确一致，值不得为空、含控制字符或超过 128 字符。
5. `MetricRegistry` 对定义和样本使用进程内锁，拒绝同名冲突定义，并以确定性顺序输出 Prometheus text format 0.0.4。输出只包含数值和有界 label，不包含 TenantContext 或请求 payload。
6. 默认技术指标为 HTTP request counter、duration histogram 和 dependency readiness gauge；默认业务基类为 business events counter。API middleware 使用路由模板而不是原始 URL 作为 label，并排除 `/metrics` 自采集。
7. `GET /metrics` 返回 `text/plain; version=0.0.4`，不执行外部探测。`/health/live`、`/health/ready` 保留 correlation response fields；readiness 同步更新非租户 dependency gauge。
8. 本任务不需要数据库对象；revision 仅作为连续、可升级/可降级的 runtime contract checkpoint。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/foundation.schema.json`
- `packages/contracts/jsonschema/metrics-baseline.schema.json`
- `packages/contracts/openapi/openapi.yaml`

迁移 revision：

- `packages/db/migrations/versions/20260916_found_006a_health_metrics.py`

## 目录边界

拥有目录：

- `infra/foundation`

允许目录：

- `infra/foundation`
- `apps`
- `packages`
- `infra`
- `deploy/environments/dev`
- `deploy/environments/staging`
- `scripts`
- `docs`
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

- `/metrics` 只暴露无租户、无 payload 的聚合样本；不把 correlation 或身份字段作为 label。
- 指标更新是进程内原子操作；重复注册相同定义返回既有 collector，不重复创建时间序列；冲突定义确定性拒绝。
- 健康检查异常转换为 `unavailable` 的脱敏结果，不把 traceback 或原始秘密写入响应。
- 本任务无写 API、无 Idempotency-Key、无外部副作用；审计证据记录 schema、迁移、测试和暴露格式。

## Given–When–Then

Given：

- `GOV-006、FOUND-000 和 FOUND-005 已完成`
- `API 使用默认 synthetic/no-network health registry 和独立 MetricRegistry`

When：

- `调用 /health/live、/health/ready、普通 API 路由和 /metrics`
- `注册并更新 technical/business counter、gauge 和 histogram`

Then：

- `liveness 不执行依赖检查；readiness 聚合 database 等检查并保持既有非秘密响应契约。`
- `普通请求按 method、route template 和 status_class 更新 counter/duration，/metrics 不自增。`
- `Prometheus 文本包含 HELP/TYPE、counter、gauge、histogram bucket/sum/count，顺序可复现。`
- `缺 label、多 label、负 counter、NaN/Infinity、非法名称、非法 bucket 和同名冲突定义确定性拒绝且不产生部分样本。`
- `org_id/actor_id/trace_id/request_id、任意 *_id、token/secret/password/payload/prompt/content/query label 被拒绝。`
- `健康检查抛异常时 readiness 返回 unavailable 且不回显原始异常；无网络、数据库写入、真实凭证或平台调用。`
- `OpenAPI、JSON Schema、迁移、任务证据和全量测试结果可复现。`

## 验证

```text
python -m pytest tests/contract/test_found_006a_metrics.py tests/integration/test_found_006a_metrics_integration.py -q
python scripts/check_task_card_precision.py --task FOUND-006A --strict
python scripts/check_migrations.py --strict --json
python scripts/check_openapi_contract.py
python -m pytest tests --maxfail=1 -q
```

Gate：`found_006a_acceptance`

## 外部依赖

- 无；Prometheus server、exporter 和 dashboard 不属于本任务。

## 开工前细化

已完成：输入、输出、健康状态聚合、指标类型、label 安全、Prometheus 暴露、迁移检查点、七类验收场景和副作用边界已冻结并实现。专项测试、全量回归、OpenAPI、迁移、任务精度和注册表检查均通过；无外部网络、真实凭证、数据库写入或平台副作用。
