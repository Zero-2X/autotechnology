# 贡献与交付规则

## 单任务工作流

每次变更必须绑定一个精确的 TASK-ID，先通过 FOUND-000 清点和任务卡门禁，再只修改 allowed_paths 中的文件。不要把相邻任务、真实平台连接或未登记的共享工具混入当前任务。

## 开始前检查

    python scripts/repo_inventory.py --check
    python scripts/check_plan_consistency.py --strict-contracts
    python scripts/check_task_card_registry_refs.py
    python scripts/check_task_card_precision.py --task <TASK-ID> --strict
    python scripts/check_openapi_contract.py

## 契约、迁移和测试

机器行为以 JSON Schema、事件 Schema、OpenAPI、任务注册表和版本化迁移为准。新增或变更字段必须有兼容策略和测试；in_progress 任务必须使用真实 migration revision，done 任务必须提供可重放验证证据。业务事实、AuditLog 和 Outbox 必须保持事务边界。

任务验证命令、失败场景、回滚方式和证据路径必须写入任务卡。不得用通过静态检查替代运行时或迁移测试。

## 安全与账号后置

不得读取、生成、提交或打印真实 Token、密码、Cookie、私钥或账号连接。无账号阶段仅允许 Fake Provider、Fake Adapter、Fake Inbox、Fake Geo、synthetic fixture、manual_export 和 simulation。未知外部结果转人工核查，不得自动重发。

## 代码边界

- modules/<module>/domain 只能包含纯业务规则。
- application 通过已登记 Port 调用 infrastructure；不得直接写 ORM。
- apps/api、apps/worker、apps/scheduler 只负责装配、租约和调用用例。
- adapters/platforms 属于后置真实平台任务，本阶段禁止触碰。
- 新共享代码必须有明确 Owner，禁止建立无边界的 modules/common 或 utils。

## 审查与回滚

变更必须满足 CODEOWNERS 审查和分支保护基线要求。失败时保留事实、证据和兼容字段，通过新版本修复；不得改写已接受的 ADR、迁移、治理策略或用户文件。

