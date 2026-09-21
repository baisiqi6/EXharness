# 产品方向与范围复核

仅在产品方向、部署/权威边界或新风险类别变化时读取。

## Scope review 触发器

当出现“新的产品方向或新风险类别”这类稳定信号时，做一次轻量 scope review。它不是周期性
项目管理仪式，也不改变任务模式；维护者裁决见
[Issue #8 裁决](https://github.com/baisiqi6/EXharness/issues/8#issuecomment-5338071303)：
事件触发，不采用“每关闭 N 个 item”计数器，不增加 cadence/config/schema/file/runtime。

### 触发事件（仅三类）

1. 产品目标或用户方向发生明确变化（用户明确的长期方向决策）。
2. 部署环境、authority boundary 或 deployment/use profile 发生变化。
3. incident、dogfood 或真实运行证据暴露 checklist 未覆盖的新风险类别。

普通实现细节、临时想法、每完成一个 item、固定时间或数量均不触发。ordinary 任务不会
因为本协议升级为 high-risk 或强制新增 checklist 节点。

### 结果落点（复用现有 authority，至少一种）

Operator 先重读 `scope.md`、当前 checklist 与相关 architecture/decision，再让本次信号
至少落入一种结果；一个方向决策确有多个独立后果时，可以同时使用多个落点，但每项只落盘
一次，不复制正文。不创建新的 scope review 文件、risk registry、第二份 backlog 或新状态机：

1. 确需跨 session 恢复的重要工作 → 现有 `add-item` / `update-item`（Coordinate-managed
   仍走 Coordinate 入口）；
2. 明确推迟或不做的方向 → 写入现有 `scope.md` 的 non-goals / deferred decision；
3. 现有范围已覆盖或无需动作 → 在现有 `progress.md` / task note 记录 `no change` 与原因。

只有 Human 决定产品方向与高风险 authority；scope review 不自行扩大授权。

### 示例：用户明确“后续支持多用户”

用户说“后续确定支持多用户”时，Operator 对照当前 scope/checklist 后分支处理：

- 需要跨 session 建设 → 用 `add-item` 登记一个重要 item（含 acceptance），不自动
  start、不写 lease；
- 本阶段明确推迟 → 写入 `scope.md` 的 deferred / non-goal，附 locator；
- 已被现有 item 覆盖 → 在 `progress.md` 记录 `no change` 与覆盖它的 item locator。
