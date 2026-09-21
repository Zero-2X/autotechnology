# qa

## 职责

Fact, code, similarity, accessibility and deterministic quality gates.

## 固定布局

- domain/：实体、值对象、状态机和纯规则。
- application/：公开用例、命令、事务边界和权限检查。
- ports/：外部接口抽象和 DTO。
- infrastructure/：本地实现、仓储和事件发布器。
- projections/：可重建的只读投影。

## 表

表由后续任务卡和版本化迁移定义；本骨架不创建业务表。

## 公开接口

公开用例和 Port 由后续任务卡登记。

## 事件

事件类型和 Schema 由 `packages/contracts/events/` 登记。

## 权限

所有租户业务调用必须经过 TenantContext 和授权检查。

## 公开边界

接口、事件和权限由对应任务卡与 JSON Schema 登记；本目录不得直接依赖其他模块的 infrastructure、FastAPI、ORM 或供应商 SDK。

## 禁止事项

不得保存 Token、完整 PII 或二进制；无账号阶段不得调用真实平台。
