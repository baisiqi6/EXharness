# 运行层设置

仅在初始化或维护可选 runtime harness 时读取；ordinary 不因此强制使用 runtime。存储位置见 [storage-and-recovery.md](storage-and-recovery.md)，执行规则见 [workflow.md](workflow.md)。

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

## 机器可读状态

如果项目需要频繁切 session / agent，推荐在 harness root 下增加 `harness-state.json`。它是协议层的派生镜像，不是新的手写 source of truth。推荐至少包含：`project`、`harness_root`、`generated_at`、`current_status`、`current_item`、`checklist_summary`、`paths`、`commands`、`workflow_summary`、`recent_events`、`open_risks`。

模板见 [harness-state-template.json](harness-state-template.json)。推荐由 repo-local 脚本刷新，session 开头先刷新一次，把它当作“给新 agent 的最快入口”，而不是唯一入口。

## Harness Config

如果实例项目需要 runtime harness，推荐增加 `harness-config.json`。它保存 repo-specific 配置，而不是写死在脚本里。推荐字段：

- `commands`: `typecheck`、`test`、`build` 或其他验证命令；不存在时脚本可尝试从 `package.json` 推断。
- `runtime.session_init_commands`: session-init 默认运行哪些 command key。
- `runtime.lease_ttl_minutes`: owner lease 默认过期时间。
- `git.base_branch`: 多主机协作的默认 base branch。
- `git.branch_namespace`: agent 分支命名模板，例如 `agent/{owner}/{item_id}`。
- `message_bus.event_log`: 本地 `events.jsonl` 路径。Standalone 下它不是可靠 bus outbox；Coordinate-managed 下它只能是 fallback/export。

模板见 [harness-config-template.json](harness-config-template.json)。不要在通用模板里硬编码 `pnpm`。

## 确定性 Session Init

如果用户想减少人工衔接，推荐为实例仓库补一个统一入口，例如：

```bash
scripts/harness/harnessctl session-init
```

它推荐至少做：确认当前工作目录和 harness root；刷新 `harness-state.json`；读取当前 checklist、`progress.md`、`current/task_plan.md` 的最小摘要；执行 checklist 校验；运行 `harness-config.json` 中配置的最小回归检查；如果发现环境已坏，优先暴露这个事实，而不是直接开始新功能。

session-init 还会做一次只读的 `git worktree list --porcelain -z` 发现（issue #12）：当 current item 有 `workflow.branch` 时，从 Git 已有事实中定位该 branch 的活跃 worktree —— 唯一可用匹配输出 `Active item worktree: <path>`（非当前 worktree 时附 switch recommendation）；0 匹配或多匹配输出明确 WARNING，绝不猜测路径、绝不创建/切换 worktree；prunable 或 path 已不存在的 entry 永远不会被称为 active，locked entry 会标注但仍可定位。Git 不可用（非 Git 项目、git 缺失、非零退出或发现异常）时保持原有行为，发现结果只作为 ephemeral 诊断输出，不写入 state，也不改变 session-init 的失败语义。

注意：这是 runtime harness，不是 orchestration system；作用是让新 session 有确定性开头，不是自动替用户做所有决策。脚本可以提供本地 lease 护栏，但跨主机的全局互斥仍应由 coordinator 或 Git/GitHub workflow 执行。

## 运行层脚本模板

当用户需要为实例仓库补运行层时，可以从 skill 的脚本模板生成实例脚本。模板在 [references/scripts/](scripts/) 下，采用完形填空式设计：固定逻辑写死，项目特定部分用 `{{占位符}}` 标记。

核心占位符：`{{HARNESS_ROOT}}`、`{{PROJECT_ROOT_DEPTH}}`、`{{SCRIPTS_DIR}}`、`{{PROJECT_NAME}}`。

实例化步骤：确定 harness root 位置；确定脚本放置深度；复制模板文件；替换占位符；复制 `harness-config-template.json` 并填入项目实际值；运行 `validate_checklist.py` 确认 harness 健康。

可用模板：`harnessctl`、`harness_common.py`、`build_harness_state.py`、`session_init.py`、`activate_item.py`、`workflow_transition.py`、`sync_current_from_item.py`、`checklist_items.py`、`prepare_handoff_packet.py`、`prepare_review_packet.py`、`prepare_blocker_packet.py`、`prepare_closeout_packet.py`、`validate_checklist.py`。

`validate_checklist.py` 完全通用，同时存在于 skill 目录 `scripts/validate-checklist.py` 与模板目录 `references/scripts/validate_checklist.py`。

```bash
python3 "$CLAUDE_SKILL_DIR/scripts/validate-checklist.py" path/to/checklist.json
```
