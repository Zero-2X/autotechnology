# MODEL-001 — （可选外部依赖，不得阻塞 M1）通过 `ModelPort` 接入一个经批准的非平台模型 Provider（仅 dev/staging）；记录供应商条款、数据地域、超时、成本和失败降级。没有模型凭证时继续使用 Fake Model 或固定人工 fixture，CI 始终不依赖真实模型。

状态：`done`  
阶段：4（Production、Localization、QA、Policy 和 Approval）  
Owner：`team/model_gateway`  
优先级：`high` / `P1`

## 目标

（可选外部依赖，不得阻塞 M1）通过 `ModelPort` 接入一个经批准的非平台模型 Provider（仅 dev/staging）；记录供应商条款、数据地域、超时、成本和失败降级。没有模型凭证时继续使用 Fake Model 或固定人工 fixture，CI 始终不依赖真实模型。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-010`
- `MODEL-CORE-002`
- `CANON-002`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `MODEL-001.implementation`
- `MODEL-001.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/model-gateway.schema.json`
- `packages/contracts/jsonschema/model-call.schema.json`
- `packages/contracts/jsonschema/approved-model-provider.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_model_001.py`

## 实现规格

- `ApprovedExternalProvider` 实现既有 `ModelPort`，外部 SDK/网络由运行时注入的 `ProviderTransport` 隔离；模块本身不读取环境变量、不持有原始密钥，也不直接访问网络。
- 仅当 GOV-010 证据完整、selection approved、环境为 dev/staging、数据地域在批准范围、调用 timeout/cost 不超过批准上限时允许外部路由；凭证只接受不透明 `secretref://` 引用。
- 缺少凭证时直接使用 FakeModelProvider；外部 timeout/unavailable 时降级到 Fake，Schema、预算、地域、证据或权限错误 fail closed，不伪装为外部成功。
- `ModelGateway.register_approved_config` 保存条款版本、处理地域、保留期和审批证据；ModelCall 记录实际 provider、成本、耗时和 attempt，事件同时记录 configured/actual provider 与 fallback reason，且不含凭证或明文输入。
- CI 和专项测试只使用内存 transport 与固定 fixture，transport 在无凭证场景的调用次数必须为零；真实 EXT-MODEL-001 凭证保持可选且未配置，不阻塞 Fake 基线。
## 目录边界

拥有目录：

- `modules/model_gateway`

允许目录：

- `modules/model_gateway`
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

- `执行 MODEL-001 的公开用例或内部命令`

Then：

- `（可选外部依赖，不得阻塞 M1）通过 `ModelPort` 接入一个经批准的非平台模型 Provider（仅 dev/staging）；记录供应商条款、数据地域、超时、成本和失败降级。没有模型凭证时继续使用 Fake Model 或固定人工 fixture，CI 始终不依赖真实模型。`
- `输出契约、审计事件和指定测试结果可复现`

补充场景：

- 完整批准证据、dev/staging 环境和安全 credential ref 可通过注入式 transport 返回结果，并记录条款、地域、成本、耗时和实际 provider。
- 无 credential ref 或外部 timeout/unavailable 时返回固定 Fake 结果，记录降级原因，幂等重放不再次调用 transport 或 Fake。
- production、缺失审批证据、未批准地域、raw credential、超出 timeout/cost 上限、输出 Schema 不符和跨租户请求均拒绝。
- CI 不依赖真实模型、真实凭证或网络；本地 GOV-010 清单仍保持未选择供应商的 No-Go 事实，不被测试 fixture 改写。

回滚：

- 移除外部 Provider 注册或停用其配置，所有无凭证调用继续使用 Fake/固定 fixture；保留既有 ModelCall、条款与降级审计证据。
- 本 revision 不创建业务表，回退执行 `python -m alembic downgrade 20260919_found_agent_core_005e`。

## 验证

```text
python -m pytest tests/unit/model_gateway tests/integration --maxfail=1
```

Gate：`model_001_acceptance`

## 外部依赖

- `EXT-MODEL-001`（可选运行时凭证，当前未配置；Fake/fixture 基线已完成）

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
