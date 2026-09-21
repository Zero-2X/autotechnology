# DIST-003B — 为 ExportPackage 实现私有对象存储、短期签名下载 URL、包过期/撤回、下载审计和版本哈希；不能默认生成公开链接。

状态：`done`  
阶段：7（Distribution 抽象、Manual Export 和 Fake Adapter）  
Owner：`team/distribution`  
优先级：`critical` / `P0`

## 目标

为 ExportPackage 实现私有对象存储、短期签名下载 URL、包过期/撤回、下载审计和版本哈希；不能默认生成公开链接。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `FOUND-003B`
- `POLICY-001`
- `DIST-003A`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `DIST-003B.implementation`
- `DIST-003B.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/export-package.schema.json`
- `packages/contracts/events/event-envelope.schema.json`

迁移计划：

- `packages/db/migrations/versions/20260919_dist_003b.py`

## 实现规格

- `ExportPackageStorage` 通过可替换 `PackageStoragePort` 登记包和文件，校验 ExportPackage、租户私有引用、文件 SHA-256 和不可覆盖的包版本。
- `issue_download_url` 只生成 `private://download/{org}/{package_id}` 的短期 HMAC 签名 URL；TTL 受 3600 秒上限和包自身 expires_at 双重约束，重复幂等键不重复下载计数。
- `expire_package`、`revoke_package` 使用 package hash 作为 If-Match 版本；过期/撤回后下载 URL 和文件读取均阻断，撤回保留事实与审计。
- `distribution` package registered/downloaded/expired/revoked 事件均符合 EventEnvelope；默认无公开链接、无凭证读取、无网络调用。
## 目录边界

拥有目录：

- `modules/distribution`

允许目录：

- `modules/distribution`
- `adapters/contract`
- `adapters/manual`
- `adapters/fake`
- `tests/replay`
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

- `注册 ManualAdapter 输出的 ExportPackage 与文件，并请求下载、过期或撤回`

Then：

- `包与文件只在 tenant private namespace 存储，文件哈希可复核`
- `签名下载 URL 为短期 private:// 引用；过期、撤回、错误 If-Match、跨租户和篡改签名被拒绝`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/distribution tests/integration --maxfail=1
```

Gate：`dist_003b_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
