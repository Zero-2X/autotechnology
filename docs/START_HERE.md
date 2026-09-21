# 开发清单使用入口

开始构建前先阅读 [`BUILD_MANIFEST.md`](BUILD_MANIFEST.md)，然后复制 [`CODEX_START_PROMPT.md`](CODEX_START_PROMPT.md) 中的 Prompt 给 Codex。

本项目现在有两个互补的执行基线：

[`AI跨境技术内容自动化工作流开发清单_审计与优化版.md`](../AI跨境技术内容自动化工作流开发清单_审计与优化版.md)

它是 **V2.4 领域、治理和账号后置基线**。

[`AI跨境技术内容自动化工作流开发清单_LangGraph_V3.md`](../AI跨境技术内容自动化工作流开发清单_LangGraph_V3.md)

它是 **V3 编排层和 LangChain 组件基线**。实施 Graph/LC 任务时，以 V3 为任务说明，以 V2.4 为业务契约和安全规则。

V2.4 描述领域架构、阶段、状态机、账号后置边界和验收标准；V3 增加 Graph State、Node、Router、interrupt、checkpoint、重放和 LangChain 组件规则。原始清单与 V2.1 备份只用于对照，不作为 Codex 的执行输入。

## 先看什么

1. 读主清单第 1–3 节：确认审计结论、账号后置方案、模块目录和技术基线。
2. 执行 `python scripts/repo_inventory.py --check`，确认仓库现状没有被覆盖。
3. 读 [`docs/task-registry.yaml`](task-registry.yaml)，按精确 `TASK-ID` 选择任务。
4. 读 [`docs/tasks/<TASK-ID>.md`](tasks/TASK_CARD_TEMPLATE.md) 对应任务卡。
5. 运行契约、引用、OpenAPI 和任务卡门禁，再开始编码。

LangGraph 任务使用独立注册表 [`docs/task-registry-langgraph-v3.yaml`](task-registry-langgraph-v3.yaml) 和对应任务卡；这些任务不得覆盖 V2.4 的同名业务任务。

## 当前分期

| 分期 | 是否需要真实账号 | 交付内容 |
|---|---|---|
| M1-Core | 否 | 底座、Topic、Provenance/Knowledge/Canonical、Variant、QA、Policy、Approval、Manual Export/Fake、核心 Observation |
| M1-Plus | 否 | 第一方知识站、GEO_CONTENT/GEO_REGION、Media/Asset、离线评测，可延期 |
| M2 | 是 | 一个真实账号、一个官方平台、OAuth/Vault、健康检查、草稿或受控发布 |
| M3 | 是 | 更多平台、账号、市场、客服、实验和规模化基础设施 |

无账号阶段只能使用 `manual_export`、`simulation`、Fake Provider、Fake Adapter、Fake Geo、Fake Inbox 和 synthetic fixture。不得保存真实 Token、调用真实平台或把模拟结果标成真实指标。

## Codex 单任务门禁

```text
只完成 TASK-ID：<TASK-ID>。
先读取任务卡、task-registry、相关 ADR、packages/contracts 和当前工作树。
只修改任务卡允许目录；不跨模块重构，不调用真实平台。
先更新/确认 Schema、迁移和测试，再实现 domain、application、infrastructure 和入口。
完成前运行：
  python scripts/check_plan_consistency.py --json
  python scripts/check_task_card_registry_refs.py
  python scripts/check_task_card_precision.py --task <TASK-ID> --strict
  python scripts/check_openapi_contract.py
最后报告修改文件、测试结果、事件/审计证据、回滚方式和未完成项。

Graph/LC 任务额外要求：Node 只能调用 Application Use Case/Port；Graph State 不得保存 Token、完整正文、PII 或二进制；checkpoint 不得替代业务事实；重放不得重复产生外部副作用。
```

## 机器契约入口

- 对象 Schema：`packages/contracts/jsonschema/`
- 事件 Schema：`packages/contracts/events/`
- HTTP 契约：`packages/contracts/openapi/openapi.yaml`
- 任务注册表：`docs/task-registry.yaml`
- 状态索引：`docs/contracts/state-registry.yaml`
- 事件索引：`docs/contracts/event-registry.yaml`
- 迁移生命周期：`docs/contracts/migration-manifest.yaml`
- Codex 执行协议：[`docs/CODEX_EXECUTION_PROTOCOL.md`](CODEX_EXECUTION_PROTOCOL.md)
- 准备度审计：[`docs/audits/v2.4-readiness-audit.md`](audits/v2.4-readiness-audit.md)

最新状态见 `docs/foundation/development-progress-2026-09-21.md`。V2.4 注册表当前有
137 项 done、20 项 planned，已有业务代码及 125 个迁移 revision；真实平台连接尚未验收。
V3 的 38 项 Graph/LC 任务中 34 项已完成 account-free 验收，4 项因 EXT-ACCOUNT-001
缺少真实账号与平台证据而 blocked。P0 任务卡继续按任务细化，通过自己的门禁后才可推进状态。
