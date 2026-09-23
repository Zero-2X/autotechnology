# AI 跨境技术内容自动化工作流

## 当前状态

历史目录基线分类为 `planning-and-contract-baseline`；当前已存在领域实现和迁移。
截至 2026-09-21，V2.4 注册表有 137 项 done、20 项 planned；V3 编排注册表有 34 项
done、4 项 blocked。当前总计 171 done、20 planned、4 blocked；blocked 项均依赖
EXT-ACCOUNT-001 的真实主体、授权和平台 Sandbox 证据。
已实现内容链、无账号交付、Media、Analytics、核心 Feedback 和 Fake/manual Support。
Account/OAuth、MFA、平台 Fake 与 Live Feedback 有本地准备性实现，尚未通过真实验收。
V3 的 account-free 编排、状态、LangChain 端口和内容图已完成本地验收，真实 LangGraph
组合入口为 `orchestration/langgraph_adapter.py`；后续只推进外部账号门禁及部署环境验证。

当前边界：小红书首个账号已使用本机独立浏览器会话接入，支持打开账号、排队准备图文草稿和主动确认后尝试提交发布；新版运行器会保护未保存草稿，发布结果仍需平台回查。2026-09-23 的只读消息区检查被平台重定向到登录页，当前会话需账号持有人重新扫码；登录重定向现在会立即反映到后台，扫码成功后也会自动恢复连接状态。评论/私信自动读取与回复尚未完成真实验收。没有真实 S3 或平台 API 发布；PostgreSQL 专有的
双 Worker 并发、隔离级别、连接中断和锁超时仍需在独立的真实 PostgreSQL 环境中
完成上线前验证。仓库内验证不得把 SQLite 结果描述为生产并发证据。

最新业务运行说明见 `docs/网页管理后台测试说明.md` 和 `docs/真实账号自动化运营操作手册.md`；历史 Foundation 审计见
`docs/audits/foundation-overall-audit-2026-09-16.md`。机器状态分别以两份任务注册表为准。

## 机器真源

- `docs/task-registry.yaml`：V2.4 任务唯一机器注册表。
- `docs/task-registry-langgraph-v3.yaml`：V3 编排增量任务机器注册表。
- `packages/contracts/`：JSON Schema、事件和 OpenAPI 契约。
- `packages/db/migrations/versions/`：已实现的版本化迁移；`planned/` 仅为计划引用。
- `docs/repo-inventory.md`：FOUND-000 文件清点与兼容/禁止覆盖边界。
- `docs/governance/branch-protection-baseline-v1.yaml`：分支保护基线。

## 目录原则

`apps/` 是运行入口，`modules/` 是逻辑边界，`adapters/` 只实现 Port，`packages/`
提供有明确归属的共享契约或工具。领域规则不得依赖 FastAPI、ORM、供应商 SDK 或
其他模块的基础设施；前端不得直接连接数据库。

## 本地验证

```text
python scripts/repo_inventory.py --check
python scripts/check_plan_consistency.py --strict-contracts
python scripts/check_task_card_registry_refs.py
python scripts/check_openapi_contract.py
python scripts/check_foundation_contracts.py
```

## 本地运营后台

```powershell
.\scripts\start-workflow.ps1
```

默认打开 `http://127.0.0.1:8766/`，同时启动 API。内容工作室可以在模型服务不可用时生成本地标题、正文、话题标签和封面；客服收件箱可以生成低风险回复草稿，高风险消息自动转人工。小红书登录会话使用独立本机浏览器目录保存，发布默认停在最终按钮前，也支持主动确认后尝试提交发布。

后台数据会同步写入本机 `.local/workflow-state.json`。发布中心在人工确认平台发布后可以登记对象 ID 或链接；客服收件箱支持导入复制的真实评论/私信、生成草稿、复制回复并登记已发送。

## 任务流程

一次只实现一个精确 TASK-ID。开始前读取任务卡、注册表、ADR、契约和当前清点；
完成后更新证据、迁移清单、契约清单和测试结果。无真实账号阶段仅允许 synthetic、
manual_export 和 simulation，不读取、生成或保存真实 Token。

## 贡献边界

提交前阅读 `CONTRIBUTING.md` 和 `CODEOWNERS`。目录移动、模块重命名、跨模块依赖
或技术栈扩展必须先更新 ADR/任务卡，并保持已有契约和迁移历史可追溯。
