# 恢复 canonical checkout

当 primary checkout 不在集成分支、或长期脏、或明显落后时使用。这是**独立、需授权的操作**，不是顺手整理。

## 前置条件（缺一不可）

1. 未纳管内容已按 [backup-and-cleanup.md](backup-and-cleanup.md) 备份或归档；
2. 每个残留改动的归属已确认（自己的 / 他人的 / 已合入待清理）；
3. 运行中的消费者已核对（是否有进程仍依赖这棵树的文件、配置或数据库）；
4. 用户明确授权“切换这棵树”的范围。

## 步骤

### 1. 只读盘点

```bash
cd <canonical-checkout>
git status --short --branch
git worktree list --porcelain
git rev-parse HEAD
git rev-parse <remote>/<integration>
```

记录：当前分支、HEAD、tracked 改动数、untracked 文件数、本地集成分支与远程的关系。

### 2. 把残留内容分三类

| 类别 | 判别 | 处理 |
|---|---|---|
| A. 旧副本 | 路径在集成分支也存在，内容相同或明显更旧 | 列入“待删除清单”，逐条确认后删除；不做批量 clean |
| B. 不可再生内容 | 任何 ref 里都没有的 untracked、本地配置、证据 | 非敏感内容按备份规范归档或提交到归档分支；凭据和私密配置只做私密备份，不进入 Git |
| C. 未提交的 tracked 改动 | `git status` 的 modified/staged | 确认归属：提交到任务分支、归档补丁，或明确丢弃 |

对 B 类要比较内容而不是只看路径；“集成分支没有同名文件”不等于“其它 ref 也没有”。

### 3. 归位

- A 类：按显式文件清单删除；删除前再核对一次路径，不做通配；
- B 类：归档后确认可从归档恢复；
- C 类：转到对应任务分支或归档为补丁；
- 完成后重新跑 `git status --short`，目标只剩空输出。

### 4. 切换到集成分支

```bash
git switch <integration>
git status --short          # 必须为空
git pull --ff-only <remote> <integration>
git worktree list           # canonical 应显示集成分支
```

### 5. 验证

- `git status --short --branch` 干净且在集成分支；
- `git rev-parse HEAD` 与 `<remote>/<integration>` 一致（或在允许的落后范围内）；
- 只读体检脚本无 `canonical_not_integration` / `canonical_has_changes` / `local_integration_behind` 告警；
- 报告“恢复前 / 恢复后”的 SHA 和清理清单。

## 失败处理

| 现象 | 处理 |
|---|---|
| `git switch` 报 untracked 文件将被覆盖 | 回到步骤 2；不许用 `-f` 或先 clean 再切 |
| 本地集成分支与远程分叉 | 停止；先确认本地独有提交归属，再决定 ff / 归档，禁止 reset 丢弃 |
| detached HEAD | 先判断它属于哪个任务或快照；nested worktree 的 detached 不应由这里切换 |
| 仓库是 bare 或无 primary checkout | 不支持此流程；按项目实际布局处理 |
| 配置了外部 clean/process 过滤器 | 不做“干净”断言；按未知状态报告 |

## 恢复之后

- canonical checkout 只保持集成分支；任务一律在新 worktree 中做；
- 每次接手先跑只读体检；
- 已清理内容在授权保留期内可回滚，过期后再销毁。

## 禁止

- 用 `reset --hard`、`checkout --`、`clean -fd/-fdx`、`worktree remove --force` 或批量 prune 制造“干净”；
- 把别人的未提交内容当作自己的残留删除；
- 未备份就切分支、未确认消费者就清空目录。
