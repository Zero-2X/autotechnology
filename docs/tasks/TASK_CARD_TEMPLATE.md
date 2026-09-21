# TASK-ID — 可执行任务卡模板

状态：`planned`  
阶段：`N`（阶段名称）  
Owner：`team/name`  
优先级：`critical|high|normal` / `P0|P1|P2`

## 目标与边界

用一句话说明本卡交付的唯一可验收行为。列出明确不做事项，避免把相邻能力带入本卡。

## 前置依赖与外部依赖

- 前置任务：精确 `TASK-ID`，不得使用通配符或复合编号。
- 外部依赖：`EXT-*`；未满足时必须说明可用的 fake/simulation 替代路径。

## 输入

列出每个输入的来源、类型、必填性和示例：

| 名称 | 来源 | 类型/约束 | 必填 | 示例 |
|---|---|---|---|---|
| tenant_context | middleware | `{org_id, actor_id, roles}` | 是 | synthetic org |

## 输出与副作用

列出返回对象、持久化记录、事件和审计证据；标注是否幂等、是否创建新版本。

## 数据模型与不变量

列出表/对象的字段（类型、必填、默认值、唯一键、外键）以及状态机允许转换。历史版本不可覆盖；所有租户实体必须有 `org_id`。

## 契约与接口

- JSON Schema：具体对象级文件路径。
- OpenAPI：方法、路径、请求/响应状态码和错误码。
- 事件：事件名、版本、发布时机、`schema_ref`。

## 目录边界

填写 `owned_paths`、`allowed_paths`、`exclusive_paths`、`forbidden_paths`。跨模块改动必须拆为新任务或声明依赖。

## Given–When–Then 验收

至少覆盖成功、重复请求、非法状态/权限、跨租户、外部依赖缺失和重试/未知结果六类场景，并给出可执行 fixture 与断言。

## 验证命令与证据

写出精确命令（可复制执行）、覆盖率/契约校验要求、生成的审计日志或快照路径。

## 回滚与运行说明

说明数据库 expand/contract 顺序、feature flag、kill switch、重放/补偿命令和向后兼容策略。
