# MODEL-003 — 实现预算门禁：按组织、任务、模型和周期累计成本；超预算停止新模型任务并生成审计事件。

状态：`done`  
阶段：4（Production、Localization、QA、Policy 和 Approval）  
Owner：`team/model_gateway`  
优先级：`high` / `P1`

## 目标

在 Model Gateway 中增加租户范围的版本化预算策略、并发安全的调用预占和实际成本结算，按组织、任务、模型及 task/day/month 周期累计成本；超限在供应商调用前阻断并留下审计事件。

## 明确不做

- 不修改供应商适配器和真实平台目录，不读取凭证，不发起额外网络调用。
- 不把 Prompt、请求正文或模型输出写入预算策略、用量事实或预算事件。
- 不删除历史成本事实；预算策略和用量账本只追加，reservation 只承载未结算状态。

## 前置依赖

- `GOV-008`
- `MODEL-CORE-002`
- `CANON-002`
- `MODEL-001`

## 输入

- `TenantContext(org_id, actor_id)`、`trace_id`、`Idempotency-Key`
- `BudgetPolicy` 的 policy key/version、`org`/`task`/`model` 三类 scope、task/day/month 周期和 cents 上限
- 带 `task_id` 的 `ModelRequest`、ModelConfig、单次 timeout 与 request budget
- Provider 返回的实际成本、状态和 ModelCall ID

## 输出

- 不可变 `BudgetPolicy`、`BudgetUsage` 和命令幂等事实
- 生命周期受控的 `BudgetReservation`
- `model.budget.policy.registered`、`model.budget.reserved`、`model.budget.exceeded`、`model.budget.settled` 审计事件
- 超限时状态为 `budget_exceeded` 的 ModelCall 事实，且 Provider 调用次数为零

## 契约与迁移

契约：

- `packages/contracts/jsonschema/model-gateway.schema.json`
- `packages/contracts/jsonschema/model-call.schema.json`
- `packages/contracts/jsonschema/model-budget-policy.schema.json`
- `packages/contracts/jsonschema/model-budget-decision.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移：

- `packages/db/migrations/versions/20260919_model_003.py`

新增 `model_budget_policies`、`model_budget_usage`、`model_budget_reservations` 和 `model_budget_commands`；policy、usage、command 由数据库触发器保护为追加式。

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
- `docs/foundation`
- `docs/tasks`
- `scripts`

禁止目录：

- `adapters/platforms`
- `deploy/environments/prod`
- `deploy/environments/prod/secrets`
- `secrets`
- `**/*.pem`
- `**/*secret*.json`
- `**/*token*.json`

## 实现规格

1. `BudgetService.register_policy` 按 `(org_id, policy_key, version_no)` 追加策略，要求 expected previous version 和三类 scope；同一幂等键重放相同策略，payload 变化或跳版本拒绝。
2. 每个 limit 使用 `org`/`task`/`model` 与 `task`/`day`/`month` 组合；精确 task/model key 优先，`*` 作为受控默认。所有周期上限不得超过 GOV-008 的 200/2500/30000 cents。
3. `ModelGateway.call` 在 ModelConfig 和调用幂等校验后先按 request budget 预占；预算服务缺失或超限 fail closed，不进入 Provider。Gateway 锁和 BudgetService 锁共同防止并发同 key 双调用。
4. Provider 成功按实际 `cost_cents` 结算并写 Usage；timeout/失败释放预占并保留零成本状态，Provider 回报负成本或超过 request budget 时失败。
5. Usage 查询按 org、task、model 汇总，日期/月窗口使用 UTC；历史事实和审计事件不接受更新/删除。
6. ModelRequest 增加可选 `task_id`，ModelCall contract 返回 task_id；未提供 task_id 的旧 Fake 调用进入 `unscoped`，不改变既有调用兼容性。

## Given–When–Then

补充场景：

- Given 合法策略和未超限 request，When 调用 Gateway，Then 先产生 reservation，再调用一次 Provider，最后按实际成本结算并记录 task/model 用量。
- Given org、task 或 model 任一适用周期已达到上限，When 创建新 ModelCall，Then 返回 `BUDGET_EXCEEDED`，不调用 Provider，保存失败 ModelCall 和 deny 事件。
- Given 相同 org 与 Idempotency-Key 并发提交，When 两个 worker 同时调用，Then 只产生一个 Provider 调用和一个 usage fact，另一个返回同一 ModelCall。
- Given 同一策略或调用幂等键使用不同 payload，When 重放，Then 返回 `IDEMPOTENCY_KEY_REUSED`，不创建第二版本或 reservation。
- Given Provider timeout、暂时不可用或输出成本超过 request budget，When Gateway 结束尝试，Then 按原有重试规则收敛，reservation 被释放，错误码和审计保留。
- Given 新 UTC 日或月，When 查询累计成本，Then day/month 窗口正确切换，历史月份不计入当前窗口；跨 org 的 policy、usage 和 call 被拒绝。
- Given limit 超过 GOV-008 上限、负数、重复 scope/period/key 或缺少 scope，When 注册策略，Then 确定性拒绝且不写入事实。

## 权限、幂等、失败和审计

- policy、reservation、settlement 全部绑定 `org_id`；ModelConfig 的 org 与 request.org_id 必须一致。
- 确定性预算拒绝不重试；Provider 暂时错误仍由 Model Gateway 的既有 retry allowlist 控制。
- 审计只写 IDs、scope、period、限额、已用/请求 cents、task/model 名和 trace，不写请求正文或凭证。

## 回滚

停止新预算策略和预算 gate，保留已有 ModelCall、Usage 和 deny 事件只读；Alembic 降级到 `20260919_found_eval_001` 前先导出预算审计，避免删除成本证据。

## 验证

```text
python -m pytest tests/unit/model_gateway tests/integration --maxfail=1 -q
python scripts/check_task_card_precision.py --task MODEL-003 --strict
python scripts/check_json_schemas.py
python scripts/check_architecture.py
python scripts/check_migrations.py
```

Gate：`model_003_acceptance`

## 外部依赖

- 无；预算与 Provider 调用在本地 Fake 运行时可复现。
