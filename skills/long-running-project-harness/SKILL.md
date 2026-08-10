---
name: long-running-project-harness
description: Use this skill when the user explicitly wants a long-running project harness, multi-session project memory, clean-room rebuild discipline, project-level planning assets, or coordinated handoff between agents/sessions. It defines a durable project protocol with scope, architecture, MVP checklist, handoff/progress, and runbook files while avoiding accidental copying of external source, API shapes, names, prompts, docs, UI text, tests, or data structures. Do not trigger for ordinary multi-step coding unless the user asks for project harnessing, cross-session continuity, clean-room constraints, or durable planning files.
---

# Long-Running Project Harness

当用户正在启动或继续一个需要跨 session、跨 agent 保持方向感的长期工程项目时，使用这个 skill。它首先是一个项目级协作协议：让项目可以被恢复、审阅、实现、验证和交接；在需要时，也可以为实例仓库补上一层很薄的 runtime harness，让 session 开头变得确定、让状态可以被机器读取。

这个 skill 借鉴的是“持久化文件、checklist、progress log、git checkpoint、deterministic session init”这类通用 harness 方法，而不是任何外部框架的代码、prompt、文件结构或命名约定。除非用户明确要求 vendor 某个框架，否则不要复制外部 harness 的实现细节。

## 核心规则

- 对话上下文是临时内存，项目文件是长期记忆。
- `tasks/<id>/plan.md` 是任务 canonical plan；它位于选定的 task artifact root 中，不要求必然与
  产品代码同仓。`harness-state.json` 是派生镜像，不是手写 source of truth。
- 多 agent 保持 operator/worker/reviewer 职责分离。
- 只工作在 `ordinary` 与 `high-risk` 两种模式；不要创建第三种。
- 不要把这个 skill 做成自动代理框架。运行层只负责减少人工搬运、校验状态、生成 packet、追加事件和保护 owner/lease。

## 部署形态

### Standalone

没有 Coordinate 时使用轻量 file-backed harness。

- `events.jsonl`、lease、packet runtime 只在 high-risk 或显式需要跨 session 自动恢复时启用。
- 本地 `events.jsonl` 是 append-only event log / outbox candidate，不提供发布确认、重试或跨平台幂等保证，也不替代当前 checklist（`harness-checklist.json` 或 legacy `mvp-checklist.json`）的状态。
- ordinary 小重构不触发 packet/lease 全仪式。

### Coordinate-managed

有 Coordinate 控制面时使用。

- 稳定项目规范在 repo harness 文件；Coordinate DB 保存 runtime events、jobs、leases、receipts、deliveries 与 executor/capacity 状态。
- Provider JSONL 是观察证据，不是权威，也不承诺暴露私有思维链。
- 本地 `events.jsonl` 只能是 fallback/export，不能成为第二套运行时账本。
- coding-host/server split 的 mutation 必须区分 `*-files` 文件 authority 与 `*-record` DB authority。

Coordinate-managed 项目可以采用 split storage：产品 repo 保存稳定规范和 Coordinate 当前实际
消费的最小兼容状态；私有 task artifact repo 保存 task-scoped 过程材料（bootstrap、review、handoff、
verdict、receipt、archive index）。

Coordinate-managed 不等于必须安装 MultiNexus：当前 agent、Operator 或已有 runner 能可靠执行和
报告 job 时，只使用 Coordinate。只有需要托管 vendor CLI/session 或跨主机执行时才增加 MultiNexus
`agentd/adapters`；只有需要 Discord/KOOK 可见协作时才启用 bridge。

**区分 policy 与 capability（不要混淆）**：
- **本项目 operator policy**：active canonical plan 留在产品 workspace；私有 repo 只存过程材料，
  Coordinate runtime 不感知它（归档是 skill/operator 层文件操作）。
- **Coordinate runtime capability（技术事实）**：Coordinate 的 minimal file harness
  （`workspace init-harness --mode minimal --root`，默认 mode）技术上**支持 external absolute root**
  （`init_file_harness` 直接 mkdir、不拒绝）。本项目选择**不**利用该 capability 把 active plan 外置。
  只有在出现真实 runtime consumer、并完成 `artifact_root` 完整 contract design（schema/ExecutionContext/
  digest）后，才把外部目录注册为 active task root。在那之前，不要用 minimal 的 external-root 能力
  把 active harness 外置，也不要用 symlink 或放宽 workspace fail-closed guard 绕过。

## 触发条件

只有满足下面至少一条时才触发：

- 用户明确要求建立 harness、长期项目设置、跨 session 记忆、durable planning files 或 handoff protocol。
- 用户说明项目会拆给多个 session、多个 agent，或会分成规划 agent 和实现 agent。
- 用户要求基于外部产品启发做 clean-room / non-copying 重建。
- 仓库里已经存在 harness，用户要求 resume、continue 或 follow it。

不要在这些场景触发：简短解释、小型单文件修改、普通 multi-step coding task、一次性的架构讨论（除非明确要求沉淀为项目资产）。

## 与其他 Skills 的关系

- `planning-with-files` 只负责当前任务或当前 slice 的战术计划。
- `design-patterns` 用于模块边界、扩展点、结构模式选择。
- `programming-principles` 或简洁性原则用于拒绝不服务 MVP 的过度抽象。
- 只有需要当前外部事实时才使用浏览器或搜索类 skill，并把重要发现写回项目文件。

