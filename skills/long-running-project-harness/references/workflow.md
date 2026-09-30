# 任务执行与角色协作

选择模式、分配任务、开始/恢复实现及收口时读取。字段和 packet 细则在需要相应操作时再加载，不预先读完所有 references。

## 先完成适用的协作检查

开始或恢复实现前，按 [GitHub 协作 profile](../subskills/github-collaboration/SKILL.md)
判断适用性并执行其前置检查；已分配 Worker 使用其中的核验路径。这一步先于下面任何
ordinary/high-risk 实现流程。不同宿主机 Operator 保持平级，各自负责自己的 Worker/Reviewer。

## 运行方式边界

- Standalone：只有启用了 runtime workflow 才使用下面的 harnessctl lifecycle；ordinary
  协议任务可直接保留任务说明、验证和 handoff，不为套用命令创建整套文件。
- Coordinate-managed：先读当前 assignment/worker-bootstrap，所有 runtime mutation 走
  Coordinate lifecycle/adapter；这里的 accept/start/closeout/mark-done 表示语义，不能直接
  用裸 harnessctl 绕过 DB authority。缺少操作信息时读取 `coordinate-operator` 对应模块。
- GitHub 认领不能替代 runtime lease，runtime assignment 也不能替代跨维护者的可见协作证据。
  布局与 active plan 位置见 [storage-and-recovery](storage-and-recovery.md)。

## 工作模式

本 skill 只工作在两种模式下：ordinary 和 high-risk。开始项目级 harnessing 之前，先选择模式。模式决定活跃导航和必须遵守的边界。

### Ordinary 模式

Ordinary 模式用于单一、可在当前 session 内完成的低风险任务。最短闭环为：

```text
适用的协作前置检查 -> task spec -> 实现 -> 验证与必要的独立审查
```

- worker 负责实现，并对正确性、边界和验证负责。
- 需要独立审查时，reviewer 负责验证是否满足验收、是否越界、测试是否充分。独立不等于每轮
  都必须使用全新上下文；按审查目的选择 `continuity`、`fresh` 或 `limited-fresh`。
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

## Coding Agent Session Protocol

已启用 runtime 的 session 可使用 [coding-prompt.md](prompts/coding-prompt.md)。普通协议任务
直接使用父入口的最小闭环，不加载其字段/命令全流程。

它把整个 session 分为三层：

- **入口**（Step 0）：识别角色、风险/运行方式、完成适用的 GitHub 协作检查，确认 writer worktree
- **读层**（Step 1-6）：pwd → profile 对应 init/bootstrap → 读 state → 读边界文件 → 读 progress → 读 canonical plan
- **跑层**：包含在 session-init 中（typecheck + test）
- **写层**（Step 7-12）：选 item → 确认 plan → 实现 → 验证 → 持久化 → 汇报

核心原则：session-init 失败时先诊断，不在未解释的回归上堆新功能；只修授权范围内问题，
无关失败留证上报。canonical plan 有占位符时先补全。runtime session 结束前更新 progress、
对应 checklist 并通过 profile 对应入口 sync/validate。

## Multi-Agent Role Protocol

多 agent 项目必须显式分工：

- Operator：读取 harness 状态和 profile 对应的 event store，决定下一步点名哪个
  agent；负责发起 assignment、校验状态推进、记录高层决策。仅在已启用且授权的消息平台
  发布关键事件。不替 agent accept，也不替 reviewer 做审查判断。
- Architect：把产品目标拆成可由单个 coding session 完成的 item；维护 architecture、domain model、task plan 和边界。
- Coding agent：消费已分配或已激活的 item；由目标 agent 发起 `accept` 或 `decline`；在 scope 内实现、验证、写 handoff；默认不自行扩大范围，不直接 mark done。
- Reviewer：审查 plan/result 是否满足 acceptance、是否越界、验证是否充分，并回到真实
  问题、产品目标和最小机制判断实现；启用 runtime 审查时由 reviewer 经 profile 对应入口发起
  `review-result <item-id> <reviewer> approved|changes_requested|blocked
  --reviewed-packet-sha256 <64-hex>`（hash 对 reviewer 实际阅读的 packet 文件计算，
  不得回抄 packet header）。上下文选择与审查方法见
  [reviewer-strategy.md](reviewer-strategy.md)。
- Human：决定产品方向、范围扩大和高风险 authority；可以给出有界持久授权。
  Operator 只能在该授权覆盖的目标、范围和时限内执行，且不能省略安全 gate。

## High-risk 生命周期阶段

以下阶段属于 high-risk 模式。ordinary 使用上面的轻量闭环，不强制以下阶段。

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

## 任务开始规则

先完成本模块开头引用的 GitHub 协作前置检查，确认共享范围及当前 writer 的隔离位置。
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

如果连续 3 次尝试同一问题仍未推进，停止无证据重试并记录问题/所需决策。ordinary 无 runtime
任务将这些信息留在当前 task note/handoff，不强制创建 blocker packet。已启用 runtime 时：

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

### Coordinate closeout input compatibility

`harnessctl workflow-contract` is a read-only capability query. Version 1
advertises `reviewed_packet_sha256=true` and `self_test_evidence=true`.
`harnessctl closeout <item-id> [reviewer] --self-test-evidence TEXT` preserves the
supplied text in the new packet's **Self-test Evidence** section without changing
historical checklist verification. Unknown closeout options fail before packet
or checklist writes rather than being silently ignored.

Coordinate adapters must check this capability before closeout/review-result and
pass the reviewer's exact `--reviewed-packet-sha256` unchanged. Updating only the
installed skill does not update a project's instantiated scripts: review and
deploy the matching project runtime files, regenerate the packet, then review
its actual bytes. Existing phase, plan/packet freshness and completion gates
remain required; capability support is not an approval or completion receipt.
