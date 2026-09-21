# Codex 开始构建 Prompt

复制下面整段内容发送给 Codex：

```text
你现在负责构建“AI 跨境技术内容自动化工作流”。请严格按仓库内的规划文件执行，不要自行扩大范围。

先读取：
1. AI跨境技术内容自动化工作流开发清单_审计与优化版.md（V2.4 领域/治理基线）
2. AI跨境技术内容自动化工作流开发清单_LangGraph_V3.md（V3 编排基线）
3. docs/BUILD_MANIFEST.md（总顺序）
4. docs/CODEX_EXECUTION_PROTOCOL.md（执行门禁）
5. docs/adr/ADR-001-langchain-langgraph-architecture.md（架构边界）
6. docs/task-registry.yaml 和 docs/task-registry-langgraph-v3.yaml
7. docs/tasks/<当前任务 ID>.md、相关 JSON Schema、事件 Schema、OpenAPI 和迁移索引

本轮只完成一个任务：FOUND-000。
如果 FOUND-000 已经是 done，则按 BUILD_MANIFEST 的顺序选择第一个依赖全部 done 且任务卡精细化检查通过的任务，并先报告你选择的 TASK-ID，再开始实现。

执行规则：
- 先读取当前工作树和任务卡，再确认依赖、契约、迁移和允许目录。
- 先更新/确认 Schema、事件、OpenAPI、迁移和测试，再实现 domain/application，再接入 infrastructure 和 API/Worker/Graph Node。
- 每次只修改当前任务的 allowed_paths，优先 owned_paths，不跨任务重构。
- 所有写命令使用 org_id、trace_id、Idempotency-Key 和 expected_version/If-Match；业务事实与 AuditLog/Outbox 必须满足事务一致性。
- Domain 不依赖 FastAPI、ORM、LangChain 或 LangGraph。
- Graph Node 只能调用 Application Use Case/Port，不能直接写数据库或调用平台 SDK；Router/Reducer 必须无副作用。
- Graph State 只能保存运行 ID、版本、对象引用、路由、错误和恢复信息；禁止 Token、完整正文、PII 和二进制。
- LLM/Agent 只能输出结构化候选、草稿、报告或人工任务，不能直接批准或发布。
- 没有真实账号时只能使用 manual_export、simulation、Fake Provider、Fake Adapter 和 synthetic fixture；不得读取、生成、保存真实凭证或调用真实平台。
- interrupt 恢复必须使用相同 run_id/thread_id，并重新检查最新版本、Rights、Region、Policy 和 Kill Switch。
- checkpoint 只用于恢复，不得替代 PostgreSQL 业务事实、审批、AuditLog 或 Outbox。
- unknown 外部结果必须进入人工核查，禁止自动重发。

完成前运行与当前任务相关的全部检查，至少包括：
python scripts/repo_inventory.py --check
python scripts/check_plan_consistency.py --strict-contracts
python scripts/check_task_card_registry_refs.py
python scripts/check_langgraph_task_registry.py
python scripts/check_task_card_precision.py --task <TASK-ID> --strict
python scripts/check_openapi_contract.py
python -m pytest <任务卡指定测试命令>

只有在实现、测试、审计、Outbox、迁移和回滚证据齐全后，才把任务标记为 done。最后输出：修改文件、契约和迁移、测试结果、trace/audit/outbox 证据、回滚方法、未完成项和风险。
```

## 下一步任务

第一轮使用 `FOUND-000`。它完成后，再按 `docs/BUILD_MANIFEST.md` 和两个注册表的依赖顺序推进；不要直接要求 Codex 一次实现全部 38 个 Graph/LC 任务或全部 157 个 V2.4 任务。

