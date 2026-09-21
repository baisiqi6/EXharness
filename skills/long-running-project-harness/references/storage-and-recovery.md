# 存储布局与恢复

选择/迁移 artifact root、初始化项目文件或恢复跨 session 状态时读取。这里只定义文件权威与布局，执行顺序见 [workflow.md](workflow.md)。

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

模板见 [task-plan-template.md](task-plan-template.md)、[blocker-template.md](blocker-template.md)、[review-template.md](review-template.md)。使用 review 模板前先读
[reviewer-strategy.md](reviewer-strategy.md)；模板只是输出结构，不是机械 checklist。
