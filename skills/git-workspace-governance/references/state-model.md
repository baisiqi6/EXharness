# 位置模型与主线纪律

判断“该在哪里做、该信哪个 ref、能写哪些路径”时读取。

## 1. 三种位置的职责

### canonical checkout

仓库的 primary worktree（`git worktree list` 的第一条，也是 `.git` 常见目录所在位置）。

- 只保持集成分支（默认 `main`），供只读核对、发布前确认；
- 不作为任务工作区；不在上面开发、提交或“顺手整理”；
- 需要看主线代码时先确认：当前分支是集成分支、工作树干净、本地 ref 与远程 ref 的关系已知；
- 项目如果自定义了主 checkout 用途，以项目规则为准。

### task worktree

每个任务一个分支、一个物理目录。

- 新任务从最新远程集成分支的**精确 ref/SHA** 创建，不沿用某个恰好被检出的旧分支；
- 复用已有 worktree 前确认它属于当前任务或被明确交接；
- 只写任务范围内路径；不同任务可以在不同分支修改同一文件，只有同一物理树覆盖未提交内容才需要协调；
- 临时目录（如系统临时区）不放长期任务树。

### release snapshot

打 tag 或固定在某个 SHA 上的只读快照。

- 只读；不承接开发；
- 发布、回滚都以它的精确 SHA 为准；
- 发布前记录当前生产/部署的 HEAD，便于回滚。

## 2. 集成主线纪律

- 集成分支只接收经审查的合入（PR 或项目明确的受控流程），不在上面直接开发；
- 任务分支从最新远程集成分支创建；远程前进后，任务是否需要 rebase 由项目规则决定；
- 已推送的共享历史不改写、不 force-push；
- 旧任务优先恢复，不为同一任务重复创建工作树或分支；
- 合入、发布、业务验收是不同事实：合入不等于部署，部署不等于验收。

## 3. 事实来源优先级

```text
远程 ref 的精确 SHA  >  canonical checkout 磁盘内容  >  本地缓存 / 记忆 / 目录名
```

常见误判与正确核对方式：

| 误判 | 正确做法 |
|---|---|
| “目录叫 main，就是主线” | 看 `git rev-parse HEAD` 和当前分支，不看目录名 |
| “本地 main 就是远程 main” | 看本地缓存 `origin/main` 的 SHA；需要最新答案时先 fetch 或 `ls-remote` |
| “工作树干净就能删” | 干净只说 tracked/untracked 状态，ignored 资产和运行消费者仍未核对 |
| “HEAD 不在主线历史，肯定没合入” | 可能已被 squash 合入；查 PR/合入证据，不能只看祖先关系 |
| “别人分支上的文件肯定是旧版本” | 比较内容而不是路径；main 有同名文件不代表本地没有独有修改 |

## 4. 并发与所有权

- 每条写命令明确工作目录；只暂存自己任务的路径，不从主 checkout `git add -A`；
- 不跨树执行 `stash`、`clean`、`checkout --`、`reset`，不清理他人未提交内容；
- 不接管、不切换、不移除不属于自己的 worktree；
- 多 agent 并行时：不同 session、不同 worktree 或互不重叠的路径 allowlist；
- 不同分支修改同一文件是正常的；只有同一物理树的未提交内容被覆盖，或接口契约冲突时才需要协调。

## 5. 只读核对命令

```bash
git rev-parse --show-toplevel
git rev-parse --path-format=absolute --git-dir --git-common-dir
git rev-parse --show-superproject-working-tree
git branch --show-current
git status --short --branch
git worktree list --porcelain
git rev-parse <remote>/<integration>
```

说明：

- `--git-dir` 与 `--git-common-dir` 不同通常表示 linked worktree，但 submodule 也会如此：用 `--show-superproject-working-tree` 区分；
- bare 仓库没有普通 primary checkout；
- `git status` 可能执行配置的 fsmonitor 或内容过滤器，不能只因为命令叫 status 就把它当绝对只读；未知状态如实报告。
