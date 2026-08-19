# `baisiqi6` GitHub Agent Provenance Profile

本 profile 仅适用于 GitHub 账号 `baisiqi6` 自己发布的 Agent-authored 内容。它记录该账号当前可直接
使用的写作标签，不是 EXharness 对其他用户宿主机或 Agent 的假设。其他用户只能借鉴格式，不能复制
这里的 inventory 作为自己的事实。

## 当前宿主机标签

公开 provenance 使用以下稳定逻辑名称：

- `Mac Max`
- `Mac Air`
- `Windows PC`
- `Tencent Cloud Server`

这些是显示标签，不公开 IP、原始 hostname、硬件标识或连接信息。宿主机 inventory 发生变化时更新
本 profile；不要把已退役宿主机继续写入新内容。

## Agent 与模型

`agent` 写当前实际入口，例如 `ZCode`、`Codex`、`OMP`、`Claude Code`。同一个入口可以出现在不同
宿主机，必须与 host 一起记录。不要维护固定的 host-to-agent allowlist，也不要假设 Agent 名称等于
底层模型。

Reviewer 可以额外写 `model`，但只有 provider-native transcript 已核验时才能写实际模型。通过
CC Switch 或其他代理路由时，UI 上的 `Opus`、`Sonnet` 等名称不能替代实际 provider/model 证据。

## 来源项目标签

当 Issue 或 PR 是另一个项目 dogfood / 开发过程产生的反馈时，账号 `baisiqi6` 可以增加
`source:<project-slug>` GitHub label，提供可检索的来源项目维度。正文仍使用 `acting_for` 写人类可读
来源，不为此增加重复的通用 provenance 字段。

- project slug 使用稳定的小写名称，例如 DevScope 使用 `source:devscope`。
- source label 只表示反馈来自哪个项目，不表示 Issue ownership、当前 assignee 或 mutation authority。
- 只在来源项目已确认时添加；不从仓库路径、宿主机或 Agent 名称猜测。
- 这是账号 `baisiqi6` 的自用 GitHub taxonomy。其他用户可以借鉴，也可以使用自己的 label 规则或
  完全不使用 source label。

当前已确认：

- `source:devscope`：来自 DevScope 项目开发或 dogfood 的反馈。

## 可直接使用的示例

本次 DevScope dogfood 反馈：

```markdown
> **Agent provenance:** `Mac Max / ZCode` · role=`Reporter` · acting_for=`DevScope Operator`
```

GitHub label：`source:devscope`

EXharness 维护者回复：

```markdown
> **Agent provenance:** `Mac Max / Codex` · role=`EXharness Maintainer Operator` · acting_for=`EXharness Owner`
```

独立 Reviewer（模型只是格式示例，发布前必须替换为本次实际核验值）：

```markdown
> **Review provenance:** `Windows PC / ZCode` · role=`Independent Reviewer` · acting_for=`EXharness Review` · model=`<provider-verified-model>` (provider-native transcript verified)
```

GitHub 页面已经显示 author=`baisiqi6` 与平台 timestamp。只有导出到仓库外时才补：

```markdown
submitted_via=`baisiqi6` · submitted_at=`<UTC ISO-8601 timestamp>`
```

## Authority 边界

上述 provenance 只说明内容来自哪台宿主机、哪个 Agent、以什么角色行动。它不授权 Issue close、
merge、release、deploy、生产 mutation 或其他仓库操作；最终 authority 仍由任务计划、仓库规则与用户
明确授权决定。
