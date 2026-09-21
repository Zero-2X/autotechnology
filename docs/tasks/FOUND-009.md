# FOUND-009 — 建立确定性 FakeClock、合成 fixtures 与私有 FakeStorage 测试工具

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/foundation`  
优先级：`critical` / `P0`

## 目标

提供可复现、租户隔离、无账号、无网络的测试工具。相同 seed、起始时间和操作序列
必须得到相同的身份、时钟、存储元数据和审计快照；工具不得调用模型或平台适配器。

## 明确不做

- 不实现真实 S3、模型网关、平台账号、OAuth 或发布适配器。
- 不把 payload bytes、seed 原文、凭据或异常原文写入审计快照。
- 不修改现有 FakeStorage 的私有、不可变和租户隔离语义。
- 不引入业务领域事实、真实等待或网络请求。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-003A`
- `FOUND-003B`
- `FOUND-005`
- `FOUND-008`

## 输入

- 非空、最多 256 UTF-8 bytes 的 synthetic seed。
- 显式、带时区的 UTC 起始时间；省略时使用固定的 2000-01-01T00:00:00Z。
- 合成对象 key、bytes、content type 和字符串 metadata。

## 输出

- `infra/foundation/testkit.py`：FakeClock、稳定身份、fixture kit 和脱敏审计事实。
- `packages/testkit/__init__.py`：共享测试导入入口。
- `packages/contracts/jsonschema/synthetic-fixture.schema.json`：fixture 快照契约。
- `tests/unit/test_found_009_testkit.py`。
- `tests/integration/test_found_009_fixture_storage.py`。
- `tests/contract/test_found_009_testkit_contract.py`。
- `docs/foundation/FOUND-009-EVIDENCE.yaml`。

## 实现规格

`FakeClock(current)` 只接受带时区时间并归一到 UTC；`now/__call__` 返回当前值，
`advance/sleep` 只推进虚拟时间，`set` 允许保持或向前设置，任何回拨、负数、布尔值、
NaN 或 Infinity 都返回确定性 `FixtureValidationError`。

`FixtureIdentity.from_seed(seed)` 使用 seed 的 SHA-256 和 UUIDv5 派生 `fixture_id`、
`org_id`、`actor_id`、`trace_id`、`request_id` 和 `idempotency_key`。公开快照只包含
`seed_hash`，不得包含 seed 原文。

`SyntheticFixtureKit` 每次创建独立 `FakeStorage`，并公开不可变 `TenantContext`。
`put_object` 使用按 fixture/key 派生的幂等键；同 key 同 payload 返回原对象，同 key
不同 payload 由 FakeStorage 拒绝。所有读取和删除仍由 FakeStorage 校验 `org_id`。

fixture 审计事件只记录稳定 event ID、sequence、事件类型、租户/actor/trace、虚拟时间、
`private://` 引用、content hash 和非敏感元数据，不记录 bytes。重复的相同 put 不追加
第二条审计事实。`as_contract()` 按引用排序对象，并显式返回
`network_access=false`、`model_calls=false`、`platform_calls=false`。

数据库没有新表。为满足一任务一迁移引用的仓库规则，使用可逆 no-op revision
`packages/db/migrations/versions/20260918_found_009_testkit.py` 作为版本边界；其
upgrade/downgrade 不执行 DDL。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/synthetic-fixture.schema.json`
- `packages/contracts/jsonschema/storage-object.schema.json`
- `packages/contracts/jsonschema/foundation.schema.json`

迁移：

- `packages/db/migrations/versions/20260918_found_009_testkit.py`

## 目录边界

拥有目录：

- `infra/foundation`
- `packages/testkit`

允许目录：

- `infra/foundation`
- `packages/testkit`
- `packages/contracts`
- `packages/db/migrations`
- `tests/unit`
- `tests/integration`
- `tests/contract`
- `docs`
- `scripts`

禁止目录：

- `adapters/platforms`
- `deploy/environments/prod`
- `deploy/environments/prod/secrets`
- `secrets`
- `**/*.pem`
- `**/*secret*.json`
- `**/*token*.json`

## 权限、幂等、失败和审计

- Fixture 身份只用于 synthetic 测试，不能替代 IAM 或平台授权。
- 写入按派生幂等键保护；不同 payload 重用相同 key 必须失败且不覆盖对象。
- 跨租户引用必须被拒绝且不得改变对象或审计状态。
- 审计只保存引用、哈希、稳定身份和虚拟时间，禁止保存输入 bytes 和 seed 原文。

## Given–When–Then

成功场景：Given 相同 seed、起始时间和操作序列，When 创建两个 fixture，Then 两个
快照完全相同，且存储引用保持 `private://`。

重复场景：Given 已写入对象，When 以相同 key、bytes 和 content type 再次写入，Then
返回同一对象且审计事实仍只有一条。

非法输入场景：Given 空/超长 seed、naive datetime、负数或非有限时长、时钟回拨，
When 构建或推进 fixture，Then 返回 `FixtureValidationError` 且状态不变化。

权限/跨租户场景：Given 另一 `org_id`，When 读取本 fixture 的对象引用，Then 返回
`StorageAccessError` 且不泄漏 payload。

依赖缺失场景：Given 未提供真实账号、模型、平台或网络，When 执行全部用例，Then
仍可完成，并在快照中固定三个副作用标志为 false。

未知结果/隐私场景：Given seed 或 payload 含敏感样例文本，When 输出契约和审计，Then
文本不出现，只保留单向 hash 与私有引用。

## 补充场景

- 不同 seed 的身份、存储和审计状态互相隔离。
- 删除对象后快照不再列出对象，但保留 put/deleted 两条追加式审计事实。
- Schema 拒绝未知字段、非法 UUID、公开 URL、sequence=0 或任一副作用标志为 true。

## 验证

```text
python -m pytest tests/unit/test_found_009_testkit.py tests/integration/test_found_009_fixture_storage.py tests/contract/test_found_009_testkit_contract.py -q
python scripts/check_task_card_precision.py --task FOUND-009 --strict
python scripts/check_json_schemas.py
python scripts/check_migrations.py --strict --json
python scripts/check_foundation_contracts.py
```

Gate：`found_009_acceptance`

## 回滚

停止新测试对 `packages.testkit` 的导入，移除 testkit、Schema、测试和证据；将 Alembic
降级到 `20260918_found_008`。no-op revision 不删除任何表或业务数据，现有 FakeStorage
实现和历史对象契约保持不变。

## 外部依赖

- 无。
