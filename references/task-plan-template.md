# Task Plan Template

这个模板用于某个正在执行的 checklist item。它不是项目总计划，而是任务级计划正文。

推荐落点：

- 规范正文：`<artifact-root>/tasks/<item-id>/plan.md`
- 当前指针：`<artifact-root>/current/task_plan.md`

也就是说，这个模板主要给 `tasks/<item-id>/plan.md` 使用；`current/task_plan.md` 只需要保留当前 item、owner、session 和 canonical plan path。

co-located layout 的 `<artifact-root>` 可以是 `docs/project-harness`；Standalone split layout 可以是
`$MYHARNESS_ROOT/projects/<project_id>`（此时 active canonical plan 可放在此处）。**Coordinate-managed
项目不适用此 split**：其 active canonical plan 必须留在产品 workspace（`plan_doc` 要求
workspace-relative），`$MYHARNESS_ROOT` 只存该 task 的过程材料。同一任务只能选择一个 canonical root，
不双写。当前 Coordinate 若要求 workspace-relative plan path，先保留 repo-local 兼容 locator，不用
symlink 绕过。

```markdown
# Task Plan

## Item

- Checklist item:
- Owner:
- Session:
- Updated at:

## Goal

本轮要交付什么。

## In Scope

- 本轮明确要做的事情。

## Out Of Scope

- 明确这轮不做什么。
- 哪些相关内容属于其他 checklist item。

## Acceptance Mapping

- 当前 item 的 acceptance:
- 本轮计划如何满足它:

## Boundary Review

- Scope non-goals checked:
- Architecture boundaries checked:
- Domain-model decisions checked:
- Potential overlap with other items:

## Steps

1. 
2. 
3. 

## Verification

- typecheck:
- tests:
- manual review:

## Exit Criteria

- 什么条件成立时，这一轮可以结束。

## Handoff

- 如果本轮未完成，下一轮从哪里继续。
```
