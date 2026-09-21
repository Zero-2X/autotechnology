# Foundation 总体架构、代码、逻辑与契约审计

初审日期：2026-09-16  
最新复核：2026-09-18  
范围：GOV-001～GOV-006、FOUND-000～FOUND-010，以及继续开发前必须关闭的基础运行风险。

## 当前结论

Foundation 的本地与 synthetic 基线已形成闭环。数据库 bootstrap、存储键策略、
Worker 组合执行、统一失败事务、递归事件兼容和 FOUND-008 控制面均已补齐并有回归
测试。FOUND-009 已补齐确定性时钟、身份、存储和审计 fixture。仓库可以继续按清单
继续进入机器注册表中更早的未完成项 GOV-007。

仍有一项外部上线前门禁：PostgreSQL 专有并发语义尚未在真实隔离数据库中验证。
该项需要可销毁的 PostgreSQL 服务，不能用 SQLite 测试替代，也不阻塞不依赖真实
数据库服务的后续本地开发。

## 已关闭问题

| 级别 | 问题 | 关闭证据 |
|---|---|---|
| P0 | legacy SQL 与 Alembic 缺少统一空库入口 | `scripts/bootstrap_foundation_db.py` 按固定 legacy 清单后接 Alembic head，并覆盖重复执行/升级测试 |
| P0 | Worker 只有 dry-run，Stores 未形成执行闭环 | `apps/worker/runtime.py` 组合 claim/start/handler/heartbeat/complete/failure/outbox；专项 24 passed |
| P1 | 状态失败与失败事实存在双入口 | `TaskFailureFacade` 成为 Worker 唯一失败入口；兼容 `TaskClaimStore.fail()` 委托同一事务 |
| P1 | 递归 payload 兼容、外围信封和版本选择不足 | 兼容检查器递归校验约束并保守拒绝不可证明组合；离线版本注册表已覆盖 |
| P2 | Fake Storage key 规范不够严格 | NFC、控制/格式/代理字符、URI 分隔符、段和 UTF-8 长度规则已冻结并统一到所有操作 |
| P0 | Feature Flag、交付模式和全局停止控制缺失 | FOUND-008 已实现租户 Flag、默认安全交付模式、显式全局授权、拒绝审计和事务 Outbox |
| P0 | 测试缺少统一可复现时钟、身份、存储和审计 fixture | FOUND-009 已提供 seed 派生身份、FakeClock、隔离 FakeStorage 和脱敏审计快照 |

## Worker 运行边界

Worker 运行时按租户和队列有界领取任务，调用注册的应用处理器。长任务通过
`WorkerExecutionContext.checkpoint()` 协作检测停机和超时并续租。处理器成功后按
lease token 与 aggregate version 完成；确定性、临时和未知失败都通过
`TaskFailureFacade` 在单事务内追加失败事实、更新任务状态并清理租约。

未知异常不持久化异常原文，只保存稳定错误码和异常类型；未知结果和执行超时转人工
复核，防止在外部结果不明时自动重试。停机时当前处理完成，已领取但未启动的任务记为
临时失败并按策略退避。容量为零时不领取任务。单个运行时同步执行一个批次，横向并发
由多个 Worker 进程提供。

详细证据见 `docs/foundation/WORKER-COMPOSITION-AUDIT-2026-09-18.yaml`。

## 契约与数据边界

- TaskJob、TaskFailure、HumanTask、Outbox、控制面状态和审计事实都按 `org_id` 隔离。
- 写命令使用幂等键和版本条件；未知外部结果不自动制造第二次副作用。
- OpenAPI、事件和对象 Schema 使用离线 Draft 2020-12 校验，不允许校验过程访问网络。
- 事件兼容基线保留历史快照；检查失败时不得通过重生成基线掩盖差异。
- 交付模式默认仅启用 `manual_export` 和 `simulation`；真实交付仍需后续 IAM、Policy、
  Rights、Region、Approval、账号授权和平台适配任务共同放行。

## 仍需上线前完成

在真实 PostgreSQL 环境运行双 Worker 并发 claim、事务隔离、租约抢占、死锁/锁超时、
连接中断和 Outbox 重复投递测试，并保存数据库版本、隔离级别和执行日志。通过前不得
声称 production-ready concurrency。

真实 S3、平台 API、凭据管理、生产监控与部署由后续对应任务实现，不属于当前已完成
范围。

## 复核证据

- Worker 相关专项：24 passed。
- FOUND-008 专项：13 passed。
- 最新完整测试：448 passed。
- 当前迁移 head：`20260918_found_010`，单 head；FOUND-009/010 revision 为无 DDL 的版本边界。
- 事件兼容：162 个事件，0 errors，0 warnings。
- 任务注册表：157 项，FOUND-010 完成后 27 项 done。

最终完整门禁命令：

```text
python scripts/check_foundation_contracts.py
```

仓库不是 Git worktree，因此审计依据为机器注册表、文件清点、迁移图、契约门禁、
专项测试与完整测试，而不是 Git diff 或提交历史。
