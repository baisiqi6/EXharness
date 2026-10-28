# 只读体检契约

横向机制：接手仓库、准备清理、发布前核对时先跑一次只读体检。它只提供线索，不自动修复，也不阻塞其他独立任务。

## 1. 优先级

1. 项目自带的只读 checker（若有）；
2. 本 skill 的 `references/scripts/check_workspace_state.py`；
3. 手工执行 [state-model.md](state-model.md) 第 5 节的只读命令。

## 2. 脚本保证

- 只用 Python 标准库（3.12+）；
- 不 fetch、不访问网络、不修复、不改变任何 Git 状态；
- 单条 Git 命令 10 秒超时；禁用可选锁、fsmonitor、untracked cache、自动 maintenance；
- 使用本地缓存的远程 ref 作参考，不声称它是实时远程状态；
- 不输出 Git stderr、凭据或 URL；路径默认只打印、不落盘。

## 3. 用法

```bash
python3 <skill-dir>/references/scripts/check_workspace_state.py                       # 当前目录
python3 <skill-dir>/references/scripts/check_workspace_state.py --repo <path>         # 任意 worktree
python3 <skill-dir>/references/scripts/check_workspace_state.py --repo <path> --json
python3 <skill-dir>/references/scripts/check_workspace_state.py --integration-branch main --remote origin
```

可从仓库任意 worktree 运行；脚本会定位同一个仓库的 primary checkout。

## 4. 输出字段

| 字段 | 含义 |
|---|---|
| `captured_at` | 采集时间（UTC） |
| `reference_scope` | 参考对象说明：本地缓存的远程 ref，未 fetch |
| `status_scope` | 扫描范围说明：列出的 worktree；不进入 submodule 内部 |
| `canonical` | primary checkout 的分支 / HEAD / tracked 改动数 / untracked 数 / last commit / 错误码 |
| `integration_branch` / `remote` | 使用的集成分支与 remote 名 |
| `remote_ref` / `remote_ref_sha` | 缓存远程 ref 名与 SHA |
| `local_integration` | 本地集成分支相对缓存远程 ref 的 ahead / behind |
| `worktree_count` / `worktrees` | 全部 worktree 及其分支、HEAD、改动数、`head_in_integration`、lock/prunable、错误码 |
| `warnings` | 汇总告警码 |

## 5. Warning 码

| 码 | 含义 |
|---|---|
| `canonical_unreadable` | primary checkout 自身读取失败（见下方错误码） |
| `canonical_not_integration` | primary checkout 不在集成分支 |
| `canonical_has_changes` | primary checkout 有 tracked 或 untracked 改动 |
| `local_integration_missing` | 本地没有集成分支 |
| `cached_remote_ref_missing` | 本地没有缓存的远程 ref（不代表远程不存在） |
| `local_integration_behind` | 本地集成分支落后缓存远程 ref |
| `local_integration_ahead` | 本地集成分支有远程 ref 没有的提交 |

## 6. Worktree 行错误码

| 码 | 含义 |
|---|---|
| `worktree_unavailable` | 路径不存在或不可读 |
| `worktree_repository_mismatch` | 该路径不属于同一个仓库 |
| `worktree_head_changed_during_scan` | 扫描期间 HEAD 被其它进程切换，结果不可用 |
| `external_git_filter_not_assessed` | 配置了实际使用的外部 clean/process 过滤器，不声称“干净” |
| `git_read_timeout` / `git_unavailable` / `git_read_failed` | 读取失败 |

## 7. 退出码

- `0`：成功产出报告（warning 和行错误只是线索）；
- `2`：连 primary checkout / 仓库基本信息都无法读取，报告不可用。

## 8. 已知限制

- 报告是**本地观察**，不是跨会话锁或全局一致快照；扫描期间其它进程可能改变状态；
- 使用缓存的远程 ref，不保证与远程实时一致；
- 不扫描 submodule 内部状态（需在各自仓库单独运行）；
- `head_in_integration=false` 只说明不是祖先，不能断言“未合入”（可能 squash）；
- 不判断 owner、PR 等价关系、活跃运行依赖或 ignored 资产，因此**不构成清理授权**。

## 9. 接入建议

- 接手第一步运行；日志只保留 warning 摘要；
- 需要时在 CI 中作为只读检查运行，但不要把历史遗留 warning 变成阻塞所有开发的硬门禁；
- 项目可以基于同一字段契约实现自己的 checker，本脚本只作为缺省实现。
