# MEDIA-001 — 实现 30/60/90 秒脚本模板、人工编辑和 Claim 引用。

状态：`done`  
阶段：6（Media 和 Asset）  
Owner：`team/media`  
优先级：`high` / `P1`

## 目标

实现 30/60/90 秒脚本模板、人工编辑和 Claim 引用。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `CANON-006`
- `PROD-002`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `MEDIA-001.implementation`
- `MEDIA-001.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/asset-version.schema.json`
- `packages/contracts/jsonschema/media-script.schema.json`：同一 VariantVersion 与目标时长下的稳定脚本根和当前版本指针。
- `packages/contracts/jsonschema/media-script-version.schema.json`：不可变的 30/60/90 秒脚本版本、分段时间、人工编辑来源和 Claim 引用。脚本文本不写入 `asset-version`；后续 MEDIA 任务从已复核脚本创建 AssetVersion。

迁移计划：

- `packages/db/migrations/versions/20260920_media_001.py`
## 目录边界

拥有目录：

- `modules/media`

允许目录：

- `modules/media`
- `apps/worker`
- `adapters/fake`
- `tests/accessibility`
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

## 实现规格

### 已批准 Variant 与 Claim 门禁

`MediaScriptService.create_script` 只读取调用方明确指定的同租户 `VariantVersion`；不得按 ContentVariant 当前指针替换。Variant 必须为 `approved`、带有效 `policy_snapshot_id` 和 SHA-256 `snapshot_hash`，body block id 唯一且文本非空。脚本只使用 Variant 的 locale/market/region 和可见 block 文本，不调用模型、网络、渲染器或平台。

每个用于 hook/body 的 block 必须通过 Variant `source_map`、block `claim_refs` 或显式 `claim_ids` 绑定至少一个 Claim。Claim 必须同租户、`status=verified`、`freshness_status=fresh`、位于有效期内且未到复核截止时间；非空 applicable locale/region/version 必须覆盖当前 Variant。缺 Claim、伪造 ID、跨租户、draft/stale/withdrawn 或过期 Claim 均确定性拒绝，不生成脚本事实。

### 30/60/90 秒模板

时长只允许 `30|60|90`。`media-script-v1` 固定生成 `hook → body → cta` 三段，时间线连续覆盖 `0..duration_seconds*1000` 且不重叠：30 秒为 `0–4000/4000–26000/26000–30000`，60 秒为 `0–7000/7000–53000/53000–60000`，90 秒为 `0–10000/10000–80000/80000–90000`。

英文及空格分词 locale 的上限分别为 75/150/225 个口播单元，CJK locale 使用非空白字符单元与固定 CTA。hook 取首个 Claim block 的首句，body 按 Variant block 顺序组合 Claim block，CTA 是不含事实断言的固定文案。生成器只能截断源文本以满足预算，不补写新事实；hook/body 保留所用 block id 与 Claim id，CTA 的 Claim 引用为空。输出 `word_count`、确定性预计时长、模板版本和源 Variant/Claim 快照哈希。

### 人工编辑与不可变版本

`edit_script` 仅允许人工按 segment sequence 修改文本；segment 数量、kind、时间线、source block 和 Claim 引用不可变，防止编辑绕过溯源。编辑后仍需满足对应时长口播预算，空文本、无变化、超预算或引用漂移拒绝。调用必须带非空 edit reason 与 `expected_version_no`；成功创建 `status=edited` 的新不可变版本，旧版本保持不变，root 当前指针以乐观并发更新。

同租户同幂等键与 payload hash 重放首次结果；不同 payload 返回 `IDEMPOTENCY_KEY_REUSED`。actor、trace 和隐式时钟不改变业务 snapshot hash。创建和编辑审计只保存输入/输出哈希、版本和稳定错误码，不保存凭证或模型原始输出。

### 持久化

`media_scripts` 保存稳定身份和 current version 指针，`media_script_versions` 追加保存脚本版本，`media_script_claim_refs` 用租户复合外键绑定已验证 Claim，`media_script_commands` 保存幂等命令投影。Version、Claim ref 和 command 禁止 update/delete/replace；root 的 org、Variant、时长和身份不可原地修改。降级只删除本任务表、索引与触发器，保留 Variant、Claim、Canonical 和 SITE 事实。

## Given–When–Then

Given：

- `所有前置任务已完成`
- `TenantContext、trace_id 和 Idempotency-Key 可用`

When：

- `执行 MEDIA-001 的公开用例或内部命令`

Then：

- `实现 30/60/90 秒脚本模板、人工编辑和 Claim 引用。`
- `输出契约、审计事件和指定测试结果可复现`

## 验证

```text
python -m pytest tests/unit/media tests/integration/test_media_001.py tests/integration/test_media_001_migration.py tests/contract/test_media_001_contract.py -q
```

Gate：`media_001_acceptance`

## 完成记录

- 实现：`modules/media/script_service.py`、`modules/media/__init__.py`。
- 迁移：`packages/db/migrations/versions/20260920_media_001.py`。
- 契约：`media-script.schema.json`、`media-script-version.schema.json`。
- 测试：11 项 MEDIA 专项测试通过；迁移在完整 Alembic 链上升级、约束验证和降级通过。
- 证据：`docs/foundation/MEDIA-001-EVIDENCE.yaml`。

## 外部依赖

- 无

## 补充场景

- 相同 Variant、Claim 快照、时长与模板输入在不同 actor/trace/时钟下得到相同脚本 snapshot hash。
- 输入 block、source map 或 Claim 数组重新排序后，Variant block 顺序仍决定脚本文本，Claim 引用按 UUID 排序去重。
- 同一 Variant 可各有一个 30/60/90 秒脚本根；同一时长重复创建不得生成第二个 root。
- 编辑只改变指定 segment 文本；旧版本、其他 segment、Claim 引用和时间线保持逐字段一致。
- Claim 在创建后被撤回不改写历史 ScriptVersion；新的创建/编辑读取当前 Claim 快照并拒绝失效引用，撤回传播由后续 MEDIA-006 处理。
- 任何外部 Port 异常均失败闭合，只记录稳定错误码和哈希，不保存异常中的 secret/token。

## 回滚

- 停止新脚本创建与编辑，导出 Script/ScriptVersion、Claim ref、snapshot hash 与审计引用。
- 降级到 `20260920_site_004`，仅删除 MEDIA-001 的脚本根、不可变版本、Claim 引用、命令、索引和触发器；不删除 Variant、Claim、Canonical、Region 或 Site 历史事实。
