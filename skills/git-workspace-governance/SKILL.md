---
name: git-workspace-governance
description: Use when multiple sessions or agents share one repository, when a primary checkout is dirty, stale, or not on the integration branch, when deciding what to back up before cleanup, when retiring branches or worktrees, or when verifying what was actually released. A project's own AGENTS or workspace rules take precedence.
---

# Git Workspace Governance

一个仓库同一时刻只有一条集成主线；本地只保留一个干净的 canonical checkout 作为镜像，所有任务在独立 worktree 里做；主线只经审查合入；发布只认远程 ref 的精确 SHA——任何本地目录内容都只是可能过期的缓存。

本 skill 只提供工作区治理边界和只读体检；不授予清理、合并、发布或业务操作权限。

## 什么时候用

- 多个 session / agent 共用同一个仓库，需要判断谁该在哪里写
- 本地主 checkout 脏了、停在旧分支、或落后远程主线
- 清理分支或 worktree、决定备份什么、删除前确认授权
- 发布前核对“实际发布的是哪个提交”
- 接手不熟悉的仓库，需要先只读体检

只做一次无关的小改动、且当前树干净且已在集成分支上时，不必加载本 skill。

## 建议动作：把规范入口挂进项目的 AGENTS.md（需人类授权）

跨 session、换模型后，agent 经常会忘记工作区约定和可用工具。最可靠的提醒位置是项目每轮都会读的 `AGENTS.md`（或等价的 instructions 文件），而不是聊天记录。

**先向用户提出建议并取得明确授权，再修改 `AGENTS.md`。** 它是项目的长期准则文件，agent 不得自行编辑，只能给出草案由人类拍板。用户同意后，通过项目正常 PR 流程加入类似 2–4 行：

```markdown
- 仓库级工作区治理（canonical checkout / task worktree / 清理备份 / 发布 SHA）：
  使用 skill `git-workspace-governance`；接手、清理或发布核对前先运行其只读体检。
- 修改本文件需要人类确认；项目规范优先于 skill 的缺省框架。
```

- 只放入口和边界，不要整份复制 skill 内容（会重复、漂移、挤占上下文）；
- 没有 `AGENTS.md` 的项目，先建议用户创建，不要擅自新建或改写别人的 instructions 文件；
- 不同项目形态的写法与授权话术见 [project-onboarding.md](references/project-onboarding.md)。

## 三种位置

| 位置 | 用途 | 边界 |
|---|---|---|
| canonical checkout | 集成主线的本地镜像，用于只读核对和发布前确认 | 只保持集成分支；不当任务工作区；不手工“整理” |
| task worktree | 一个任务一个分支一个目录 | 只写自己的任务路径；复用已有任务树前先确认归属 |
| release snapshot | tag 或固定 SHA 的只读快照，用于发布与回滚 | 只读；不开发；发布前记录精确 SHA |

## 六条原则

1. **三位置分离** → [state-model.md](references/state-model.md)
2. **集成主线纪律**：主线只接收审查合入；任务从最新远程集成分支的精确 ref 建支；不改写已推共享历史 → [state-model.md](references/state-model.md)
3. **事实来源优先级**：远程 ref > canonical 磁盘内容 > 本地缓存与印象；“这是主线代码 / 已合入 / 可清理”都要先只读核对 → [state-model.md](references/state-model.md)
4. **并发与所有权**：每条写命令明确 cwd；只暂存自己任务的路径；不跨树 stash / clean / checkout -- / reset；不接管他人 worktree → [state-model.md](references/state-model.md)
5. **清理与备份**：先备份后删除；只备份不可再生的最小集合；备份不授权清理；逐项确认 → [backup-and-cleanup.md](references/backup-and-cleanup.md)
6. **发布是另一条边界**：合并、发布、业务验收是三件不同的事；发布前读回四个 SHA → [release-verification.md](references/release-verification.md)

## 决策表

| 要做的事 | 用哪个位置 / 动作 |
|---|---|
| 读主线代码 | canonical checkout（先确认在集成分支且干净）或 `git show <remote>/<integration>:<path>` |
| 开发 / 修改 | 从最新远程集成分支建任务 worktree |
| 收尾 / 合入 | 走 PR 流程；合入后再评估 worktree 退役（需授权） |
| 恢复脏的 canonical checkout | [recovery.md](references/recovery.md)，单独授权后执行 |
| 备份 / 清理 | [backup-and-cleanup.md](references/backup-and-cleanup.md) |
| 发布 / 回滚 | [release-verification.md](references/release-verification.md) + release snapshot |
| 接手先体检 | 下文“只读体检” |

