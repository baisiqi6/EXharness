# EXharness

一组面向长期工程项目和多 agent 协作的 agent skill。本仓库是一个 skill 集合（monorepo），包含两个互相独立、各有所长的 skill。

长期项目最常见的失败不是写不出代码，而是**方向感丢失**：换一个 session 就忘了上次做到哪、为什么这么决定、还差什么。本仓库的 skill 围绕这个问题——让项目状态落盘、可恢复、可审计，并让多个 agent 能实际协作推进。

## 包含的 skill

### `long-running-project-harness` — 长期项目协作协议

当用户正在启动或继续一个需要跨 session、跨 agent 保持方向感的长期工程项目时使用这个 skill。它首先是一个项目级协作协议：让项目可以被恢复、审阅、实现、验证和交接；在需要时，也可以为实例仓库补上一层很薄的 runtime harness，让 session 开头变得确定、让状态可以被机器读取。

核心原则很简单：**对话上下文是临时内存，项目文件是长期记忆**。重要决策、已接受范围、明确不做的范围、实现进展和验证结果，都应该落到仓库里的项目文件中，而不是只留在某个还活着的 session 里。

核心能力：

- **项目记忆**：`scope.md`（长期目标 + non-goals）、`architecture.md`、`domain-model.md`、`runbook.md` 等稳定规范，加上 `harness-checklist.json` 的机器可读任务状态（legacy 名 `mvp-checklist.json` 继续兼容）。
- **任务追踪**：每个任务有 `tasks/<item-id>/plan.md` canonical plan 和 task-scoped evidence（bootstrap、review、handoff、verdict、receipt），不会被后续任务覆盖。
- **多 agent 协作协议**：operator / worker / reviewer 显式分工，handoff / review / blocker / closeout packet 让交接可定位、可审计；`events.jsonl` 追加记录关键事件。
- **薄运行层**：`harnessctl` 命令、checklist 校验、状态派生、packet 生成、本地 owner/lease 护栏、确定性 session init——减少人工搬运，但不取代你的判断。

这个 skill 借鉴的是"持久化文件、checklist、progress log、git checkpoint、deterministic session init"这类通用 harness 方法，而不是任何外部框架的代码、prompt、文件结构或命名约定。

它是**协议优先**：先保证文件语义正确，再用薄脚本减少机械工作。它不是自动代理框架，不替你做产品决策；真正的自动协调、跨主机运行状态和可靠消息投递放到独立的 runtime 层（见下文「两个 skill 的关系」中列出的 runtime 实现选项）。

### `invoke-coding-agents` — agent 调用与监督方法

教 agent 如何用 stdio 调起、监督、恢复和验收本地外部 coding agent CLI（Claude Code、Qoder、Grok Build、OMP、OpenCode、Codex 等）。

核心能力：

- **结构化调用**：固定 cwd、权限 allowlist、session 定位、超时、验收——不是发一句自然语言就等结果。
- **provider 路由**：每个 agent CLI 一份 reference，实时核验 binary/model，不硬编码历史路由。
- **监督与验收**：worker 自述、测试通过、reviewer verdict、operator acceptance 是不同证据，不混为一谈。

## 两个 skill 的关系

它们**互相独立，各满足不同需求**，不是依赖关系：

- `invoke-coding-agents` 满足独立需求："调某个 agent 干件事"——不需要项目 harness 协议。
- `long-running-project-harness` 维护的是**协议**（谁负责什么、任务怎么流转、状态怎么落盘、交接怎么留痕），**不规定 runtime 面怎么推进任务**。推进任务时用哪种 runtime 实现，由用户根据场景自选。

`long-running-project-harness` 常见的 runtime 实现从轻到重：

- **当前 agent 自身的 subagent**（最轻量）：如果任务只用当前这一种 agent 就能完成、不跨 agent 生态，直接用 agent 自带的 subagent 能力推进，不需要任何外部 skill 或服务。harness 只负责把状态和交接记录落盘。
- **`invoke-coding-agents` skill**：当任务需要调用当前 agent 之外的 coding agent（Claude Code / Qoder / OMP / Codex 等），用它把外部 agent 拉起来、监督和验收。
- **多 agent 编排 workflow 引擎**：用声明式 workflow 编排多个 agent_call 节点，把多 agent 协作变成可审计、可恢复的 workflow（如 Composia 这类项目）。
- **Coordinate 控制面**：需要 durable job、事件、lease、审查记录和恢复，但由当前 agent、Operator
  或已有 runner 主动执行任务时使用。
