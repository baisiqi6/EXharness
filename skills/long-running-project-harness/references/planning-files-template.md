# Planning Files Template

这些模板是起点，不是固定框架。使用时保持精简，并根据项目实际情况调整。

## File Ownership

稳定产品规范是项目级 source of truth；task-scoped 文件属于唯一选定的 artifact root。如果
`planning-with-files` 同时启用，它只负责当前任务的战术计划；稳定结论和完成摘要要回写产品 repo，
过程全文不复制回去。

以下结构是 co-located layout 示例。split layout 把 task-scoped 过程材料（review、receipt、
bootstrap、handoff、archive）放到 `$MYHARNESS_ROOT/projects/<project_id>/`，产品 repo 只保留稳定规范
及当前工具真实消费的最小状态/locator。**active canonical plan 是否随之外置取决于形态**：
Standalone 可以把 active plan 一起放到 `$MYHARNESS_ROOT`；Coordinate-managed 的 active plan 仍留
产品 workspace（`plan_doc` 要求 workspace-relative），`$MYHARNESS_ROOT` 只存过程材料。

推荐补充的任务级结构：

```text
current/
  task_plan.md
  blocker.md
  review.md
harness-config.json
harness-state.json
events.jsonl
tasks/
  mvp-001/
    plan.md
```

其中：

- `tasks/<item-id>/plan.md` 是任务计划正文的规范落点
- `current/task_plan.md` 只保留当前激活计划的指针或摘要
- `harness-state.json` 是从长期文件派生出来的机器可读镜像，不是新的手写 source of truth
- `events.jsonl` 是 append-only 关键事件日志 / outbox candidate，供 coordinator 和 Discord/KOOK adapter 读取；当前脚本不提供发布确认或 retry
- `harness-config.json` 保存 repo-specific commands、lease TTL、branch namespace 和 event log 路径

## scope.md

```markdown
# Scope

## Goal

用 3-6 句话描述产品或工程目标。

## Non-Goals

- 当前明确不做的事情。
- 当前不依赖的系统。
- 不允许从外部项目复制的行为或实现细节。

## Constraints

- Runtime、language、deployment、budget、security 或 clean-room 约束。

## Source Of Truth

- Harness root:
- Tactical planning tool, if any:
- Files that should not be duplicated:

## MVP

- 能证明架构成立的最小 user-visible 或 developer-visible 能力集合。
```

## architecture.md

```markdown
# Architecture

## Modules

- `module-a`: 职责。
- `module-b`: 职责。

## Boundaries

- 每个模块可以 import 什么。
- 每个模块不应该知道什么。

## Execution Model

描述 request、job、run 或 event 的生命周期。

## Storage

描述需要持久化的实体，以及为什么需要。

## Extension Points

只列 MVP 需要，或下一步明确需要的 extension points。
```

## domain-model.md

```markdown
# Domain Model

## Entities

- `Entity`: 职责和核心字段。

## State Machines

- `Status`: 允许的值和状态流转。

## Interfaces

- `Gateway`: 它抽象什么，以及不应该泄漏什么。

## Open Questions

- 现在不应该猜、需要后续确认的决策。
```

## mvp-checklist.json

```json
{
  "project": "project-name",
  "harness_root": "docs/project-harness",
  "updated_at": "YYYY-MM-DD",
  "items": [
    {
      "id": "mvp-001",
      "title": "Define core domain model",
      "status": "todo",
      "priority": "p0",
      "owner": null,
      "selected_in_session": null,
      "updated_at": "YYYY-MM-DD",
      "dependencies": [],
      "blocked_by": [],
      "blocked_reason": null,
      "acceptance": "Core entities and states are documented and reflected in code types.",
      "verification": "Typecheck passes and domain-model.md matches exported types.",
      "handoff": "Start by comparing the documented model to exported core types.",
      "workflow": {
        "status": "todo",
        "updated_at": "YYYY-MM-DD"
      },
      "lease": null,
      "artifacts": {},
      "review": {
        "decision": null
      }
    }
  ]
}
```

允许的 `status`：

- `todo`
- `doing`
- `done`
- `blocked`

`priority` 约定：

- `p0`: MVP 必需。
- `p1`: 重要的下一阶段切片。
- `p2`: 以后有用，但当前不阻塞。

`owner` 约定：

- 开始一个 item 前先设置 `owner`。
- 将 `selected_in_session` 设置为短标识，例如 `codex-2026-05-06-core-types`。
- item 有变化时更新 `updated_at`。
- 只有完成、handoff、decline、阻塞、或主动释放任务时，才清空 `owner`。
- `workflow`、`lease`、`artifacts`、`review` 是兼容扩展字段；老 harness 可以没有这些字段。
- `workflow.status` 记录细粒度阶段：`assigned`、`running`、`handoff_requested`、`blocked`、`unblocked`、`closeout_requested`、`review_approved`、`changes_requested`、`closed` 等。
- `lease` 用于避免多 agent 同时抢同一 item；过期后可以被接管，强制接管必须写 reason 并追加 event。
- `workflow.branch` 是当前 item 的工作分支；`artifacts.branch` 保持同值；`artifacts.pr` 是后续交付链接。

校验 checklist：

```bash
# 跨项目直接引用（不需要实例化脚本）
python3 "$CLAUDE_SKILL_DIR/scripts/validate-checklist.py" "$PROJECT_HARNESS_ROOT/mvp-checklist.json"

# 实例化后使用本地脚本
python3 scripts/harness/validate_checklist.py "$PROJECT_HARNESS_ROOT/mvp-checklist.json"
```

## progress.md

```markdown
# Progress

Harness root:

## Current Status

简短描述项目当前状态。

## Source Of Truth

- Project scope:
- MVP checklist:
- Tactical plan, if active:

## Session Log

### YYYY-MM-DD

- Changed:
- Verified:
- Checklist:
- Handoff:
- Notes:

## Blockers

- None.
```

## harness-config.json

```json
{
  "commands": {
    "typecheck": "python -m mypy src",
    "test": "python -m pytest",
    "build": null
  },
  "runtime": {
    "session_init_commands": ["typecheck", "test"],
    "lease_ttl_minutes": 120
  },
  "git": {
    "base_branch": "main",
    "branch_namespace": "agent/{owner}/{item_id}"
  },
  "message_bus": {
    "event_log": "docs/project-harness/events.jsonl",
    "visible_bus": "discord-or-kook"
  }
}
```

如果没有 `harness-config.json`，脚本会尝试从 `package.json` 推断 `typecheck`、`test`、`build`。不要在模板里硬编码 `pnpm`，除非实例项目确实使用它。

## runbook.md

```markdown
# Runbook

## Setup

安装依赖和初始化环境的命令。

## Develop

启动本地服务或开发模式的命令。

## Test

验证当前 MVP 的命令。

## Session Init

新 session 固定先跑的命令，例如：

```bash
scripts/harness/harnessctl state
scripts/harness/harnessctl session-init
```

说明它会刷新哪些文件、跑哪些最小检查。

## Debug

日志、trace、run records 或调试入口的位置。
```
