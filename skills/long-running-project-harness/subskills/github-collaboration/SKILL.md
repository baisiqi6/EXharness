---
name: long-running-project-harness-github-collaboration
description: Apply the EXharness GitHub collaboration profile before implementation and during PR delivery, especially when peer Operators share a repository across hosts. Covers semantic overlap, cooperative claims, shared-account identity, and GitHub versus runtime authority; does not require Coordinate or add a task tracker.
---

# GitHub 协作 profile

本模块是 EXharness GitHub 协作前置检查的唯一规范。父入口、session prompt 和开工模板引用
本模块，不各自复制一份认领规则。

## 适用条件与轻量例外

项目明确采用 GitHub Issue/PR 作为工作协调入口时适用，尤其是多个平级 Operator 或宿主机
共同维护同一仓库。风险模式仍单独选择：ordinary 不免除适用的 GitHub 协作检查，GitHub
协作也不自动升级 high-risk。普通单 Operator、单 session、无需协作或恢复的小任务不因此
强制建 Issue/checklist；无 GitHub 的 Standalone 项目继续使用自己选定的稳定任务 ID。

已分配的 Worker 不重复创建 Issue 或冒充另一位 Operator 认领；它应核对任务包中的 Issue、
负责 Operator、分支/基线、范围和当前远端冲突。证据缺失/漂移时请派发 Operator 补齐，完成
之前只做不改变产品的分析。另一宿主机的 Operator 是平级维护者，不因共享账号成为本会话的 Worker。

## 开工前置检查

在产品代码编辑、派发实现 Worker 或进入实现工作树开工前完成以下检查。只读调查和准备计划
可以先做。恢复任务时核对现有认领，不重复登记。

1. **识别重叠。**读取相关 Issue、评论/认领和 PR，按用户问题、症状/配置/函数关键词及修改
   范围搜索；不能只搜 Issue 编号。对相关命中核对当前 head、具体行为与 owner 范围。
   外部社区独立候选再按 [候选准入指南](../../references/candidate-collision-check.md) 留下
   shortlist、实现前、发布前三阶段证据。内部已有任务的协作也必须做语义查重，但不机械套用
   全仓候选筛选仪式。
2. **选择工作归属。**先核验对应 Issue 仍为 open，再复用；若已关闭，检查关闭理由、关联
   合并和当前问题是否仍存在，由负责 Operator 决定授权重开或登记有明确差异的新问题，不能
   根据旧本地 todo 直接认领/继续实现。已修复则停止原修复计划。有 active PR/人工认领时
   先协作，或明确不重叠的独立范围。没有对应项时，在已有授权内创建 Issue。当地 checklist 显示 todo、无 assignee
   或无关联标签均不能单独证明无人施工；owner/范围冲突未解决前不重复实现。
3. **登记并读回认领。**在项目约定的 Issue 正文、评论、assignee/label 中公开记录负责的
   Operator、问题范围、基线/分支与验收标准，并重新读取远端确认。共享 GitHub 账号时仅设
   assignee 不足以区分 Mac/Windows 等维护者；使用已确认的逻辑 host、agent、角色标识，
   不暴露私有 hostname、IP 或 session。已有足够的认领直接复用，不反复刷评论。
   没有公开写入权限/授权时，先准备认领内容并报告缺口，不虚构认领已完成。
4. **进入隔离实现。**使用该 writer 的 branch/worktree；将 Issue 与唯一 task plan 关联。
   若启用 checklist，单仓库 Issue `#123` 对应稳定 ID `issue-123`，多仓库由项目明确 namespace。
   普通任务不会仅因存在 Issue 就必须创建 checklist 或 lease。
5. **交付并刷新。**push/PR 前刷新相关工作状态，创建关联 PR 并按项目约定使用 `Closes #123`
   等关系。review、CI、冲突和合并门槛由 PR/项目流程承载。Mac/Windows 等平台的验收分别
   留证，一端通过不冒充另一端通过；认领、push、merge、发布权限不互相推导。

认领内容与公开交付遵循 [GitHub agent provenance](../github-agent-provenance/SKILL.md)。
provenance 仅说明实际来源，不产生 mutation authority。详细 plan/review/raw evidence 保留在
任务证据中；Issue 只留可供其他维护者协调的摘要与 locator。

## GitHub 与运行方式的组合

GitHub Issue 保存需求、repo-scoped identity 和 cooperative claim，PR 保存代码、CI 与 review。
它们不提供数据库级 hard lock；认领后仍需处理并发和新的远端变化。

- **Standalone**：需要 item 时使用 `harnessctl add-item` / `update-item`，已有 runtime 的
  accept/start/lease/closeout 仍按 [workflow](../../references/workflow.md) 执行。
- **Coordinate-managed**：GitHub 认领与 runtime assignment 各自满足；使用 Coordinate 的
  lifecycle/combined-create/mirror 入口，不裸改 checklist/DB，不用 GitHub assignee 绕过 lease
  或 receipt。实际操作按已安装的 `coordinate-operator` 对应模块；模块不可用时报告缺口，
  不退回未经授权的 Standalone mutation。

分支中的 checklist 是 merge candidate；main 上的 checklist 是已接受的 canonical snapshot。
其他 clone 的工作状态以远端 Issue/PR 与相应 runtime authority 核验，不把本地副本当全局锁。

合并时，两个不同 Issue 的节点可以共存；Git 无文本冲突也仍需 validator 检查 duplicate ID。
同一 ID 的 title、acceptance 或计划语义不同则停止合并，由 reviewer 对照 Issue 核对；不能
静默覆盖、重编号或创建第二份 checklist。本模块不向 runtime 增加 GitHub API、registry 或锁。
