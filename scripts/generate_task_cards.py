"""Create missing per-task specifications without overwriting human edits."""
from __future__ import annotations

from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs/task-registry.yaml"


def bullet(values: list[str]) -> str:
    return "\n".join(f"- `{value}`" for value in values) if values else "- 无"


def main() -> None:
    registry = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    created = 0
    for task in registry["tasks"]:
        target = ROOT / task["task_spec_ref"]
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        acceptance = task["acceptance"]
        target.write_text(
            f"""# {task['id']} — {task['title']}

状态：`{task['status']}`  
阶段：{task['phase']}（{task['phase_name']}）  
Owner：`{task['owner']}`  
优先级：`{task['priority']}` / `{task['tier']}`

## 目标

{task['title']}

## 明确不做

- 不修改任务注册表中的禁止目录。
- 不顺带实现相邻任务或未满足的外部依赖。
- 无真实账号时不读取或生成真实凭证，不调用真实平台副作用。

## 前置依赖

{bullet(task['depends_on'])}

## 输入

{bullet(task['inputs'])}

## 输出

{bullet(task['outputs'])}

## 契约与迁移

契约：

{bullet(task['contract_refs'])}

迁移计划：

{bullet(task['migration_refs'])}

## 目录边界

拥有目录：

{bullet(task['owned_paths'])}

允许目录：

{bullet(task['allowed_paths'])}

禁止目录：

{bullet(task['forbidden_paths'])}

## 权限、幂等、失败和审计

- 由 `TenantContext` 注入 `org_id` 和 actor；跨租户访问必须拒绝。
- 写命令使用 `Idempotency-Key` 和 payload hash；状态修改使用 `If-Match` 或 expected version。
- 确定性校验失败不重试；临时失败按任务卡与策略退避；未知外部结果转人工核查。
- 记录 `trace_id`、actor、输入/输出版本、Policy 快照、拒绝原因、耗时和成本。

## Given–When–Then

Given：

{bullet(acceptance['given'])}

When：

{bullet(acceptance['when'])}

Then：

{bullet(acceptance['then'])}

## 验证

```text
{task['test_command']}
```

Gate：`{task['gate']}`

## 外部依赖

{bullet(task['external_dependencies'])}

## 实现规格（开工前必填）

- 数据对象/表：列出字段、类型、必填、默认值、唯一键、外键和 `org_id` 约束。
- 状态机：列出允许转换、非法转换错误码、并发版本控制和恢复路径。
- 接口/命令：列出 HTTP 或 Worker-only 命令、请求/响应、事件名与具体 Schema 路径。
- 测试 fixture：给出成功、重复请求、权限/跨租户、外部依赖缺失、重试和未知结果样例。
- 回滚：说明迁移 expand/contract、feature flag、kill switch、重放或补偿命令。

## 开工前细化

本卡从 `planned` 进入 `in_progress` 前，Owner 必须完成“实现规格（开工前必填）”，将通用输入/输出和验收条件改成可执行的字段、命令、fixture 与断言；一致性检查必须确认契约、迁移和测试路径存在。
""",
            encoding="utf-8",
        )
        created += 1
    print(f"created {created} task cards; existing cards were not overwritten")


if __name__ == "__main__":
    main()
