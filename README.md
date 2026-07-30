# Long-Running Project Harness

一个面向长期工程项目的 agent skill：让项目能被跨 session、跨 agent 恢复、审阅、实现、验证和交接。把对话上下文当临时内存，把项目文件当长期记忆。

如果你正在做一个需要多次 session、多个 agent、或者跨天推进的项目，又不想每次重新解释背景、丢失进度、或者靠聊天记录猜状态——这个 skill 适合你。

## 解决什么问题

长期项目最常见的失败不是写不出代码，而是**方向感丢失**：换一个 session 就忘了上次做到哪、为什么这么决定、还差什么。这个 skill 用一套持久化文件协议解决这个问题——让项目状态落盘、可恢复、可审计，不依赖任何 session 还活着。

核心能力：

- **项目记忆**：`scope.md`、`architecture.md`、`domain-model.md`、`runbook.md` 等稳定规范文件，加上 `mvp-checklist.json` 的机器可读状态。
- **任务追踪**：每个任务有 `tasks/<item-id>/plan.md` canonical plan 和 task-scoped evidence，不会被覆盖。
- **多 agent 协作**：operator / worker / reviewer 显式分工，handoff / review / blocker / closeout packet 让交接可定位、可审计。
- **薄运行层**：`harnessctl` 命令、checklist 校验、状态派生、packet 生成、本地 owner/lease 护栏——减少人工搬运，但不取代你的判断。
- **确定性 session init**：新 session 开头先刷新状态、跑校验、读最小摘要，而不是靠人脑回忆。

这个 skill 是**协议优先**：先保证文件语义正确，再用薄脚本减少机械工作。它不是自动代理框架，不替你做产品决策。

## 快速开始

**前置**：Git、Bash、Python 3.12+。不需要 `pip install`、编译或后台服务。

这个仓库本身就是一个 skill 目录：

```bash
# 1. clone
git clone https://github.com/baisiqi6/EXharness.git long-running-project-harness

# 2. 放进你的 agent client 能发现的 skill root
#    (具体位置因 client 而异,以你的 client 文档为准)
mv long-running-project-harness ~/.agents/skills/

# 3. 重启 session,确认 client 能读到根目录的 SKILL.md
```

装好后，在你的项目里告诉 agent「用 long-running-project-harness 给这个项目建 harness」，它会按协议创建标准文件：

```text
docs/project-harness/
  scope.md              # 长期目标 + 不做的事
  architecture.md       # 架构边界
  domain-model.md       # 关键决策
  mvp-checklist.json    # 机器可读任务状态(todo/doing/done/blocked)
  progress.md           # 人类可读进展
  runbook.md            # 操作手册
  events.jsonl          # append-only 关键事件日志
  current/              # 当前任务指针 + handoff/review/blocker packet
  tasks/<item-id>/plan.md   # 每个任务的 canonical plan
```

之后每次开新 session，agent 会先读这些文件恢复上下文，而不是从零开始。

## 部署形态

**Standalone**（默认）：纯 file-backed harness。`events.jsonl` 是 append-only 事件日志，不提供发布确认、重试或跨平台幂等——它是 outbox candidate，不是可靠消息总线。

**带 Coordinator**：如果你需要 SQLite 事件存储、可靠消息投递、remote runner 调度或 GitHub PR/CI 集成，那些由独立的 coordinator 服务层负责，不塞进这个 skill。两者通过协议组合，不共享内部代码。

## Clean-Room

如果项目受外部产品启发，保持独立设计：可以用通用的产品目标和架构权衡，但不复制外部源码、API 形状、prompt、文档或测试。详细规则见 `references/clean-room-rules.md`。

## 验证

```bash
# runtime 脚本测试(只依赖 Python 标准库)
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s references/tests -p 'test_*.py'

# shell 命令路由器语法检查
bash -n references/scripts/harnessctl
```

`scripts/validate-checklist.py` 可跨项目直接引用，校验 `mvp-checklist.json` 的结构和语义：

```bash
python3 scripts/validate-checklist.py path/to/mvp-checklist.json
```

`references/scripts/` 是生成项目实例 runtime 的**模板**（含 `{{占位符}}`），不是这个仓库的安装器。

## 状态与边界

本仓库维护稳定的 harness 协议与薄 file-backed runtime。真正的自动协调、跨主机运行状态和可靠消息投递放到 coordinator 层。运行层脚本只做：读校验文件、领取/续租/释放 owner-lease、生成 packet、追加事件、派生机器可读状态镜像。

## 许可证

[MIT License](LICENSE)。