- **Coordinate + MultiNexus executor 层**：需要自动调用 vendor agent CLI、恢复 provider session
  或跨宿主机执行时，增加 MultiNexus 的 `agentd + adapters`；不要求启用 Discord/KOOK。
- **完整协作层**（最重）：需要 Discord/KOOK、多 Bot 和可见的多 agent 协作时，再启用
  MultiNexus bridge。

**关键**：harness 不绑定任何一种 runtime 实现。可以只用最轻的 subagent，也可以组合多种。各自独立安装、独立使用。

## 如何选择最小组合

| 需求 | 最小组合 |
|---|---|
| 当前 agent 直接开发，只需要持久计划、SDD/TDD、审查和测试纪律 | `long-running-project-harness` |
| 需要 durable job、任务状态、事件、审查记录和可恢复流程 | EXharness + Coordinate |
| 需要系统自动调用 agent CLI、恢复 provider session 或跨宿主机执行 | EXharness + Coordinate + MultiNexus `agentd/adapters` |
| 需要 Discord/KOOK、多 Bot 和多 agent 可见协作 | 三者完整部署 |

选择原则是“只安装解决当前问题的最小层级”。Coordinate 提供确定性控制面，但不会因为安装完成就
自动获得 Claude Code、Qoder、Grok 等 vendor runtime 的原生 session 控制；这部分由当前 agent、
已有 runner，或 MultiNexus executor 层承担。MultiNexus 也不等于 Discord：bridge 是可选 transport，
`agentd/adapters` 才是托管执行层。

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
  harness-checklist.json  # 机器可读任务状态(todo/doing/done/blocked)；legacy 名 mvp-checklist.json 兼容
  progress.md           # 人类可读进展
  runbook.md            # 操作手册
  events.jsonl          # append-only 关键事件日志
  current/              # 当前任务指针 + handoff/review/blocker packet
  tasks/<item-id>/plan.md   # 每个任务的 canonical plan
```

之后每次开新 session，agent 会先读这些文件恢复上下文，而不是从零开始。

## 和 Coordinate / MultiNexus 的关系

`long-running-project-harness` **可以直接给 agent 在项目里实例化**，不依赖任何外部服务就能用——纯文件协议 + 薄脚本。

上一节列出的 managed runtime 由独立的 **Coordinate**（确定性协调内核）和
**MultiNexus**（agent 执行织物）组合提供。两者可以一起形成跨宿主机、可靠的多 agent runtime；
也可以只使用 Coordinate 管理 durable state，由用户现有 agent/runner 负责执行；或只启用
MultiNexus 的 executor 层而不启用 Discord/KOOK bridge。

关键解耦原则：skill 与这两层**通过协议组合，不共享内部代码或数据库**——skill 维护稳定的文件
协议，managed runtime 消费这个协议。中小项目只用 skill（配合 subagent 或
invoke-coding-agents）就够；只有出现 durable control-plane、托管 executor、跨主机或可见消息总线
需求时，才逐层增加 Coordinate 和 MultiNexus。

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

`validate-checklist.py` 可跨项目直接引用，校验 checklist（`harness-checklist.json` 或 legacy
`mvp-checklist.json`）的结构和语义；顶层脚本是 thin wrapper，唯一 semantic implementation 在
`references/scripts/validate_checklist.py`：

```bash
python3 skills/long-running-project-harness/scripts/validate-checklist.py path/to/checklist.json
```

实例化后的 `harnessctl` 提供受控 checklist mutation（不手改 JSON）：

```bash
harnessctl add-item <id> --title "..." --acceptance "..." [--priority p1] [--plan PATH] [--dependency ID]...
harnessctl update-item <id> [--title ...] [--acceptance ...] [--verification ...] [--add-dependency ...]
harnessctl migrate-checklist   # legacy 名 -> 新名，同目录 rename，不改 bytes
```

规则：checklist 只有唯一 resolver（new-only / legacy-only 都完整可用；none / both fail closed，doctor
只诊断 dual authority）；每个 mutation 都 validate-before/after 并 atomic 写入；`coordinate-managed`
部署下裸 add/update fail closed；Standalone 允许 operator 明确选择的 external absolute plan locator
（operator 选择，不是 containment 安全保证）。

`references/scripts/` 是生成项目实例 runtime 的**模板**（含 `{{占位符}}`），不是安装器。

## 许可证

[MIT License](LICENSE)。
