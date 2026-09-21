# FOUND-007A — 创建 OpenAPI 基线、统一错误码和版本兼容规则。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/foundation`  
优先级：`critical` / `P0`

## 目标

把当前 OpenAPI 3.1 文档、稳定错误码和兼容规则冻结为可检查的机器基线；后续任务只能做向后兼容的增量变更，破坏性变更必须显式升级 API major version 或提交 ADR。

## 明确不做

- 不凭空补齐尚未实施的 API Catalog 操作；未来 38 个 Catalog 缺口继续保持 planned warning。
- 不实现任何新的业务路由、认证系统或平台发布能力。
- 不修改任务注册表中的禁止目录，不调用真实平台或读取真实凭证。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-001`
- `FOUND-004A`
- `FOUND-006B`

## 输入

- `packages/contracts/openapi/openapi.yaml` 当前 OpenAPI 3.1 文档。
- `packages/contracts/jsonschema/*.schema.json` 的本地 `$ref` 目标。
- `apps/api/main.py` 和 foundation error handlers 的实际错误码。
- `docs/contracts/api-catalog.yaml` 的分期操作清单（若存在）。

## 输出

- `docs/foundation/openapi-compatibility-baseline-v1.yaml`：当前 operation/参数/响应兼容快照。
- `docs/foundation/error-code-catalog-v1.yaml`：稳定错误码、HTTP 状态、retryable 和 owner。
- `scripts/check_openapi_compatibility.py`：检测删除 operation、删除必需参数、收窄参数约束、删除响应和本地 ref 断裂。
- `packages/contracts/jsonschema/api-contract-baseline.schema.json`：基线契约并纳入 foundation union。
- `packages/db/migrations/versions/20260916_found_007a_openapi.py`：不新增业务表的连续检查点。
- `tests/contract/test_found_007a_openapi.py`、`tests/integration/test_found_007a_openapi_integration.py`。
- `docs/foundation/FOUND-007A-EVIDENCE.yaml`。

## 实现规格

1. OpenAPI 基线必须是 3.1.x，所有 operation 有唯一 `operationId`、`x-task-ids` 和 `x-real-account-required`；每个本地 `$ref` 必须指向存在且可解析的 JSON/YAML 文件。
2. Compatibility checker 从当前 OpenAPI 与 baseline 生成稳定 operation key（method + path），拒绝删除已有 operation、删除已有必需参数、把参数从可选改为必需、收窄 `minLength/maxLength/minimum/maximum/enum`，以及删除已有 response code。
3. 新增 operation、可选字段、响应字段和 response code 默认兼容；Catalog 尚未实现的操作只报告 warning，不由本任务自动生成。
4. Error catalog 覆盖当前代码使用的错误码，包括 `INVALID_*`、`INTERNAL_ERROR`、`WORKER_ONLY`、`OUTBOX_*`、`JOB_*`、`RETRY_*`、`REPLAY_*`、`TENANT_SCOPE_VIOLATION`、`REQUEST_VALIDATION_ERROR`；每项声明 `http_status`、`retryable`、`category` 和 owner。
5. `/internal/*` worker-only 端点必须显式声明 `X-Worker-Id`；写操作的 `Idempotency-Key` 必须使用公共参数并保留 8～200 字符约束；状态修改继续使用 `If-Match` 或 expected version。
6. API compatibility baseline 不包含 token、secret、payload、请求样本或真实凭证；只保存路径、方法、参数名/位置、约束摘要、响应 code 和 contract refs。
7. 本任务不改运行时业务逻辑；迁移只是可逆的 runtime contract checkpoint。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/foundation.schema.json`
- `packages/contracts/events/event-envelope.schema.json`
- `packages/contracts/jsonschema/api-contract-baseline.schema.json`
- `packages/contracts/openapi/openapi.yaml`

迁移 revision：

- `packages/db/migrations/versions/20260916_found_007a_openapi.py`

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

- OpenAPI 基线只描述契约，不读取身份凭证；错误 catalog 不记录秘密值。
- 兼容检查失败是确定性 gate，不修改当前 OpenAPI 或 baseline。
- planned Catalog 差异是 warning；当前已实现 operation 的破坏性变化是 error。
- 证据记录 baseline、checker、error catalog、迁移和测试输出。

## Given–When–Then

Given：

- `GOV-006、FOUND-000、FOUND-001、FOUND-004A 和 FOUND-006B 已完成`
- `当前 OpenAPI 3.1 文档和本地 JSON Schema refs 可读取`

When：

- `执行 OpenAPI compatibility checker、error catalog contract test 和 API integration test`
- `构造删除 operation、必需参数、响应 code 或收窄约束的临时变体`

Then：

- `当前 OpenAPI 通过结构、operationId/task mapping、本地 ref、worker/idempotency 参数和 error response 检查。`
- `兼容变体通过；破坏性变体被稳定错误码和路径定位拒绝。`
- `错误 catalog 与实现中稳定错误码覆盖一致，retryable/status/category 不含矛盾。`
- `未来 Catalog 差异保留 warning，不擅自生成业务 API。`
- `无网络、数据库写入、真实凭证或平台副作用；输出可复现。`

## 验证

```text
python -m pytest tests/contract/test_found_007a_openapi.py tests/integration/test_found_007a_openapi_integration.py -q
python scripts/check_task_card_precision.py --task FOUND-007A --strict
python scripts/check_openapi_compatibility.py --strict
python scripts/check_migrations.py --strict --json
python -m pytest tests --maxfail=1 -q
```

Gate：`found_007a_acceptance`

## 外部依赖

- 无；API Catalog 的未来操作由所属任务后续实现。

## 开工前细化

已完成：operation 快照、破坏性变更分类、error catalog 字段、worker/idempotency 参数门禁、planned warning 边界、迁移和验收场景已冻结。本任务从 `planned` 进入 `in_progress`。