## 接手五问

1. 我在 canonical checkout 还是 worktree？仓库根和 common git dir 分别在哪？
2. 当前在集成分支吗？干净吗？落后远程主线多少？
3. 要改的东西是否已有任务、分支或 worktree？先恢复原任务，不重复开工
4. 这次写入的路径范围和授权边界是什么？
5. 是否有运行中的消费者依赖这棵树里的文件？

任一问题答不上来，先只读核对，不要开始写。

## 只读体检

优先使用项目自带的只读 checker。没有时运行本 skill 自带的脚本：

```bash
python3 <skill-dir>/references/scripts/check_workspace_state.py --repo . --json
```

它只读取本地 Git 事实：不 fetch、不修复、不改变任何状态、单命令 10 秒超时、按本地缓存的远程 ref 比较。输出 canonical 的分支 / HEAD / 改动数、本地集成分支与缓存远程 ref 的 ahead/behind、全部 worktree 清单和 warning。

字段、warning 码、退出码和已知限制见 [health-check.md](references/health-check.md)。告警只提供线索，不自动修复，也不阻塞其他独立任务。

## 可选集成（不是依赖）

本 skill 可独立安装和使用；不要求、不检查、也不调用任何其他 skill。若环境恰好提供下列能力，可改用它们，再按本 skill 的边界执行；没有时使用 fallback。

| 能力 | 常见可选实现（示例，非要求） | 本 skill 的 fallback |
|---|---|---|
| 创建 / 复用 / 退役任务 worktree | 环境中的 worktree skill（如 `using-git-worktrees`） | [standalone-fallbacks.md](references/standalone-fallbacks.md) |
| 任务分支收尾（合并 / PR / 保留） | 环境中的分支收尾 skill（如 `finishing-a-development-branch`） | [standalone-fallbacks.md](references/standalone-fallbacks.md) |
| 长期项目协议、交接与审查 | 配套 skill `long-running-project-harness`（若已安装） | 本 skill 只处理工作区边界 |
| 外部 coding agent 调用与监督 | 配套 skill `invoke-coding-agents`（若已安装） | 本 skill 不涉及 |

项目自己的 AGENTS.md、贡献指南或工作区规范优先于本 skill；本 skill 只提供缺省框架。

## 硬约束

- 不使用 `git clean`、`reset --hard`、`checkout --`、`worktree remove --force`、批量 `prune` 或自动删除分支来“把树弄干净”
- 不覆盖或删除他人未提交内容；不接管不属于自己的 worktree
- 不把“干净”“已合入”当作清理授权；不把“合入”当作发布授权
- 不把依赖、虚拟环境、浏览器缓存、构建产物当作必须备份的资产
- 不把本地缓存的分支或 SHA 当作远程事实
- 不擅自修改项目的 `AGENTS.md` 等 instructions 文件；只能提出建议并等待人类授权

## 按需读取

| 场景 | 读取 |
|---|---|
| 位置模型、主线纪律、事实来源、并发边界 | [state-model.md](references/state-model.md) |
| 恢复 canonical checkout | [recovery.md](references/recovery.md) |
| 备份取舍与清理授权 | [backup-and-cleanup.md](references/backup-and-cleanup.md) |
| 发布前 SHA 核对 | [release-verification.md](references/release-verification.md) |
| 体检脚本契约与限制 | [health-check.md](references/health-check.md) |
| 常见自欺与红旗 | [anti-patterns.md](references/anti-patterns.md) |
| 把规范入口挂进项目 AGENTS.md（需人类授权） | [project-onboarding.md](references/project-onboarding.md) |
| 没有其它 skill 时的最小闭环 | [standalone-fallbacks.md](references/standalone-fallbacks.md) |

## 报告要求

结束时报告实际做了什么：核对了哪些位置、创建或复用了哪棵树、读了哪个 ref、是否备份或清理、哪些留给用户确认。合并、部署和业务验收是不同事实，不能由工作区操作推出。
