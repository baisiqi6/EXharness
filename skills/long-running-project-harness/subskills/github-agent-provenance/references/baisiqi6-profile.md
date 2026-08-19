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

## 可直接使用的示例

本次 DevScope dogfood 反馈：

```markdown
> **Agent provenance:** `Mac Max / ZCode` · role=`Reporter` · acting_for=`DevScope Operator`
```

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
