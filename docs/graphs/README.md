# Graph 拓扑与状态

V3 图只保存运行 ID、对象引用、版本、路由、错误和恢复信息。完整正文、Token、PII、
媒体二进制和业务事实由领域模块或私有对象存储保存；Checkpoint 只用于恢复。

当前可执行的 account-free 拓扑是：

`TopicSignal → TopicBrief → Source/Rights/Knowledge/Canonical → Variant/QA/GEO → Approval → Manual Export → Simulation/Fake Adapter`

实现入口是 `orchestration.content.build_content_graph`。每个节点只接收注入的
Application Port；真实账号分布图暂时只保留 `draft_only` 门禁，受 `EXT-ACCOUNT-001` 阻塞。

版本和回放规则见 `docs/adr/ADR-001-langchain-langgraph-architecture.md` 与
`docs/adr/ADR-002-live-feedback-observation-port.md`。Graph 重放不会重复外部副作用，
未知平台结果必须进入人工核查。
