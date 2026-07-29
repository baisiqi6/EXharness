# Long-Running Project Harness

这是一个面向长期工程项目的 Codex/Claude skill，目标是提供持久项目记忆、多 session 恢复和显式多 agent handoff。

本仓库定位为 file-backed protocol runtime。它不是 coordinator、消息总线、remote runner，也不是 GitHub 自动化服务。

## 本 Skill 负责什么

- 持久项目文件：产品 repo 中的 `scope.md`、`architecture.md`、`domain-model.md`、精简状态与 `runbook.md`
- 任务文件：唯一 task artifact root 中的 `tasks/<item-id>/plan.md` 和 task-scoped evidence；该 root 可以是独立私有仓库
- 薄运行层脚本：`harnessctl`、checklist 校验、状态派生、packet 生成、本地 owner/lease 护栏
- 本地事件日志：`events.jsonl`

`events.jsonl` 是 append-only event log / outbox candidate。脚本会写入 `publish_status=local_only`；它不提供 Discord/KOOK 投递确认、重试、平台消息 id 绑定或崩溃恢复。

## Coordinator 边界

coordinator 是独立服务层。它消费本 harness 协议，并负责不应该塞进 skill 的运行时基础设施：

- SQLite event store 和 job store
- 可靠 Discord/KOOK bus outbox
- remote runner 调度和 retry 记录
- GitHub branch、PR、CI、review 集成
- 进程重启后的恢复能力

coordinator 项目通常位于：

```text
${COORDINATE_REPO:-$HOME/projects/coordinate}
```

Coordinate 的当前架构、范围、运维和历史入口分别维护在：

```text
${COORDINATE_REPO:-$HOME/projects/coordinate}/docs/architecture.md
${COORDINATE_REPO:-$HOME/projects/coordinate}/docs/scope.md
${COORDINATE_REPO:-$HOME/projects/coordinate}/docs/runbook.md
${COORDINATE_REPO:-$HOME/projects/coordinate}/docs/archive-index.md
```

可复用的 harness 协议决策放在本仓库中维护。coordinator 的 delivery、runner、SQLite 和 GitHub 集成决策放在 coordinator 项目中维护。

若使用 split storage，产品 repo 保存稳定规范，`$MYHARNESS_ROOT/projects/<project_id>/` 保存
task-scoped 过程材料（bootstrap、review、handoff、verdict、receipt、archive index）。**active canonical
plan 的位置按形态区分**：Coordinate-managed 项目的 active plan 留在产品 workspace（split-operation
`plan_doc` 要求 workspace-relative），`$MYHARNESS_ROOT` 只存该 task 的过程材料；Standalone（无
Coordinate runtime）项目可以把 active plan 放在 `$MYHARNESS_ROOT`。不要提交 raw JSONL、session logs、
DB backup、secret 或大型输出。Coordinate 的 path 约束按调用层区分：full harness 和 split-operation
使用 workspace containment/relative-path guard，minimal file harness 技术上允许 external absolute root。
本项目 policy 仍保持 active plan workspace-local；不能用 symlink 或放宽 guard 绕过受审边界。

整个 `$MYHARNESS_ROOT` 可以是一个独立私有 Git repository。每个项目只提交自己的
`projects/<project_id>/` 子树；共享根文件使用独立维护 commit。单 writer 使用 path-scoped commit，
多个项目并发写入时使用独立 branch/worktree，因为不同目录并不会隔离共享 Git index 和 `HEAD`。

## 安装与启用

本仓库本身就是一个 skill 目录，不需要 `pip install`、编译或后台服务。前置环境为 Git、Bash 和
Python 3.12+。

1. clone 或下载本仓库；
2. 将目录命名为 `long-running-project-harness`，放入所用 agent client 能发现的 skill root；
3. 重新启动 session，并确认 client 能读取根目录 `SKILL.md`。

不同 client 的 skill root 与发现方式不同，请以对应 client 的文档为准。本项目不提供会猜测客户端路径的
通用 `install.sh`。`references/scripts/` 是生成项目实例 runtime 的模板，不是本仓库安装器。

安装后可在仓库根目录运行下方验证命令；它们只使用 Python 标准库和 Bash。

## 当前状态

本仓库维护稳定的 harness 协议与薄 file-backed runtime：先保证文件语义，再用薄脚本减少人工搬运；
真正的自动协调、跨主机运行状态和可靠消息投递放到 Coordinate 层。

## 验证

运行 runtime 测试：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s references/tests -p 'test_*.py'
```

检查 shell command router：

```bash
bash -n references/scripts/harnessctl
```

## 许可证

本项目使用 [MIT License](LICENSE)。
