# Review Template

这个模板用于计划审查、结果审查或阶段性边界审查。先读
[reviewer-strategy.md](reviewer-strategy.md)；以下结构帮助结论可复核，不要求为了填满栏目而
制造 finding。

```markdown
# Review

## Subject

- Checklist item:
- Plan or artifact under review:
- Reviewer:
- Context mode: continuity / fresh / limited-fresh
- Why this mode:
- Updated at:
- Event:

## Review Context

- User problem and product purpose:
- Canonical sources and authority boundaries:
- Current code / diff:
- Non-goals:
- Evidence available and `UNVERIFIED` boundaries:

## Problem And Design Fit

- 当前实现是否直接解决真实问题：
- 是否存在同样正确但更小、authority 更清楚的实现：
- 防御机制对应的真实 failure mode：

## Findings

没有实质 finding 时写 `None`，不要为了“严格”而制造问题。

### P0 / P1 / P2 / P3 — Finding title

- Evidence:
- Impact:
- Minimal counterexample:
- Minimal correction:

## Complexity Check

- 可以删除、合并或推迟而不损害核心正确性的内容：
- 仅服务假想风险或重复 authority 的内容：

## Evidence Consistency

- 需求、代码、测试、文档和 runtime evidence 是否一致：
- 哪些结论只是 claim / receipt，哪些已独立验证：

## Decision

- APPROVE / CHANGES_REQUESTED / BLOCKED

## Required Changes

1. 仅列阻塞或明确要求修正的事项。

## Notes

- Reviewer verdict 不授予 commit、merge、push、deploy、delete 或 production mutation authority。
```
