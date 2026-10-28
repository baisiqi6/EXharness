# 独立使用时的最小闭环

本 skill 不依赖任何其它 skill。若环境里没有更完整的 worktree 或分支收尾 skill，用下面两个最小流程即可闭环；若环境提供更完整实现，可改用它们，结果等价。

## A. 最小建树流程

### 1. 确认当前位置

```bash
git rev-parse --show-toplevel
git rev-parse --path-format=absolute --git-dir --git-common-dir
git rev-parse --show-superproject-working-tree
git branch --show-current
git worktree list --porcelain
git status --short --branch
```

- `--git-dir` 与 `--git-common-dir` 不同且不在 submodule 内 → 已在 linked worktree；
- 已在属于本任务的 worktree → 直接复用，不重复创建；
- 在 primary checkout → 按项目规则换到独立 worktree 再开发。

### 2. 选 base 和位置

- base：项目要求优先；否则刷新远程集成分支，用精确 ref/SHA 创建（不是“当前检出的分支”）；
- 位置：项目显式约定 > 已有约定 > 项目内被 ignore 的 `.worktrees/` 目录；不使用系统临时目录存放长期任务。

### 3. 创建

```bash
git fetch <remote> <integration>
git worktree add -b <task-branch> <absolute-path> <remote>/<integration>
```

### 4. 验证

```bash
git -C <absolute-path> rev-parse --show-toplevel
git -C <absolute-path> rev-parse HEAD
git -C <absolute-path> branch --show-current
git -C <absolute-path> status --short --branch
```

确认：路径正确、HEAD 等于创建时选定的 ref、分支正确、起始状态干净（依赖安装按任务需要决定）。

## B. 最小收尾流程

### 1. 测试

运行与改动面相关的测试；区分“本来就有失败”和“本次引入的回归”，不把未执行的检查说成通过。

### 2. 决定去向

与用户确认三种之一：本地合并 / 推送并开 PR / 保留分支暂不处理。不要擅自合并或删除。

### 3. 核对后再退役

worktree 退役是独立动作，清理前至少核对：

- 任务 owner 与 PR/合入状态；
- staged / unstaged / untracked / ignored 内容；
- 本地独有提交与 stash；
- 用户授权是否覆盖具体路径和分支。

### 4. 执行

```bash
git worktree remove <absolute-path>     # 不带 --force
git branch -d <task-branch>             # 确认合入后再删；不自动删远端分支
```

## 与完整 skill 的关系

- 环境提供更完整的 worktree 创建/复用/退役 skill → 优先用它们，本流程作为对照；
- 环境提供分支收尾 skill → 优先用它们，本流程作为 fallback；
- 无论用哪套，备份、清理授权、发布边界仍以本 skill 的规范为准。
