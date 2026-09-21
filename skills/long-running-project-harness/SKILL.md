---
name: long-running-project-harness
description: Use this skill when the user explicitly wants a long-running project harness, multi-session project memory, clean-room rebuild discipline, project-level planning assets, or coordinated handoff between agents/sessions. It defines a durable project protocol with scope, architecture, MVP checklist, handoff/progress, and runbook files while avoiding accidental copying of external source, API shapes, names, prompts, docs, UI text, tests, or data structures. Do not trigger for ordinary multi-step coding unless the user asks for project harnessing, cross-session continuity, clean-room constraints, or durable planning files.
---

# Long-Running Project Harness

让项目在跨 session、跨 agent 工作中可恢复、可审阅、可交接。本入口只保留跨场景约束和路由；
细节在实际操作前按需读取，不一次性加载所有模块。

## 适用范围

用户要求长期 harness、持久计划、跨会话/多 agent 交接、clean-room 重建，或继续已有 harness 时使用。
简短解释、单文件小改动、普通多步骤任务不因此强制建立 harness。

## 核心边界

- 一个任务只有一个 canonical plan；`current/*` 是指针/恢复缓存，`harness-state.json` 是派生镜像。
- GitHub 保存公开协作事实；Standalone 文件或 Coordinate DB 按 profile 保存 runtime 状态。
  本地 checklist、聊天记录和 assignee 都不能单独证明跨 clone 没人施工。
- Operator、Worker、Reviewer 的职责和权限分开；同仓库的另一位 Operator 是平级维护者，
  只有明确的有界委派才建立上下级关系。详见 [执行与角色协作](references/workflow.md)。
- 只使用 `ordinary` / `high-risk` 两种风险模式；模式、运行方式、协作方式分别判断。
- 测试通过、审查通过、用户授权、合并、部署和平台验收是不同事实，不相互替代。
- 不覆盖其他 writer 的修改或 active lease；每个并行 writer 使用独立 branch/worktree。
- 产品代码、CLI/schema 与 runbook 是实例事实；本 skill 维护可泛化协议，不复制运行时手册，
  不增加 Issue tracker、分布式锁或第二套运行账本。用户当前明确要求优先，既有有界授权持续有效。

## 开始任务：先判断三个维度

读取当前项目规范、请求范围和必要的 Git/harness 状态，再按下列条件选择路径。
不要因为普通任务可直接实现，就跳过适用的协作前置检查。

| 维度 | 判断与动作 |
| --- | --- |
| 风险模式 | 可逆、低风险任务用 ordinary。生产/部署/删除/迁移、身份权限与 secret、持久 authority、租约并发、崩溃恢复或跨主机真实副作用用 high-risk；详见 [workflow](references/workflow.md)。普通多人协作本身不升级风险。 |
| 运行方式 | 只使用项目文件时是 Standalone；已有 Coordinate-managed 项目必须保留其 assignment/lease/receipt authority，读取 [workflow](references/workflow.md) 的运行方式边界。不要因协作需求自动安装 Coordinate/MultiNexus。 |
| 协作方式 | 项目采用 GitHub 协作 profile 时，**在实现前**读取并执行 [GitHub 协作子 skill](subskills/github-collaboration/SKILL.md)。多个维护者/宿主机共用该仓库时尤其不能省略；具体适用条件、查重/认领步骤和 Worker 例外只在那里定义。 |

若项目协作约定不明确且存在平级维护者，先只读核对远端相关工作和项目规范，确认协作范围后再实施；
不要从“本地没有 doing item”推导共享仓库无人负责。普通单 Operator、单 session、无协作/恢复需求的
小任务继续走轻量路径，不强制创建 Issue、checklist 或 runtime。

## 按需加载

只加载当前动作需要的模块，跨领域任务按执行顺序逐个读取。

| 当前动作 | 读取 |
| --- | --- |
| GitHub 多维护者/多宿主机开工、查重、认领、PR 交付 | [GitHub 协作](subskills/github-collaboration/SKILL.md) |
| 模式选择、角色/委派、任务开始/恢复/阻塞/收口 | [workflow](references/workflow.md) |
| 存储布局、canonical plan locator、跨 session 恢复与归档 | [storage-and-recovery](references/storage-and-recovery.md) |
| 初始化或维护可选 runtime、session-init、脚本实例化 | [runtime-setup](references/runtime-setup.md) |
| 登记 checklist、改 mode、理解校验/兼容行为 | [checklist-contract](references/checklist-contract.md) |
| 生成或审查 packet、写 verdict、关闭 runtime item | [events-and-packets](references/events-and-packets.md) |
| 产品方向、部署边界或新风险类别变化 | [scope-review](references/scope-review.md) |
| 选择审查上下文与审查方法 | [reviewer-strategy](references/reviewer-strategy.md) |
| 外部产品启发下的 clean-room 约束 | [clean-room-rules](references/clean-room-rules.md) |

模板在确定对应流程后再读：[项目文件](references/planning-files-template.md)、
[任务计划](references/task-plan-template.md)、[review](references/review-template.md)、
[blocker](references/blocker-template.md)。初始化/使用 runtime 的 session 可采用
[coding prompt](references/prompts/coding-prompt.md)；它不是所有 ordinary 任务的默认仪式。

## 最小执行闭环

1. 确认当前范围、三个维度和已有授权，先完成适用的 GitHub 协作前置检查。
2. 读取唯一当前计划和必要证据；由持有 authority 的 Operator 安排工作，Worker 核对分配范围。
3. 在自己的隔离范围内实现，运行与改动相称的验证，按需独立审查。
4. 保存实际结果、剩余问题和下一步；启用 runtime 时按对应 lifecycle 收口，遵守 packet/freshness 约束。

ordinary 可以只保留任务说明、实现、验证和必要审查；不强制 item、lease、packet、events 或 session-init。
high-risk 或已显式启用 runtime workflow 时，在 mutation 前读取相应执行/契约模块，不能以轻量模式
绕过已有 managed authority、审查新鲜度或恢复要求。配置缺失的 legacy item 模式由 runtime 按
high-risk 处理，不能自行按 ordinary 降级。

范围扩大、owner 冲突、authority 不足或事实无法核验时，先记录具体缺口与可继续的独立工作；
不要静默接手、把未执行的检查写成通过，或为跨过阻塞而修改规则。

## 与其他 skills 配合

- `planning-with-files`：当前 slice 的战术记录，不另建第二份项目计划。
- `invoke-coding-agents`：确需外部 provider 时管理进程与 session；本协议不绑定执行器。
- `coordinate-operator`：实际操作 Coordinate 时按其子模块执行；EXharness 不复制其 CLI 用法。
- GitHub 发布时按协作子 skill 的 provenance 路由声明真实来源；不把 provenance 当授权。

结束时简要报告变更、验证、当前状态与下一步。详细轨迹留在任务证据中，不塞回父 skill。
