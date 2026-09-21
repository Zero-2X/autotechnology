# FOUND-003B — 配置 S3 兼容对象存储和 Fake Storage 接口；保存对象哈希和私有访问策略。

状态：`done`  
阶段：1（模块化单体底座和可观测骨架）  
Owner：`team/foundation`  
优先级：`critical` / `P0`

## 目标

配置 S3 兼容对象存储和 Fake Storage 接口；保存对象哈希和私有访问策略。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `GOV-006`
- `FOUND-000`
- `FOUND-003A`

## 输入

- `docs/foundation/postgresql-foundation-baseline-v1.yaml`：FOUND-003A 的基础设施前置基线。
- `docs/governance/tech-stack-baseline-v1.yaml`：S3-compatible private object storage 约束。
- `STORAGE_ENDPOINT_URL`、`STORAGE_BUCKET` 等可选运行时配置；CI 允许缺失并使用 Fake Storage。

## 输出

- `infra/foundation/storage.py`：配置解析、健康快照、StoragePort 和 FakeStorage。
- `docs/foundation/s3-storage-baseline-v1.yaml`：无秘密对象存储基线。
- `packages/contracts/jsonschema/storage-config.schema.json`：对象存储配置契约。
- `docs/foundation/FOUND-003B-EVIDENCE.yaml`：验证和副作用证据。

## 契约与迁移

契约：

- `packages/contracts/jsonschema/foundation.schema.json`
- `packages/contracts/jsonschema/storage-config.schema.json`
- `packages/contracts/jsonschema/storage-object.schema.json`

迁移：

- `packages/db/migrations/versions/20260916_found_003b_storage_baseline.sql`
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

- `GOV-006、FOUND-000、FOUND-002 和 FOUND-003A 已完成`
- `EXT-STORAGE-001` 未提供真实凭证时，测试使用 Fake Storage

When：

- `执行 FOUND-003B 的配置、哈希、租户隔离、幂等、删除、契约和迁移测试`

Then：

- `S3-compatible endpoint/bucket 缺失或非法时确定性拒绝；配置快照不包含凭证`
- `Fake Storage 以 private://<bucket>/<namespace>/<org_id>/<object_key> 保存对象，记录 SHA-256 和 private policy`
- `跨租户读取/删除被拒绝；相同幂等键和 payload 可重放，不同 payload 冲突；删除后对象不可读`
- `不生成公开 URL、不调用 S3 SDK 或网络；迁移可重复执行且 baseline version/object metadata tenant key 唯一`

补充场景：

- Given 未设置存储环境变量，When 生成 storage health，Then 返回 `not_configured/probe=skipped`。
- Given endpoint 含用户名或密码，When 解析配置，Then 确定性拒绝且不回显秘密。
- Given 同一租户写入同一 key 的不同内容，When 再次写入，Then 返回不可变对象冲突。
- Given A 租户对象引用，When B 租户读取或删除，Then 返回租户命名空间拒绝。
- Given 相同 `Idempotency-Key` 和同一 payload，When 重放写入，Then 返回同一对象引用且不创建副本。
- Given Fake Storage 删除成功，When 再读取对象，Then 返回 not found；不得生成公开 URL。

## 验证

```text
python -m pytest tests/contract tests/integration --maxfail=1
```

Gate：`found_003b_acceptance`

## 外部依赖

- `EXT-STORAGE-001`

## 实现规格

1. `StorageSettings` 只解析 endpoint、bucket、namespace、region、TTL 和 private policy；endpoint 禁止携带用户名/密码，仓库不保存任何凭证。
2. `storage_health()` 只报告配置状态，不进行网络探测；真实 S3 SDK/HTTP 由后续 adapter 任务负责。
3. `FakeStorage` 实现最小 `StoragePort`：put/get/head/delete/list；对象引用必须是 `private://` 且包含 bucket、namespace 和 `org_id`。
4. 写入计算内容 SHA-256、大小、content type 和 metadata；同一对象 key 只允许相同内容重放，其他内容确定性冲突。
5. 幂等键按租户隔离并绑定 payload hash；相同键不同 payload 返回冲突；跨租户引用不得读取或删除。
6. 删除语义先删除 StoragePort 对象，再由后续任务删除业务元数据；当前迁移只保存配置/策略和对象元数据，不保存对象正文。
7. dev 使用无凭证 MinIO compose 形状；staging 只提供非秘密模板；Fake Storage 是 dev/test 的默认替代。
8. 审计修复依据 `docs/foundation/storage-key-policy-v1.md`：org/namespace 单段 NFC、128 UTF-8 字节上限；完整 namespace/org/key 最多 1024 字节。写入和引用读/删均拒绝控制/格式/代理字符、非 NFC、URI 分隔符、路径空段/点段、段首尾空白；不静默 strip/normalize/decode。历史有效引用和数据库迁移保持不变，非法历史键需显式迁移映射。

## 实施证据

- 配置实现：`infra/foundation/storage.py`。
- 配置基线：`docs/foundation/s3-storage-baseline-v1.yaml`。
- 配置/对象契约：`packages/contracts/jsonschema/storage-config.schema.json`、`packages/contracts/jsonschema/storage-object.schema.json`，并纳入 foundation contract union。
- 迁移：`packages/db/migrations/versions/20260916_found_003b_storage_baseline.sql`。
- dev/staging 模板：`deploy/environments/dev/storage.env.example`、`deploy/environments/staging/storage.env.example`。
- 本地 compose：`infra/compose/storage.dev.yaml`，凭证仅由运行时环境变量注入。
- 专项测试：`python -m pytest tests/contract/test_found_003b_storage.py -q`（9 passed）；integration fixture：`python -m pytest tests/integration/test_found_003b_fake_storage.py -q`（1 passed）；全量测试：`54 passed`。

## 回滚与运行说明

- 仅新增配置、Fake Port、基线和迁移；回滚使用受审查的反向变更，不删除 FOUND-003A 或现有契约。
- `EXT-STORAGE-001` 未满足时保持 Fake Storage；不得把 Fake Storage 结果标记为真实对象存储指标。
- 真实 S3 endpoint、密钥、签名 URL 和 SDK 适配不在本卡内。

## 开工前细化

本卡已完成从 `planned` 到 `in_progress` 再到 `done` 的状态闭环；真实 S3 连接、签名下载和平台对象传播由后续任务实现。
