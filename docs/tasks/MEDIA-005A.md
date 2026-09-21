# MEDIA-005A — 实现画面、音频、字幕和文件哈希 QA。

状态：`done`  
阶段：6（Media 和 Asset）  
Owner：`team/media`  
优先级：`high` / `P1`

## 目标

实现画面、音频、字幕和文件哈希 QA。

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

- `PROD-002`
- `MEDIA-004A`
- `MEDIA-004B`

## 输入

- `predecessor_artifacts`
- `tenant_context`
- `idempotency_key`

## 输出

- `MEDIA-005A.implementation`
- `MEDIA-005A.tests`
- `audit_evidence`

## 契约与迁移

契约：

- `packages/contracts/jsonschema/qa-report.schema.json`
- `packages/contracts/jsonschema/render-job.schema.json`
- `packages/contracts/jsonschema/media-output-spec-version.schema.json`
- `packages/contracts/jsonschema/media-subtitle-version.schema.json`

迁移：

- `packages/db/migrations/versions/20260920_media_005a.py`
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

## Given–When–Then

Given：

- `所有前置任务已完成`
- `TenantContext、trace_id 和 Idempotency-Key 可用`

When：

- `MediaAssetQAService.run_media_qa` 接收同租户的 RenderJob、产物事实、OutputSpec profile、可选 SubtitleVersion、TenantContext、trace_id 和幂等键

Then：

- `文件哈希检查先对 private:// 对象执行 head/get，确认 SHA-256、大小、content_type、租户和不可覆盖约束；无法确认的存储结果为 needs_review，哈希或权限不匹配为 failed`
- `画面检查确认容器、宽高/比例、帧率、视频编码、像素格式和时长符合锁定 profile；音频检查确认 codec、采样率、声道和音频存在性符合 profile`
- `字幕检查确认同租户、锁定版本和 profile track 引用，cue 按时间排序、无重叠、文本非空且落在视频时长内；缺少字幕版本或轨道为 failed`
- `MediaProbePort 为唯一媒体探针边界；FakeMediaProbe 可离线复现。探针或存储临时/未知结果不得自动通过，报告为 needs_review 且不保存媒体字节`
- `报告按 check/category、code、path、artifact_id 稳定排序，保存 input snapshot、artifact facts、规则版本和 finding；同租户同幂等键相同 payload 重放，payload 不同返回 IDEMPOTENCY_KEY_REUSED`
- `跨租户、expected_version 冲突、公开对象引用和敏感字段在写入前拒绝；每次成功或拒绝都写入 audit/outbox envelope，事件不含媒体字节`

## 实现规格

- `MediaAssetQAService`（别名 `MediaQAService`、`MediaRenderQAService`）只依赖 `StoragePort`、`MediaProbePort` 和可替换的内存 Store；不导入 ORM、FastAPI、供应商 SDK 或网络客户端。
- `run_media_qa` 支持传入 `media_render_job_id` 加 `render_service` 查询，或直接传入不可变 `render_job`/`artifacts` 投影；两种入口都必须验证 `org_id`、Job input_hash、profile_key 和 artifact natural key。
- `MediaProbePort.probe` 返回脱敏的容器、视频、音频、时长和字幕轨道事实。缺字段是未知结果；只允许 `FakeMediaProbe` 在测试中从固定映射返回事实。
- 迁移 `20260920_media_005a` 新增 `media_qa_reports`、`media_qa_findings`、`media_qa_commands` 三张追加式表，使用 RenderJob 的租户复合外键、报告/ finding 哈希约束、private/hash/敏感字段触发器和可逆 downgrade 回 `MEDIA-004B`。

## 补充场景

1. 同一 private object 已写入但 `head` 成功、`get` 暂时失败：报告为 `needs_review`，不重渲染、不写入媒体字节。
2. `head` 的 hash 与 artifact 不同，或 `get` 的 SHA-256 与 head 不同：报告为 `failed`，finding code 分别为 `FILE_HASH_MISMATCH` 或 `FILE_HEAD_GET_MISMATCH`。
3. profile 要求 `audio_codec=none` 但探针发现音频，或 profile 要求音频而探针返回 `none`：报告为 `failed`，使用 `AUDIO_PROFILE_MISMATCH`。
4. cue 的 `start_ms/end_ms` 越界、重叠、逆序、空文本或 track 引用不存在：报告为 `failed`，每个问题输出稳定的 `SUBTITLE_*` finding。
5. 探针抛出可重试异常或返回 `unknown`：报告为 `needs_review`，输出唯一 `MEDIA_PROBE_UNAVAILABLE` finding，不改变 RenderJob 状态。
6. 另一租户读取 Job、artifact 或 storage ref：返回 `TENANT_SCOPE_VIOLATION`，不创建报告、不触发 probe/get。

## 回滚

- downgrade 只移除 MEDIA-005A 的三张表及其索引/触发器，保留 MEDIA-004B 的 RenderJob、失败事实、重试计划和 private object；已生成的内存报告不影响渲染事实。
- 迁移升级不删除列或历史事实；数据库触发器拒绝 finding/report/command 的 update/delete，必须通过新报告追加修正。

## 验证

```text
python -m pytest tests/unit/media tests/integration --maxfail=1
```

Gate：`media_005a_acceptance`

## 外部依赖

- 无

## 开工前细化

本卡是 bootstrap 任务卡。任务从 `planned` 进入 `in_progress` 前，Owner 必须把通用输入、输出、契约文件和 Given–When–Then 细化为本任务的精确行为，并由一致性检查确认引用存在。
