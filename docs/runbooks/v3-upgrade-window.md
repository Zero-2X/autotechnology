# V3 依赖升级窗口

V3 的 Python 兼容线固定为 3.12，provider profile 锁定为 LangGraph 0.6.7 和
LangChain Core 0.3.72（见 `requirements-v3.lock`）。代码通过本仓库的 Port 运行，
CI 使用 Fake 实现，不需要真实供应商凭证。升级按 30 天窗口评审，必须同时通过
Graph State Schema、Prompt/Parser、模型调用、Checkpoint、重放和未知结果测试。

升级期间保留旧 `graph_key + workflow_version`，已有运行继续使用原版本；新版本只在
Registry 注册后接收新运行。回滚只停止新版本注册，不删除旧 Checkpoint 或业务事实。