## 工作模式

本 skill 只工作在两种模式下：ordinary 和 high-risk。开始项目级 harnessing 之前，先选择模式。模式决定活跃导航和必须遵守的边界。

### Ordinary 模式

Ordinary 模式用于单一、可在当前 session 内完成的低风险任务。最短闭环为：

```text
task spec -> worker -> independent reviewer -> tests
```

- worker 负责实现，并对正确性、边界和验证负责。
- independent reviewer 负责验证是否满足验收、是否越界、测试是否充分。
- tests 是最终质量护栏。

Ordinary 模式**不强制**：checklist item、owner/session lease、`events.jsonl`、handoff/review/closeout/blocker packet、runtime harness / session-init。

### High-risk 模式

High-risk 模式用于：生产环境、部署、schema 变更、持久 authority、身份/权限/secret、路由/租约/并发、崩溃-重启-恢复、回滚、跨主机真实副作用，或任何失败代价高、可逆性低的任务。它保留完整协议：

```text
plan -> review -> bootstrap -> receipt -> deploy -> recovery
```

包括：scope/architecture、MVP checklist、owner/lease、events、packets、session-init、reviewer verdict、deploy boundary、recovery plan。high-risk 的安全契约（lease、authority、recovery、reviewer 边界）保持原样，不得弱化。

### 模式选择

- 如果任务可在当前 session 内独立完成，且没有生产/删除/部署/跨主机风险，默认使用 ordinary。
- 只要涉及生产环境、部署、删除、数据迁移、schema 变更、持久 authority、身份/权限/secret、路由/租约/并发、崩溃-重启-恢复、回滚、跨主机真实副作用或不可撤销操作，就必须使用 high-risk。
- 不要以“任务有多个步骤”为由把普通任务升级成 high-risk；普通多 agent 协作或 review 不会自动升级。

## 活跃导航规则

活跃导航只指向五个对象：

1. 当前任务规范 / 计划。
2. 当前 handoff（如处于 agent 交接状态）。
3. 最终 reviewer verdict（`approved` / `changes_requested` / `blocked`）。
4. 最终 receipt / closeout。
5. 一个事件索引，用于快速定位历史事件和归档证据。

`current/*` 只是可选指针/恢复缓存，不是 active authority 本身。以下对象必须进入 archive / index：provider JSONL / 多 provider 原始记录、历史轮次或 superseded session 上下文、被取代的 packet/plan/review 版本、临时 scratch / 草稿 / 仅作证据的文件。

## 归档与索引规则

仅保留不可重建且审计/恢复必需的证据；冗余或可再生成证据可按 retention policy 真正删除。archive index 只记录保留证据的元数据和路径，不重复证据全文。新 session 不得把历史 JSONL 或旧 packet 当作当前决策权威。archive 不等于 deletion gate。

## Source Of Truth

项目级稳定状态放在产品 repo 的精简 harness/docs：长期 scope 和 non-goals、architecture、
domain decisions、公开 runbook，以及 Coordinate 当前真实消费的最小 checklist/locator。
task-scoped **过程材料**（bootstrap、review、handoff、verdict、receipt 与 archive index）可以放在
独立私有 task artifact repo（由 skill/operator 消费，Coordinate runtime 不感知）。运行时 lease/event
按 deployment profile 分别进入 Standalone 文件或 Coordinate DB。

**active canonical plan 的位置按部署形态区分（不要混淆 policy 与 capability）**：
- **Coordinate-managed**：
  - **operator policy（本项目采用）**：active canonical plan 留在产品 workspace 内。Coordinate 的
    split-operation `plan_doc` 要求 POSIX workspace-relative、可 hash（见 coordinate-operator skill）。
    外部 task artifact repo 只存该 task 的**过程材料**，不存 active plan 正文，不形成第二份 canonical。
  - **runtime capability（技术事实，非本项目 policy）**：Coordinate 的 minimal file harness
    （`workspace init-harness --mode minimal --root`，默认 mode）技术上**支持 external absolute root**
    （`init_file_harness` 直接 mkdir、不做 containment 拒绝）。本项目选择不利用该 capability 外置 active
    plan；若未来要用，须先完成 `artifact_root` 完整 contract design 并明确边界。不要把"本项目 policy"
    误写成"Coordinate 不支持 external root"。
- **Standalone（无 Coordinate runtime）**：active canonical plan 可以放在选定的 task artifact root
  （co-located 或独立私有 repo）；一个任务只选一个 canonical root。

任务级状态（当前 slice 的 step-by-step plan、临时 findings、当天 tactical progress）放在该形态对应的
active plan 位置。产品 repo 与外部 artifact repo 不得同时维护同一份 active plan 正文。

如果两套系统同时存在，不要把同一个事实重复维护两遍。当前任务完成后，把稳定结果摘要写回 harness 的 `progress.md`，并更新当前 checklist；详细执行轨迹留在 task plan。机器可读状态由脚本从长期文件派生，不要手写维护第三份事实。

推荐 source of truth 划分：

