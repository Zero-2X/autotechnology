# EVAL-001 — 建立 LLM golden set、Prompt 版本、离线评测、模型成本和回归阈值。

状态：`done`  
阶段：4（Production、Localization、QA、Policy 和 Approval）  
Owner：`team/evaluation`  
优先级：`high` / `P1`

## 目标

建立租户隔离且可重放的 Prompt、合成 golden set 和回归阈值版本，并通过现有 Model Gateway 离线评测质量与模型成本。

## 明确不做

- 不连接真实模型供应商，不读取或生成供应商凭证。
- 不把 Prompt 输入、期望输出或模型输出正文写入 EvalRun 和审计记录。
- 不用合成评测结果宣称生产 SLO 达标，也不实现后续 Graph 级评测。

## 前置依赖

- `GOV-008`
- `MODEL-CORE-002`
- `AGENT-CORE-001`
- `CANON-002`

## 输入

- `TenantContext(org_id, actor_id)`、`trace_id`、`Idempotency-Key`
- Prompt 模板、简单占位符、输入/输出 Schema 引用和 expected previous version
- 仅标记为 synthetic 的 golden cases，以及质量、错误率、绝对成本和相对回归阈值
- 已登记的 Model Gateway 配置；CI 使用 Fake Provider

## 输出

- 不可变 `PromptVersion`、`GoldenSetVersion`、`RegressionThresholdVersion`
- 只含逐 case 哈希、ModelCall 引用、耗时、成本和回归结论的 `EvalRun`
- 不含正文的版本登记与评测完成审计证据

## 契约与迁移

契约：

- `packages/contracts/jsonschema/prompt-version.schema.json`
- `packages/contracts/jsonschema/golden-set-version.schema.json`
- `packages/contracts/jsonschema/regression-threshold-version.schema.json`
- `packages/contracts/jsonschema/eval-run.schema.json`

迁移：

- `packages/db/migrations/versions/20260919_eval_001.py`

迁移新增 `evaluation_prompt_versions`、`evaluation_golden_set_versions`、`evaluation_threshold_versions`、`eval_runs` 和 `evaluation_commands`；记录按租户唯一且追加式不可变。

## 目录边界

拥有目录：

- `packages/prompt_registry`

允许目录：

- `packages/prompt_registry`
- `tests/eval`
- `tests/replay`
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

1. `EvaluationService.register_prompt` 按 `(org_id, prompt_key, version_no)` 追加版本，要求 `expected_previous_version` 与当前版本一致；模板只允许已声明的简单占位符，输入和输出 Schema 必须已登记。
2. `register_golden_set` 只接收合成数据，逐 case 校验输入/期望输出 Schema，固定排序并计算 `dataset_hash`；case ID 在版本内唯一。
3. `register_thresholds` 固化最低 exact-match、最高错误率、单 case/总成本、最大质量下降和最大成本增长；总预算不得超过 GOV-008 的单工作流 200 cents 上限。
4. `run_offline` 只经 `ModelGateway.call` 执行，复用其租户、调用哈希、Schema、成本和 Fake Provider 证据；达到绝对成本上限后不再创建新模型调用。
5. EvalRun 保存 Prompt/dataset/threshold hash、ModelCall ID、输出/期望 hash、模型版本、成本、耗时和 gate 原因，不保存评测正文。候选 run 可与同租户、相同 dataset hash 的 baseline 比较质量下降和成本增长。
6. 所有登记和运行命令按 `(org_id, Idempotency-Key)` 重放首次结果；同 key 不同 payload 拒绝。公开读取统一校验租户，返回深拷贝，调用方不能改写已登记版本。
7. 模型暂时失败、预算拒绝或输出 Schema 错误转为逐 case error，并使阈值 gate 失败；已发生的模型成本仍计入运行证据。

## Given–When–Then

补充场景：

- Given 合法 Prompt v1，When 使用同一幂等键重复登记，Then 返回同一版本；不同 payload、跳号或 stale expected previous version 被拒绝。
- Given 含重复 case、未知 Schema 或不合规输出的 golden set，When 登记，Then 不创建版本和审计事实。
- Given Fake Provider 与全部命中的 golden cases，When 离线评测，Then 每个 case 只产生一个 ModelCall，质量、成本和模型版本可复算，gate 为 passed。
- Given 同一运行命令重放，When 再次提交，Then 返回原 EvalRun 且 Fake Provider 调用次数不增加。
- Given候选 Prompt 的 exact-match 下降或成本增长超过阈值，When 与同一 dataset baseline 比较，Then gate 为 failed 并返回稳定原因码。
- Given 已达到总成本上限，When 仍有待评测 case，Then 不调用模型，把剩余 case 标为 `EVAL_COST_LIMIT_REACHED`。
- Given 模型输出 Schema 非法或 Provider 暂时失败，When 评测，Then case 标为 error，已发生成本保留，正文不进入 EvalRun 或审计。
- Given 跨租户 Prompt、dataset、threshold、baseline、ModelConfig 或 EvalRun 引用，When 读取或执行，Then 返回 `TENANT_SCOPE_VIOLATION`。

## 权限、幂等、失败和审计

- 所有命令要求 UUID 格式的 `org_id`、`actor_id`、非空 trace 和 8–200 字符的 Idempotency-Key。
- 确定性输入、Schema、版本和权限错误不重试；Model Gateway 负责其允许的暂时错误策略。
- 审计仅记录版本 ID/hash、运行 ID/hash、actor、trace、gate 和成本汇总。

## 回滚

停止创建新 Prompt、golden set、threshold 和 EvalRun；已生成的版本、ModelCall 和评测证据保持只读。Alembic 降级到 `20260919_found_model_001` 可移除本任务新增的空评测表，生产数据存在时须先导出审计证据。

## 验证

```text
python -m pytest tests/unit/evaluation tests/integration/test_eval_001_offline_gateway.py -q
python scripts/check_task_card_precision.py --task EVAL-001 --strict
python scripts/check_json_schemas.py
python scripts/check_architecture.py
python scripts/check_migrations.py
```

Gate：`eval_001_acceptance`

## 外部依赖

- 无；CI 和本地只使用 Fake Provider。
