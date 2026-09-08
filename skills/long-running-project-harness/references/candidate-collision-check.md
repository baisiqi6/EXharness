# 社区贡献候选：语义碰撞检查

在从外部仓库选择独立贡献候选（包括 dogfood 修复）时读取本指南。目标是判断当前是否还有
独立交付空间；能复现问题、没有精确引用 Issue 的 PR，都不能单独证明没有重复工作。
用户已指定协作既有 PR 时，检查用于划分剩余范围，不要求把已有工作重新判成“无人施工”。
普通本地修改、无 GitHub 的项目不触发本流程。

这是 Operator 的准入规则与证据格式，不是 runtime 的自动 gate。EXharness 维护协议，执行
Operator 维护任务内证据；GitHub 和当前源码提供事实。不要为这些结论增加 checklist 状态、
Coordinate/MultiNexus schema 或第二套 Issue registry。

## 何时检查

在 shortlist 入选、创建实现工作树前、push/PR 前刷新。每阶段留下 UTC 时间与结论；连续阶段
没有新操作时可引用同一轮有效证据并说明理由，不必复制记录。实现前先做有时间盒的碰撞检查，
通常 15–20 分钟；超时、搜索失败或关键覆盖未完成时记 `incomplete`，换候选或上报缺口，
不能因预算耗尽而判定可开工。允许为定位 owner 做必要的只读分析，不提前投入完整实现与审查。

恢复旧任务、候选范围变化或相关 PR 出现新提交时，刷新受影响的证据。发布前必须重新读取
远端状态；已有授权不会因检查而失效，但已有检查也不代替 push/PR 的授权。

## 如何判断是否有重复工作

1. 定义用户症状、预期行为、配置/函数/错误文案关键词和可能的 owner 文件。先确认目标分支
   当前源码是否仍有缺陷，记录 base commit；不要只凭旧 Issue 描述选题。
2. 同时检查精确 Issue 引用与语义标题/正文。用症状、配置名、函数名、错误文案分别搜索，
   不把多个词拼成一次零结果查询就结束。覆盖 open、closed-unmerged 和相关 recently merged
   PR；记录最近合并的时间范围及理由，不能把 Issue 创建时间当作最早搜索边界。
3. 查看相关命中的说明、讨论、changed files 与当前 head。对 owner 重叠项比较具体行为和
   修复范围；相同文件不等于重复，不同 Issue 也可能修同一问题。只有需要证明两份源码等同
   时才比较 exact blob；文件无 diff 不能代替所有相关行为的分析。
4. 区分已有主修复、已合并修复与剩余缺口。closed-unmerged PR 是历史尝试线索，不自动
   占有该问题；recently merged PR 需要核对当前源码是否已修复。PR 冲突、CI 失败、无近期
   更新也不自动释放协作范围。残余问题应有独立的用户可见差异和源码证据。
5. 检查工具有效性。记录原始查询、repo/state/time 过滤、分页/截断和错误。依赖零结果前，
   用已知存在且应匹配的 PR 做正例校验；找不到正例或查询路径漏检时换用可靠路径（例如直接
   GitHub Search API）并重查。正例能命中只证明该查询路径可用，不证明语义搜索已穷尽。

搜索结果只用于发现候选，必须打开相关 PR 核对。未分配、没有人工留言、缺少关联标签以及
精确编号搜索为空，都不得单独作为“无人施工”的证据。执行 Operator 给出有范围限定的判断，
不能把“本轮未发现重复”写成全局不存在重复的保证。

## 准入结论

以下值只写入候选证据，不写入 checklist 的 `status` 或 `workflow.status`。

| 结论 | 适用情况与下一步 |
| --- | --- |
| `eligible_for_implementation` | 检查完整、当前缺陷仍在，未发现实质重复工作；记录搜索范围与判断理由，再按既有任务授权进入实现。 |
| `blocked_by_existing_pr` | 活跃 PR 已覆盖拟交付范围；换候选或联系现有作者协作。 |
| `residual_value_only` | 已有主修复，但有明确剩余缺口；限定补充范围，优先交给已有作者吸收，不自动授权另开 PR。 |
| `already_fixed` | 当前源码已消除拟修问题；停止原实现计划。 |
| `incomplete` | 查询可靠性、覆盖或源码判断不足；列出缺口与下一动作，暂不进入独立实现/发布。 |

不要把早期错误的准入结论改写成当时已完成检查。追加更正、当前结论及证据，保留原始
选型和审查记录。后来找到残余价值不能反向证明最初的独立候选选择正确。

## 任务内证据模板

在现有 task artifact root 使用 `tasks/<item-id>/candidate-collision-check.md`，从唯一 canonical
plan 链接它。无 checklist 的 ordinary 任务可放在已有任务证据目录，不因此强制创建 item。
模板是可复制的字段约定，不创建新的计划权威或任务状态账本。每次刷新追加一个阶段记录。

```markdown
# Candidate collision check

- Repository / Issue:
- 拟修用户行为与预期结果:
- 症状、配置、函数、错误文案关键词:
- 可能的 owner paths:
- 执行 Operator:

## 检查记录

- 阶段：shortlist / pre-implementation / pre-publication
- Checked at（UTC，YYYY-MM-DDTHH:MM:SSZ）:
- 目标分支 / base commit:
- 搜索覆盖：open / closed-unmerged / recently merged（日期范围与理由）:
- 查询证据：每项记录工具、完整查询及过滤、分页/截断、错误、结果链接:
- 已知正例：预期可命中的 PR、查询与实际结果；失败时的替代路径与复查:
- 相关 PR：URL、状态、head、owner overlap、实际行为覆盖或排除理由:
- 当前源码：缺陷仍在 / 已修复 / 无法判断；源码 locator 与依据:
- 复用先前证据（如有）：记录位置、未变范围和仍适用的理由:
- 未完成项 / 不确定性:
- 结论：eligible_for_implementation / blocked_by_existing_pr /
  residual_value_only / already_fixed / incomplete
- 结论理由、可交付范围、下一动作与 owner:
```

后续如增加只读采集器，只校验查询执行、分页和证据字段完整性；语义结论仍由 Operator
负责。空结果、字段齐全或源码 blob 相等都不自动产生 `eligible_for_implementation`。