- `harness-checklist.json`（新默认；legacy 名 `mvp-checklist.json` 兼容）: coarse status、priority、owner、lease、workflow、acceptance、verification、artifact path、review decision。
- `tasks/<item-id>/plan.md`: 单个 item 的 canonical plan。
- `progress.md`: 人类可读进展、验证摘要、风险、handoff。
- `events.jsonl`: Standalone 的关键动作日志；Coordinate-managed 中只作 fallback/export。
- `harness-state.json`: 从上述文件派生的机器可读镜像，不手写维护。

### Storage layout

默认 co-located layout 把稳定规范和 task files 放在同一个 repo harness root。若用户有专用私有
harness artifact repo，可以使用 split layout：

```text
product-repo/
  docs/project-harness/        # 稳定规范、公开 runbook、必要兼容状态/locator

$MYHARNESS_ROOT/
  projects/<project_id>/
    project.md                 # repo identity 与边界，不复制产品规范
    current.md                 # 当前任务指针
    tasks/<task_id>/           # task-scoped 过程材料（bootstrap/review/handoff/receipt/archive）；
                               #   Standalone 形态下也放 active canonical plan；
                               #   Coordinate-managed 形态下 active plan 留 workspace，此处只放过程材料
    archive/index.md           # 历史 locator，不复制 raw logs
```

`$MYHARNESS_ROOT` 应通过配置或环境变量发现，不在通用 skill 中硬编码个人绝对路径。该仓库默认
private；raw provider JSONL、session logs、DB backup、大型输出和 secret 不进入普通 Git history。
旧产品 commit 中的历史材料不会因迁移自动消失，默认不为此重写历史。

### Shared artifact repository Git isolation

一个私有 artifact repository 可以承载多个项目，但每个项目必须拥有稳定且互不重叠的
`projects/<project_id>/` 子树。项目任务提交只 stage/commit 自己的子树；提交前检查 staged path，
发现其他项目路径就 fail closed。根目录 README、policy 或索引属于共享维护面，使用单独的
repository-maintenance commit，不夹在某个项目任务提交中。

目录隔离不等于 Git 并发隔离：同一 worktree 的多个 writer 仍共享 index 与 `HEAD`。只有一个
writer 时使用 path-scoped commit 即可；多个项目同时写入时，为每个项目/session 使用独立 branch
和 worktree。不要为没有并发 writer 的场景新增锁服务，也不要在各项目子目录嵌套独立 `.git`。

## 协议层与运行层

默认先建立**协议层**，只有当用户明确需要减少人工切会话、减少人工复制、或让新 session 自动恢复上下文时，再补**运行层**。协议层在 ordinary 模式下可以只保留最小 spec/plan；high-risk 模式建议完整保留。

- 协议层：`scope.md`、`architecture.md`、`domain-model.md`、`harness-checklist.json`（legacy `mvp-checklist.json` 兼容）、
  `progress.md`、`runbook.md`、`tasks/<item-id>/plan.md`，以及 profile 对应的事件索引
- 运行层：`harness-config.json`、`harness-state.json`、`session-init` 命令、packet 生成命令、owner/lease 保护命令、必要时的 `init.sh`

运行层的职责不是取代协议层，而是把协议层里已经落盘的事实，转换成新 session 可以稳定消费的入口。

## 运行层能力边界

当前脚本是 file-backed protocol runtime，不是 coordinator、runner 或可靠消息系统。

脚本能做：读取和校验 harness 文件；领取、续租、释放本地 owner/lease 护栏；生成 handoff/review/blocker/closeout packet；追加本地 `events.jsonl` 事件日志并打印可见 header；从 source-of-truth 文件派生 `harness-state.json`。

脚本不能做：跨主机强一致锁或原子化多 clone 写入；Discord/KOOK 发布确认 / 失败补发 / 消息 id 绑定 / 可靠 outbox retry；GitHub branch protection / PR 创建 / CI 监听 / merge policy；远程 runner 调度 / job retry / 超时恢复 / agent 进程管理。

如果项目需要这些能力，使用 Coordinate-managed 部署形态；不要把职责塞进 skill 脚本。

## 协议与 runtime 实现

本 skill 维护的是**协议**：谁负责什么、任务怎么流转、状态怎么落盘、交接怎么留痕。协议本身不规定 runtime 面怎么推进任务——那是 agent 执行层的事，由用户根据场景自选。常见的 runtime 实现从轻到重：

- **当前 agent 自身的 subagent**（最轻量）：很多 agent client 自带 subagent/agent team 能力。如果任务只用当前这一种 agent 就能完成、不需要跨 agent 生态，直接用 agent 自身的 subagent 推进即可，不需要任何外部 skill 或服务。本 harness 只负责把项目状态、任务分工和交接记录落盘。
- **`invoke-coding-agents` skill**（结合其他 agent 的强项）：当任务需要调用当前 agent 之外的 coding agent（Claude Code / Qoder / OMP / Codex 等），用它把外部 agent 进程拉起来、监督和验收。它和本 skill 是平级的独立 skill，只在需要跨 agent 协作时配合使用。
- **多 agent 编排 workflow 引擎**：用声明式 workflow 编排多个 agent_call 节点（如 Composia 这类项目，把多 agent 协作变成可审计、可恢复的 workflow）。
- **Coordinate 控制面**：需要 durable job、event、lease、receipt 和恢复，但任务由当前 agent、
  Operator 或已有 runner 主动执行时使用。
