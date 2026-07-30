# EXharness

一组面向长期工程项目和多 agent 协作的 agent skill。本仓库是一个 skill 集合（monorepo），包含两个互相独立、各有所长的 skill。

长期项目最常见的失败不是写不出代码，而是**方向感丢失**：换一个 session 就忘了上次做到哪、为什么这么决定、还差什么。本仓库的 skill 围绕这个问题——让项目状态落盘、可恢复、可审计，并让多个 agent 能实际协作推进。

## 包含的 skill

### `long-running-project-harness` — 长期项目协作协议

让项目能被跨 session、跨 agent 恢复、审阅、实现、验证和交接。把对话上下文当临时内存，把项目文件当长期记忆。

核心能力：

- **项目记忆**：`scope.md`、`architecture.md`、`domain-model.md`、`runbook.md` 等稳定规范，加上 `mvp-checklist.json` 机器可读状态。
- **任务追踪**：每个任务有 `tasks/<item-id>/plan.md` canonical plan 和 task-scoped evidence，不会被覆盖。
- **多 agent 协作协议**：operator / worker / reviewer 显式分工，handoff / review / blocker / closeout packet 让交接可定位、可审计。
- **薄运行层**：`harnessctl` 命令、checklist 校验、状态派生、packet 生成、本地 owner/lease 护栏。

它是协议优先：先保证文件语义正确，再用薄脚本减少机械工作。它不是自动代理框架，不替你做产品决策。

### `invoke-coding-agents` — agent 调用与监督方法

教 agent 如何用 stdio 调起、监督、恢复和验收本地外部 coding agent CLI（Claude Code、Qoder、Grok Build、OMP、OpenCode、Codex 等）。

核心能力：

- **结构化调用**：固定 cwd、权限 allowlist、session 定位、超时、验收——不是发一句自然语言就等结果。
- **provider 路由**：每个 agent CLI 一份 reference，实时核验 binary/model，不硬编码历史路由。
- **监督与验收**：worker 自述、测试通过、reviewer verdict、operator acceptance 是不同证据，不混为一谈。

## 两个 skill 的关系

它们**互相独立，各满足不同需求**：

- 经常有这种情况：用户跟自己的 agent 说"你去调用某某 agent 做某件事"——这时只需要 `invoke-coding-agents`，不需要整个项目 harness 协议。
- 反过来，做长期项目多 agent 协作时，一般会需要 `invoke-coding-agents`——因为 harness 协议规定了 operator/worker/reviewer 怎么分工交接，但 worker/reviewer 进程要靠 `invoke-coding-agents` 实际拉起来、监督和验收。

所以两者是**软依赖**：harness 引用 invoke-coding-agents 作为"怎么调起 agent"的方法，但不强制、不内联。各自独立安装、独立使用。

## 快速开始

**前置**：Git、Bash、Python 3.12+。不需要 `pip install`、编译或后台服务。

本仓库是 skill 集合，clone 后需要把要用的 skill 放进你的 agent client 能发现的 skill root：

```bash
# 1. clone
git clone https://github.com/baisiqi6/EXharness.git

# 2. 把要用的 skill 目录放进 skill root
#    (具体位置因 client 而异,以你的 client 文档为准)
cp -R EXharness/skills/long-running-project-harness ~/.agents/skills/
cp -R EXharness/skills/invoke-coding-agents        ~/.agents/skills/

# 3. 重启 session,确认 client 能读到两个 skill 的 SKILL.md
```

装好 `long-running-project-harness` 后，在你的项目里告诉 agent「用 long-running-project-harness 给这个项目建 harness」，它会按协议创建标准文件：

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

## 和 Coordinate / MultiNexus 的关系

`long-running-project-harness` **可以直接给 agent 在项目里实例化**，不依赖任何外部服务就能用——纯文件协议 + 薄脚本。

当你需要更重的能力——SQLite 事件存储、可靠消息投递、remote runner 调度、跨宿主机多 agent 协同的 runtime 运行时管理、GitHub PR/CI 集成——那些由独立的 **Coordinate**（确定性协调内核）和 **MultiNexus**（agent 执行织物）两层实例化项目负责。这两层调用密集、几乎不分家，共同提供跨主机、可靠的多 agent runtime。

skill 与这两层通过协议组合，不共享内部代码或数据库：skill 维护稳定的文件协议，重档运行时消费这个协议。中小项目只用 skill 就够；大型、跨主机、需要可靠恢复的项目再加 Coordinate + MultiNexus。

## Runtime Engineering

这个项目从两个月前的一个私人仓库开始迭代，直到现在开源。随着完善，它在实现 harness 的过程中自发地触及了后来开源社区兴起的 loop engineering 和 dynamic graph——但这两者不是重点。真正重要的是 **runtime engineering**：如何在长程任务中保持方向不偏离，始终像一个成熟的人类工程团队那样持续推进项目。这既是 harness 的精髓，也是对 harness 的深度挖掘。

## Clean-Room

如果项目受外部产品启发，保持独立设计：可以用通用的产品目标和架构权衡，但不复制外部源码、API 形状、prompt、文档或测试。详细规则见 `skills/long-running-project-harness/references/clean-room-rules.md`。

## 验证

`long-running-project-harness` 的运行层测试（只依赖 Python 标准库）：

```bash
cd skills/long-running-project-harness
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s references/tests -p 'test_*.py'
bash -n references/scripts/harnessctl
```

`validate-checklist.py` 可跨项目直接引用，校验 `mvp-checklist.json` 的结构和语义：

```bash
python3 skills/long-running-project-harness/scripts/validate-checklist.py path/to/mvp-checklist.json
```

`references/scripts/` 是生成项目实例 runtime 的**模板**（含 `{{占位符}}`），不是安装器。

## 许可证

[MIT License](LICENSE)。
