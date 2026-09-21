# V3 编排本地运行手册

本地/CI 使用 `FakeModel`、`InMemoryRetriever`、`InMemoryCheckpointer` 和
`adapters.fake.FakeOfficialServer`。没有真实账号时只运行 manual export 或 simulation。

1. 由组合入口注册 `GraphDefinition` 和版本策略。
2. 用 `GraphRunner.run` 提供同租户 `org_id`、`actor_id`、`trace_id`、`Idempotency-Key`，
   `input_refs` 只能是私有引用。
3. `waiting` 运行通过 `HumanTaskService` 领取/解决后，用同一 run 的 checkpoint 调用
   `GraphRunner.resume`；恢复时重新读取当前版本、Policy 和 Kill Switch。
4. `replay` 只读取 checkpoint 和 PublicationIntent，`ReplayGuard` 复用 provider 幂等键，
   不重新产生外部对象。
5. 检查 `TraceLedger.events`、`GraphRunner.audit` 和 `outbox`，日志中不得出现 Prompt、
   Token、完整正文或供应商原始响应。

生产 Checkpointer 和真实平台接入必须另行通过 V3 Go/No-Go 及 V2.4 外部依赖证据。