- **Coordinate + MultiNexus executor 层**：需要自动调用 vendor agent CLI、恢复 provider session
  或跨宿主机执行时，增加 `agentd/adapters`；不要求启用消息平台。
- **完整 MultiNexus bridge**（最重）：只有需要 Discord/KOOK、多 Bot 和可见协作时才启用。

**关键**：本 skill 不绑定任何一种 runtime 实现。用户可以只用最轻的 subagent，也可以组合多种。选择依据是任务复杂度、是否跨 agent 生态、是否跨主机——而不是本 skill 的要求。本 skill 的职责始终只是：让协议事实落盘、可恢复、可审计。

### 递归委派与局部 Operator

主 Operator 可以把边界清晰的 dogfood 小修、ordinary 小任务或主线之外的独立任务线委派给
subagent，让它在该范围内充当局部 Operator。局部 Operator 可以直接完成很小的修改，也可以按需调用
worker/reviewer，并在交付前先核对实现、测试和任务线状态；是否增加独立 reviewer 由风险、改动范围和
可逆性决定，不把每个小任务机械升级成完整仪式。

局部 Operator 是一次有界委派，不是新的持久角色或第三套 workflow。它只能继承明确授予的任务范围，
不能自行扩大 merge、deploy、生产 mutation 或其他 authority；每条并行任务线继续使用独立的
Issue/item、session、branch/worktree 和持久 ID。主 Operator 最终核验实际 diff、tests、reviewer verdict、
Git/runtime 状态与 authority 边界，而不是只接受下级摘要。递归层级只有在能减少主线阻塞或提高交叉验证
质量时才增加；一个 agent 直接完成更简单时就不要委派。

## Mirror Rule

- global skill 维护可泛化的项目协议和边界。
- 具体产品代码、CLI、schema、生产边界以 repo 代码与 runbook 为准。
- 只有可泛化的经验（流程、边界、安全契约）才回流 global skill。
- 实例可以增补 repo-specific 命令和路径，但不要背离 skill 的字段语义和流程语义。
- 如果 skill 与实例冲突，以用户当前明确要求为准；冲突解除后再重新对齐。

## 标准 Harness 文件

创建文件前，先检查产品 repo 是否已有稳定文档约定，并检查是否配置独立 task artifact repo。
稳定产品规范优先复用 repo 内已有 `docs/`、`plans/`、`specs/` 或 `adr/`；task-scoped 材料写入
唯一选定的 artifact root。没有 split-storage 决策时继续使用 co-located layout，不自行创建第二套。

Co-located layout 示例：

```text
docs/project-harness/
  scope.md
  architecture.md
  domain-model.md
  harness-checklist.json
  progress.md
  runbook.md
  harness-config.json
  harness-state.json
  events.jsonl
  current/
    task_plan.md
    handoff-packet.md
    blocker.md
    review.md
    review-packet.md
    blocker-packet.md
    closeout-packet.md
  tasks/
    mvp-001/
      plan.md
```

这些文件要保持精简。`harness-state.json` 推荐由脚本生成，不建议手写维护。`events.jsonl` 只追加关键事件，事件应引用 artifact path，不把长计划或长审查全文复制进去。

split layout 中不要机械复制上述整棵目录：repo-local 只留稳定规范和现有 runtime consumer 必需
文件；task-scoped 过程材料（review、receipt、bootstrap、handoff、archive）与 task-scoped `current/`
进入外部 artifact root。**active canonical plan 是否随之外置取决于形态**：Standalone 可以把
`tasks/<id>/plan.md` 一起外置；Coordinate-managed 的 active plan 仍留产品 workspace（`plan_doc`
要求 workspace-relative），外部 root 只存过程材料。切换前先审计脚本、checklist、handoff renderer
与 coordinator 是否要求 workspace-relative path。

## 机器可读状态

如果项目需要频繁切 session / agent，推荐在 harness root 下增加 `harness-state.json`。它是协议层的派生镜像，不是新的手写 source of truth。推荐至少包含：`project`、`harness_root`、`generated_at`、`current_status`、`current_item`、`checklist_summary`、`paths`、`commands`、`workflow_summary`、`recent_events`、`open_risks`。

模板见 [harness-state-template.json](references/harness-state-template.json)。推荐由 repo-local 脚本刷新，session 开头先刷新一次，把它当作“给新 agent 的最快入口”，而不是唯一入口。

## Harness Config

如果实例项目需要 runtime harness，推荐增加 `harness-config.json`。它保存 repo-specific 配置，而不是写死在脚本里。推荐字段：

- `commands`: `typecheck`、`test`、`build` 或其他验证命令；不存在时脚本可尝试从 `package.json` 推断。
- `runtime.session_init_commands`: session-init 默认运行哪些 command key。
- `runtime.lease_ttl_minutes`: owner lease 默认过期时间。
- `git.base_branch`: 多主机协作的默认 base branch。
- `git.branch_namespace`: agent 分支命名模板，例如 `agent/{owner}/{item_id}`。
- `message_bus.event_log`: 本地 `events.jsonl` 路径。Standalone 下它不是可靠 bus outbox；Coordinate-managed 下它只能是 fallback/export。

模板见 [harness-config-template.json](references/harness-config-template.json)。不要在通用模板里硬编码 `pnpm`。

## 确定性 Session Init

如果用户想减少人工衔接，推荐为实例仓库补一个统一入口，例如：

