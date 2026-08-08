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

> **文件名权威规则（U1）**：新项目使用 `harness-checklist.json`；`mvp-checklist.json`
> 作为 legacy 文件名继续完整可用。runtime 通过唯一 resolver 决定当前 checklist：
> 只有新名、只有旧名都正常读写；两者都没有或同时存在时 fail closed（doctor
> 只诊断 dual authority，不宣布哪份 active）。需要从旧名切换到新名时运行
> `harnessctl migrate-checklist`（只做同目录 rename，不改 bytes，不提交 Git）。
> 不要在普通 read/mutation 下手动二选一。

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
# 跨项目直接引用（不需要实例化脚本；legacy 名 mvp-checklist.json 也接受）
python3 "$CLAUDE_SKILL_DIR/scripts/validate-checklist.py" "$PROJECT_HARNESS_ROOT/harness-checklist.json"

# 实例化后使用本地脚本（不传路径时走 resolver）
python3 scripts/harness/validate_checklist.py "$PROJECT_HARNESS_ROOT/harness-checklist.json"
scripts/harness/harnessctl validate
```

### 重要节点登记（add-item / update-item）

operator 需要新增或调整重要节点时，用 `harnessctl` 落盘，不要手改 JSON：

```bash
# 新增 todo 节点（初始状态固定 todo，priority 默认 p1）
scripts/harness/harnessctl add-item mvp-004 \
  --title "Implement node handlers" \
  --acceptance "Node handlers pass the configured test suite." \
  --priority p1 \
  --dependency mvp-002 \
  --handoff "Next session starts from current/task_plan.md."

# 更新已存在节点的允许字段（title/acceptance/priority/plan/verification/handoff/依赖）
scripts/harness/harnessctl update-item mvp-004 \
  --acceptance "Updated acceptance text." \
  --add-dependency mvp-003
```

规则：

- `add-item` 只创建 `todo` 节点；不创建 plan 文件、不自动 start、不写 lease/review/workflow 占位对象。
- 只有提供 `--plan` 时才写 plan locator；同一节点不要同时维护 `plan_path` 与 `artifacts.plan` 两个不同值。
- `--plan` 指向的文件必须已存在；Standalone 允许 operator 明确选择 external absolute plan locator
  （这是 operator 选择，不是 containment 安全保证）。
- `update-item` 不能修改 `status`、`owner`、`selected_in_session`、`lease`、`workflow.status`、`review.decision`；
  这些走 lifecycle 命令。未触碰字段与未知兼容字段原样保留。
- `deployment_profile=coordinate-managed` 下裸 add/update fail closed，走 Coordinate 入口；
  `migrate-checklist` 需要显式 `--ack-managed-profile`（只是防误操作确认，不是 authority token）。

### GitHub-backed 团队协作

如果项目使用 GitHub Issues/PRs，不要再维护一套 item ID registry。单仓库中直接使用
`issue-<number>`：Issue `#123` 对应 `issue-123` 与 `tasks/issue-123/plan.md`。

```bash
# 先在 GitHub 确认 #123 open、无人认领、没有 active implementation PR，并完成认领
scripts/harness/harnessctl add-item issue-123 \
  --title "Issue #123 的交付标题" \
  --acceptance "验收条件通过，PR 关联并关闭 #123"

# 每个 writer 使用独立 branch/worktree；branch 与 workflow/artifacts 中的记录保持一致
git worktree add ../worktrees/issue-123 -b agent/codex/issue-123
```

权威边界：Issue 保存需求、repo-scoped identity 与 cooperative claim；branch checklist 是 merge
candidate，`main` checklist 是 accepted canonical snapshot；task plan 保存执行细节；PR 保存 diff、
review、CI 与 merge 结论。assignee/label 不是 hard lock，认领后仍应重读远端 Issue/PR 状态。
branch 可遵循项目已有 namespace，但自定义后必须让 `workflow.branch` 与 `artifacts.branch` 保持同值。

团队当前工作的全局视图来自实时 Issue/PR；未合并分支的状态不提前复制进 `main` checklist。合并时，
不同 Issue 节点都应保留，并对 merge candidate 运行 checklist validator；同一 `issue-123` 若重复或
语义不同则停止，由 reviewer 对照 Issue 处理，不得静默覆盖或改号。普通单 session 任务不强制创建 Issue/item；没有 GitHub 的 Standalone 项目继续
使用 operator 选择的 safe ID；Coordinate-managed 节点仍走 Coordinate authority。

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
  "deployment_profile": "standalone",
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

`deployment_profile` 只接受 `standalone` 与 `coordinate-managed`，缺省按 `standalone` 兼容处理：

- `standalone`：裸 `add-item` / `update-item` 可用。
- `coordinate-managed`：裸 add/update fail closed（指向 Coordinate 入口）；
  lifecycle 命令仍可被 Coordinate 的 HarnessAdapter 受控调用；`migrate-checklist` 需要显式 `--ack-managed-profile`。

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
