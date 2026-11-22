---
name: coding-orchestrator
description: Use when the user requests coding-orchestrator, needs to choose or combine engineering methods, encounters conflicting coding workflows, or wants to add a personal or third-party engineering convention.
---

# Coding Orchestrator（工程方法编排）

选择当前需要的工程方法，处理实际冲突。可独立安装；专项规范和完整工作流均为可选。
方法与验证已经清楚的局部任务直接执行，不为使用编排器先跑一套流程。

## 开始与按需读取

先核对用户要求、项目已有规范和当前任务事实。已有明确做法时沿用；不要因安装了多个包就全部启用。

| 当前需要 | 读取与动作 |
| --- | --- |
| 方法未定、缺少专项能力，或约定出现冲突 | [选择与冲突处理](references/selection-and-conflicts.md) |
| 接入第三方或个人规范，或更新其适用范围 | [规范接入记录](references/convention-profile.md)；复用项目已有记录位置 |
| 核对已列举规范的官方来源与接入边界 | [上游规范](references/upstream-conventions.md)；只读选中的来源 |
| 替换旧的重复路由或迁移安装 | [迁移说明](references/migration.md) |

只加载当前动作所需的内容。设计、调试、实现、测试和审查可以随进展切换，不设置永久任务模式。
没有其它方法包时，仍可按项目规范定位问题、完成必要改动并运行相称的检查。

## 执行边界

- 用户要求和项目明确约定决定选用的方法；本 skill 不改变上层指令、权限或已启用插件钩子的效力。
- 先核对所选能力的实际安装入口和版本，再按其适用要求使用；缺少方法包时采用内置做法，实际工具或权限缺口仍需如实报告。
- 规范、设计与执行计划按职责保留原生产物；同一用途只认项目选定的权威位置，通过引用接续。
- 无法同时满足的明确要求说明具体冲突和影响，继续不依赖该决定的工作，由有权决定的一方裁定。
- 方法选择清楚时无需额外登记。需要解释取舍或交接时，简短写回已有任务记录。

## 可选集成（非依赖）

| 能力 | 示例（如已安装） | 未安装时 |
| --- | --- | --- |
| 通用编码约束 | `karpathy-guidelines`，按[来源与版本](references/upstream-conventions.md)选用 | 沿用项目规范，明确目标与验证方式 |
| 结构分析与模式选择 | `design-patterns` | 从直接方案出发，只解决实际结构问题 |
| 测试、调试与审查方法 | `test-driven-development`、`systematic-debugging`、代码审查专项 | 使用[最小方法](references/selection-and-conflicts.md) |
| 完整工程工作流 | Superpowers、gstack、OpenSpec、spec-kit | 使用项目现有流程，不要求安装整套框架 |
| 项目记录、工作区或外部进程协作 | `long-running-project-harness`、`git-workspace-governance`、`invoke-coding-agents` | 使用项目已有记录与执行入口 |

结果报告实际改动、验证和剩余问题；区分方法被选中、工具已执行和任务已验收。