```bash
scripts/harness/harnessctl session-init
```

它推荐至少做：确认当前工作目录和 harness root；刷新 `harness-state.json`；读取当前 checklist、`progress.md`、`current/task_plan.md` 的最小摘要；执行 checklist 校验；运行 `harness-config.json` 中配置的最小回归检查；如果发现环境已坏，优先暴露这个事实，而不是直接开始新功能。

注意：这是 runtime harness，不是 orchestration system；作用是让新 session 有确定性开头，不是自动替用户做所有决策。脚本可以提供本地 lease 护栏，但跨主机的全局互斥仍应由 coordinator 或 Git/GitHub workflow 执行。

## 运行层脚本模板

当用户需要为实例仓库补运行层时，可以从 skill 的脚本模板生成实例脚本。模板在 [references/scripts/](references/scripts/) 下，采用完形填空式设计：固定逻辑写死，项目特定部分用 `{{占位符}}` 标记。

核心占位符：`{{HARNESS_ROOT}}`、`{{PROJECT_ROOT_DEPTH}}`、`{{SCRIPTS_DIR}}`、`{{PROJECT_NAME}}`。

实例化步骤：确定 harness root 位置；确定脚本放置深度；复制模板文件；替换占位符；复制 `harness-config-template.json` 并填入项目实际值；运行 `validate_checklist.py` 确认 harness 健康。

可用模板：`harnessctl`、`harness_common.py`、`build_harness_state.py`、`session_init.py`、`activate_item.py`、`workflow_transition.py`、`sync_current_from_item.py`、`checklist_items.py`、`prepare_handoff_packet.py`、`prepare_review_packet.py`、`prepare_blocker_packet.py`、`prepare_closeout_packet.py`、`validate_checklist.py`。

`validate_checklist.py` 完全通用，同时存在于 skill 目录 `scripts/validate-checklist.py` 与模板目录 `references/scripts/validate_checklist.py`。

```bash
python3 "$CLAUDE_SKILL_DIR/scripts/validate-checklist.py" path/to/checklist.json
```

## Coding Agent Session Protocol

当 coding agent 开始一个新 session 时，推荐使用确定性 session prompt，让每个 session 有固定的开头步骤。模板见 [coding-prompt.md](references/prompts/coding-prompt.md)。

它把整个 session 分为三层：

- **读层**（Step 1-6）：pwd → session-init → 读 state → 读边界文件 → 读 progress → 读 canonical plan
- **跑层**：包含在 session-init 中（typecheck + test）
- **写层**（Step 7-12）：选 item → 确认 plan → 实现 → 验证 → 持久化 → 汇报

核心原则：session-init 失败时，先修 bug，再实现新功能；canonical plan 有“待补充”占位符时，先补全再编码；session 结束前必须更新 progress.md + 当前 checklist + sync + validate。

## Multi-Agent Role Protocol

多 agent 项目必须显式分工：

- Operator：读取 harness 状态和 profile 对应的 event store，决定下一步点名哪个
  agent；负责发起 assignment、校验状态推进、记录高层决策，并把关键事件发到
  Discord/KOOK。不替 agent accept，也不替 reviewer 做审查判断。
- Architect：把产品目标拆成可由单个 coding session 完成的 item；维护 architecture、domain model、task plan 和边界。
- Coding agent：消费已分配或已激活的 item；由目标 agent 发起 `accept` 或 `decline`；在 scope 内实现、验证、写 handoff；默认不自行扩大范围，不直接 mark done。
- Reviewer：审查 plan/result 是否满足 acceptance、是否越界、验证是否充分；由 reviewer 发起 `review-result approved|changes_requested|blocked`。
- Human：决定产品方向、范围扩大和高风险 authority；可以给出有界持久授权。
  Operator 只能在该授权覆盖的目标、范围和时限内执行，且不能省略安全 gate。

## Event And Packet Protocol

high-risk 模式或显式启用 runtime workflow 时，关键动作必须同时满足：

1. 更新对应的 harness 状态或 packet。
2. 写入 deployment profile 对应的权威 event store。
3. 输出一行可转发到 Discord/KOOK 的事件 header。

ordinary 模式不强制此三联动作。

推荐可见事件类型：

```text
[ASSIGN]  task=<id> actor=<operator> target=<agent> status=assigned
[ACCEPT]  task=<id> actor=<agent> status=running
[RESULT]  task=<id> actor=<agent> target=<reviewer> status=closeout_requested
[REVIEW]  task=<id> actor=<reviewer> status=approved|changes_requested|blocked
[BLOCKER] task=<id> actor=<agent> target=human status=blocked
[CLOSE]   task=<id> actor=<operator> status=done
```

事件落点由 deployment profile 决定。Standalone 的 `events.jsonl` 是 append-only
event log / outbox candidate，当前脚本只写 `publish_status=local_only`；
Coordinate-managed 的权威事件写入 Coordinate DB，本地 `events.jsonl` 只是
fallback/export。事件使用稳定字段并只保存摘要与 artifact paths，不复制长计划或
长审查全文。

Packet 状态机：

