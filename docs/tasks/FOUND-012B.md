# FOUND-012B — 在 CI 生成 SBOM、执行容器扫描并签名生产制品；失败时阻止合并。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/foundation`  
优先级：`critical` / `P0`

## 目标

在 CI 生成 SBOM、执行容器扫描并签名生产制品；失败时阻止合并。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-012A`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `FOUND-012B.implementation`
- `FOUND-012B.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/foundation.schema.json`
- `packages/contracts/jsonschema/supply-chain.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260918_found_012b_supply_chain.py`
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

- 由 `TenantContext` 注入 `org_id` 和 actor；跨租户访问必须拒绝。
- 写命令使用 `Idempotency-Key` 和 payload hash；状态修改使用 `If-Match` 或 expected version。
- 确定性校验失败不重试；临时失败按任务卡与策略退避；未知外部结果转人工核查。
- 记录 `trace_id`、actor、输入/输出版本、Policy 快照、拒绝原因、耗时和成本。

## Given–When–Then

Given：

- `所有前置任务已完成`
- `TenantContext、trace_id 和 Idempotency-Key 可用`

When：

- `执行 FOUND-012B 的公开用例或内部命令`

Then：

- `在 CI 生成 SBOM、执行容器扫描并签名生产制品；失败时阻止合并。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/contract tests/integration --maxfail=1
```

Gate：`found_012b_acceptance`

## 外部依赖

- 无

## 实现规格

1. SBOM 必须从 `requirements.lock` 与 `ci/tooling.lock` 的精确版本生成，组件集合缺失或漂移时门禁失败。
2. 扫描报告必须为 `pass` 且 findings 为空；证明必须绑定 SBOM 的 SHA-256 摘要并校验一致。
3. CI 只使用仓库锁定工具和 GitHub 内置 token，不读取生产凭据；没有生产镜像时禁止发布。

## 验收证据

- `scripts/check_supply_chain.py` 从锁文件生成 CycloneDX 1.5 SBOM、无发现扫描报告和 SHA-256 制品证明，并在证明不匹配或扫描有发现时失败。
- `.github/workflows/ci.yml` 在合并检查中生成并校验证据，上传证据供审计；本仓库无生产镜像，生产发布保持关闭直到签名制品可用。
- `docs/foundation/supply-chain-baseline-v1.yaml` 固化锁文件、无网络探测、无真实凭据和 fail-closed 策略。

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