- `handoff-packet.md`: 用于转交给另一个 agent；生成时释放旧 owner/lease，记录 `workflow.handoff_target`。
- `review-packet.md`: 用于计划或结果审查，请求 reviewer 输出结构化 decision。
- `blocker-packet.md`: 表示 item 进入 `blocked`；生成时释放 owner/lease，记录 `workflow.unblock_owner`，必须通过 `unblock` 或明确 override 解阻。
- `closeout-packet.md`: 只表示 ready for closeout review，不允许直接把 item 标为 `done`。

如果目标 agent 不能接手，应运行 `decline <item-id> <actor>`，而不是沉默丢弃 handoff。长任务超过 TTL 时，当前 owner/session 应运行 `renew-lease <item-id> <owner> <session-id>`，避免其他 agent 误判 lease 过期。

只有 reviewer 通过 `review-result <item-id> <reviewer> approved` 写入 closeout 审查结论后，operator/human 才能运行 `mark-done`。`mark-done` 会释放 owner/lease 并清理 stale current pointer。`--force --reason` 只用于明确 human override，并会写入 event metadata。

## High-risk 生命周期阶段

以下阶段属于 high-risk 模式。ordinary 模式只保留最小 spec → worker → reviewer → tests 闭环，不强制以下阶段。

### Init Only

用户想先建立规划资产，还不希望马上实现时使用：澄清 product goal 和 non-goals；判断是否适用 clean-room 规则；检查现有文档约定并选择 harness root；创建或更新标准 harness 文件；定义带客观验收标准的 MVP checklist；除非用户明确要求继续，否则在总结下一个推荐 implementation slice 后停止。

### Init And First Slice

用户希望建立 harness 后立刻实现第一个最小切片时使用：完成 Init Only 的步骤；
只选择一个 MVP checklist item 或一个 vertical slice；Standalone 通过
`harnessctl`、Coordinate-managed 通过 Coordinate operator/CLI 领取 owner/lease
并推进 workflow；实现最小可用切片；运行与风险相称的验证；更新规范状态；如果完成，
走 reviewer approval 与 profile 对应的 mark-done；否则用简短 handoff 结束。

### Resume

已有 harness，或用户要求继续之前的工作时使用：读取 `progress.md`、当前 checklist 和相关 plan/architecture 文件；检查 `git status`，不要覆盖他人修改；判断是否已有 item 处于 `doing`；如果另一个 owner/session 的 lease 仍 active，选择不冲突的 item 或等待 operator/human，不要静默接手；找到用户指定的 slice 或最高优先级的未阻塞 item；实现前先通过脚本标记选中的 item 并领取 lease；实现最小可用切片；结束前更新 progress 和 checklist。

## Clean-Room 协议

如果项目受外部产品或代码库启发，必须保持独立设计。

允许：抽象后的产品目标；用户可见的能力类别；通用 UX 启发；公开、通用的架构权衡；独立设计的接口和数据模型。

除非用户明确拥有源项目并要求复用，否则不允许：源码或近似重写；注释、文档、测试、prompts 或 UI copy；API shapes、JSON node structures、database schemas 或 variable names；换语言但保持同一套实现的 port。

不确定时，先把外部启发转写成独立 requirement，写入 `scope.md`，再从第一性原则设计新的模型。参考 [clean-room-rules.md](references/clean-room-rules.md)。

## MVP Checklist 规则

使用 JSON 维护 checklist，因为它容易 diff，也容易被 agent 稳定更新。

**文件名权威规则**：新项目使用 `harness-checklist.json`；`mvp-checklist.json` 是 legacy 文件名，
继续完整可用。runtime 只有唯一 resolver 决定当前 checklist：只有新名/只有旧名都正常读写；
两者都没有或同时存在时 read/mutation fail closed（doctor 只诊断 dual authority，不宣布哪份
active）。从旧名切换到新名运行 `harnessctl migrate-checklist`（同目录 rename，不改 bytes，不提交 Git）。

**重要节点登记规则**：operator 需要新增或调整重要节点时，用 `harnessctl` 落盘，不要手改 JSON：

- `harnessctl add-item <id> --title <text> --acceptance <text> [--priority p0|p1|p2] [--plan <path>] [--dependency <id>]... [--handoff <text>]`：只创建 `todo` 节点，不创建 plan 文件、不自动 start、不写 lease/review/workflow 占位对象。`--plan` 文件必须已存在。
- `harnessctl update-item <id> [--title] [--acceptance] [--priority] [--plan] [--verification] [--handoff] [--add-dependency] [--remove-dependency]`：不能改 `status`/`owner`/`selected_in_session`/`lease`/`workflow.status`/`review.decision`；未触碰字段与未知兼容字段原样保留。
- 每个 mutation 都先校验 current、内存变更、再校验 candidate、atomic 写入；commit 前失败原 bytes 不变。
- `deployment_profile=coordinate-managed` 下裸 add/update fail closed（走 Coordinate 入口）；`migrate-checklist` 需要显式 `--ack-managed-profile`（只是防误操作确认，不是 authority token）。

每个 item 至少包含：`id`、`title`、`status`（todo/doing/done/blocked）、`priority`（p0/p1/p2）、`owner`、`selected_in_session`、`updated_at`、`dependencies`、`blocked_by`、`blocked_reason`、`acceptance`、`verification`、`handoff`。

多 agent 兼容扩展字段（推荐）：`workflow`（assigned/running/closeout_requested/changes_requested/closed）、`lease`（acquired_at/expires_at/ttl_minutes）、`artifacts`（plan/handoff_packet/review_packet/closeout_packet/branch/pr）、`review`（decision 取 approved/changes_requested/blocked/null）。

Branch 字段协议：`workflow.branch` 是工作分支，通常由 `git.branch_namespace` 生成；`artifacts.branch` 与其保持一致；`artifacts.pr` 是 PR 链接；远程 agent 不得改非自己 namespace 下的 branch，除非 human 明确授权。

### GitHub-backed 团队协作 profile

团队协作不要在 harness 内再造 Issue registry、ID allocator、phase lock 或 distributed lock。对使用
GitHub Issues/PRs 的单仓库项目，直接复用以下边界：

- **GitHub Issue**：需求、repo-scoped identity、认领状态和人类可见讨论。Issue `#123` 对应
  checklist item ID `issue-123`；ID 在任务生命周期内不改号。
- **assignee / 约定 label**：cooperative claim。开工前检查 Issue open、无人认领且没有 active
  implementation PR，认领后再读一次远端状态；这降低重复劳动，但不是数据库级 hard lock。
- **branch/worktree**：每个 writer 的文件和 Git 隔离。分支中的 checklist 是 merge candidate；
  `main` 中的 checklist 是已经通过 PR 接受的 canonical snapshot。
- **实时全局视图**：查看 open/assigned Issue 与 active PR。未合并分支的执行状态不提前写进 `main`
  checklist，也不要求 checklist 承担跨 clone 的 live query。
- **EXharness**：item 保存 coarse execution state，`tasks/issue-123/plan.md` 保存具体执行计划，
  review/verification/receipt 保存交付证据；不要把这些正文复制进 Issue。
- **PR**：代码与 checklist diff、CI、review、冲突解决和 merge gate；正文使用 `Closes #123` 或项目
  等价约定建立关闭关系。

最小流程：

1. 选择 open、无人认领且没有 active implementation PR 的 Issue；通过 assignee/label 认领。
2. Standalone 使用 `harnessctl add-item issue-123 ...` 登记重要或跨 session 节点；Coordinate-managed
   仍走 Coordinate combined-create/mirror 入口，禁止裸 add/update；普通小任务仍不强制登记。
3. 创建包含 `issue-123` 的独立 branch/worktree，激活 item，维护唯一 canonical plan。
4. worker 实现，独立 reviewer 审查，运行与风险相称的 tests。
5. 创建关联 Issue 的 PR；对 merge candidate 运行 checklist validator 并解决冲突，合并后由项目流程
   关闭 item/Issue。

冲突规则只保护真实 authority 冲突：两个不同 Issue（例如 `issue-123`、`issue-124`）即使处于同一
phase，也应保留为两个节点并在 PR 中合并。Git 文本合并未报冲突不等于安全：validator 仍须检查
duplicate ID；同一 ID 若 title、acceptance 或计划语义不同，必须 fail closed，由 reviewer 回到 Issue
核对，不能静默覆盖、重编号或创建第二份 checklist。若项目横跨
多个 GitHub repository，Issue number 不再全局唯一，应由上层项目明确 repo namespace；在出现该真实
需求前，不向通用 schema 增加字段。

这个 profile 不让本地 runtime 获得 GitHub API 能力。查询、认领、创建 PR 与 branch protection 仍由
人类、`gh`、Coordinate 或其他既有工具完成；EXharness 只规定可恢复的协作协议。

Canonical plan locator：一个 item 只有一个语义答案（`plan_path` 或 `artifacts.plan` 之一，或两者标准化后相同）；冲突时 fail closed，不静默选择。没有 locator 时 activation 可以 scaffold 默认
`tasks/<id>/plan.md`；已有 locator 但文件缺失时 fail closed，不偷偷重建。Standalone 允许 operator
在 checklist 中明确选择 external absolute plan locator（repo-local 协议 + 外部 task artifact root 的
split layout）；这是 operator 选择，只做 lexical/regular-file 校验，不构成 containment 安全保证。

除非验证结果已经记录在 `progress.md`，否则不要把 item 标成 `done`。
除非用户明确要求 override，否则不要启动 dependencies 未完成的 item。
除非 reviewer 已 approved，coding agent 不应自行把 item 标为 `done`；使用 `closeout` + `review-result` + `mark-done`。
如果 item 被其他 owner 的 active lease 占用，不要覆盖；选择其他 item，等待 operator，或使用带 reason 的 human override。

模板见 [planning-files-template.md](references/planning-files-template.md)。

## Checklist 校验

创建或修改 checklist（`harness-checklist.json` 或 legacy `mvp-checklist.json`）后，优先运行校验脚本：

```bash
python3 "$CLAUDE_SKILL_DIR/scripts/validate-checklist.py" path/to/checklist.json
# 实例化后：不传路径时走 resolver 决定当前 checklist
scripts/harness/harnessctl validate
```

校验只有一份 semantic implementation（`references/scripts/validate_checklist.py`）；顶层
`scripts/validate-checklist.py` 只是 thin wrapper，两者对相同输入保持 stdout/stderr/exit code parity。
脚本只读取和校验 JSON，不会修改文件。它检查必填字段、顶层字段类型、`status`、`priority`、`doing`
ownership、`done` verification，以及 `dependencies` / `blocked_by` 引用是否存在。

## 任务级材料

high-risk 或显式需要跨 session 自动恢复时，可以在唯一选定的 task artifact root 下增加：

```text
current/
  task_plan.md
  handoff-packet.md
  blocker.md
  review.md
  review-packet.md
  blocker-packet.md
  closeout-packet.md
tasks/
  mvp-001/
    plan.md
```

- `tasks/<item-id>/plan.md`: 任务计划的规范正文落点和历史快照。
- `current/task_plan.md`: 当前激活任务计划的指针或摘要，不再作为唯一正文文件。
- `current/handoff-packet.md`: 转交给另一个 agent 的最小上下文。
- `current/blocker.md`: 当前卡住的问题、已尝试方案和暂停理由。
- `current/review.md`: 当前计划或阶段结果的边界审查结论。
- `current/*-packet.md`: 可选的恢复缓存。生成 packet 时，Standalone 将摘要追加到
  本地事件日志；Coordinate-managed 写入 Coordinate DB 的权威事件，本地日志只作
  fallback/export。

active canonical plan 的写位置按部署形态区分：
- **Standalone**：把每个 item 的计划正文写进选定的 `<artifact-root>/tasks/<item-id>/plan.md`
  （co-located 或独立私有 repo 均可），一个 item 只选一个 artifact root。
- **Coordinate-managed**：active plan 正文留在产品 workspace 内（split-operation `plan_doc` 要求
  workspace-relative）；`<artifact-root>/tasks/<item-id>/` 只放该 task 的过程材料，不放 active plan 正文。
`<artifact-root>/current/task_plan.md` 只负责告诉下一个 session“现在正在执行哪一个计划文件”，是指针/恢复缓存。
split layout 尚未被当前 coordinator 原生支持时，保留 repo-local 兼容 locator，不制造两份 plan 正文。

模板见 [task-plan-template.md](references/task-plan-template.md)、[blocker-template.md](references/blocker-template.md)、[review-template.md](references/review-template.md)。

## 任务开始规则

high-risk 或显式启用 runtime workflow 时，checklist item 从 `todo` 进入 `doing`
应遵守：

1. 先检查 dependencies、blocked 状态、owner 和 active lease。
2. 领取 owner/session lease；如果覆盖别人的 active lease，必须使用 `--force --reason` 并写入事件。
3. 创建或更新 `tasks/<item-id>/plan.md`。
4. 再更新 `current/task_plan.md`，让它指向当前激活的 item 计划文件。
5. 在计划正文里明确当前 item、目标、范围边界、非目标、验证方式和退出条件。
6. 追加 `[ACCEPT]` 事件后再开始实现。

如果已有任务计划但范围发生变化，必须先更新计划，再继续执行。

## 越界审查规则

任务计划落地后，先做一次轻量边界审查。至少对照：当前 checklist item 的 `acceptance`、`scope.md` 的 non-goals、`architecture.md` 的模块边界、`domain-model.md` 中已拍板的关键决策。如果计划涉及别的 checklist item，必须显式写出来，并说明为什么不能后移。

## 卡住暂停规则

如果连续 3 次尝试同一问题仍未推进：

1. 停止继续试错。
2. 将问题、已尝试方案、失败信号、怀疑原因、建议下一步写入 `current/blocker.md`。
3. 运行 `harnessctl blocker <item-id> --unblock-owner <human|architect|...>` 生成 blocker packet、把 item 标为 `blocked`、释放 owner/lease，并追加 `[BLOCKER]` 事件。
4. 更新 `progress.md` 和当前 checklist item 的 `handoff`。
5. 等待 unblock owner 决策。
6. 决策完成后运行 `harnessctl unblock <item-id> <actor> --decision "..."`，再由新的 owner `accept` 或重新 `assign`。

不要在明显卡住时一味继续“多试几次”。

## 实现纪律

- 优先完成一个 vertical slice，而不是铺很多半成品层。
- core model 要小而明确。
- 只有 MVP 已经有真实调用方时，才添加 extension point。
- 如果同时使用 `planning-with-files`，只为当前选中的 slice 创建战术计划，不要重新为整个项目建一套计划。
- 实例仓库的产品代码、CLI、schema 和生产 runbook 是具体事实；只有确认可泛化的
  协议语义才回流 global skill，不执行机械的“skill 先于实例”镜像顺序。
- `harness-state.json` 应由脚本派生，不要手写维护成第三份 source of truth。
- 只有用户要求 git workflow 时，才主动 commit 或 checkpoint。
- 不要静默覆盖用户或其他 agent 的修改。
- 如果测试不能运行，记录原因和未验证风险。
- 多主机 agent 默认各自使用独立 branch 或 worktree。
- 共享 artifact repository 中，project-scoped commit 不得包含其他 `projects/<project_id>/` 子树；
  并发 writer 使用独立 worktree，串行 writer 不额外引入锁系统。
- Reviewer 默认只审查 artifact、diff、PR 和 packet；不要让 reviewer 自动获得 merge/delete/deploy 权限。
- 脚本 lease 是本地护栏，不是跨主机强一致锁；跨主机全局互斥应由 coordinator、GitHub branch/PR 和 human review 共同保障。

## 结束汇报

每个 session 结束时简短汇报：改了什么、验证了什么、哪些 checklist item 状态变化了、是否有风险/阻塞/推荐的下一个 slice。详细信息写在项目文件里。
