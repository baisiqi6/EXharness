---
name: long-running-project-harness-github-agent-provenance
description: Use when an Agent drafts, reviews, or publishes a GitHub Issue, PR, or comment for a project using long-running-project-harness and the shared GitHub account alone cannot identify the originating host, Agent surface, role, or represented Operator. Keep provenance separate from authority, and load an account-specific profile only when it actually matches the current account.
---

# GitHub Agent Provenance

这个子 skill 只解决一个问题：同一个 GitHub 账号下存在多个宿主机和 Agent 时，让读者知道一段内容
来自哪里、以什么角色产生。它不验证 Agent 身份，也不授予 merge、release、deploy 或 production
mutation authority。

## 何时使用

仅在 Agent 代表项目 Operator 起草、审查或发布 GitHub Issue、PR、review 或 comment 时使用。
人类直接写作不强制增加 Agent provenance；已有 task receipt 只服务私有审计时，也不把完整执行链
复制到公开评论。

## 通用字段

公开行只保留足以消除歧义的字段：

- `host`：用户自己定义的稳定逻辑显示名称，不是 IP、机器序列号或原始 hostname。
- `agent`：实际交互入口，例如 `ZCode`、`Codex`、`OMP` 或 `Claude Code`；不要把 UI 显示名当成
  底层模型。
- `role`：该内容中的职责，例如 `Reporter`、`Worker`、`Independent Reviewer`、
  `Maintainer Operator`。
- `acting_for`：它代表的项目级角色，例如 `DevScope Operator` 或 `EXharness Owner`。
- `model`：可选，只在 Reviewer 模型会影响证据解释且已由 provider-native transcript 核验时记录。

普通 Agent 内容使用：

```markdown
> **Agent provenance:** `<host> / <agent>` · role=`<role>` · acting_for=`<operator>`
```

独立审查使用：

```markdown
> **Review provenance:** `<host> / <agent>` · role=`Independent Reviewer` · acting_for=`<project review>` · model=`<verified-model>` (provider-native transcript verified)
```

GitHub 自带的 author 与 timestamp 是公开提交账号和时间的 authority，不需要在每条内容中重复。
当内容被导出到 GitHub 之外、会失去平台元数据时，才按需补：

```markdown
submitted_via=`<github-account>` · submitted_at=`<UTC ISO-8601 timestamp>`
```

## Authority 与真实性边界

- provenance 说明内容来源，不代表该 Agent 拥有 Issue close、merge、release、deploy 或其他 mutation
  authority。最终决策者与 Reviewer 必须按项目协议分开记录。
- `agent` 与 `model` 是不同事实。CC Switch、代理路由或 provider fallback 场景下，只能记录
  provider-native evidence 实际确认的模型；不能照抄 UI label 或历史路由。
- 不把 IP、credential、token fingerprint、机器序列号、private session ID 或内部原始 hostname
  放进公开 provenance。精确 session、provider JSONL 和执行 receipt 留在项目选择的私有 artifact root。
- 发现旧 provenance 有误时追加明确更正或修改当前 canonical Issue/PR 正文；不要删除历史评论来
  伪装从未出错。

## Account profile 路由

宿主机和 Agent inventory 属于用户自己的运行环境，不是 EXharness 通用事实：

1. 先确认当前 GitHub account 或项目明确指定的 publication profile。
2. 只有账号确实是 `baisiqi6` 时，读取
   [baisiqi6 profile](references/baisiqi6-profile.md) 并直接使用其中的 host labels。
3. 其他用户只能借鉴字段结构，必须按自己的宿主机、Agent 和 privacy boundary 建立自己的 profile；
   不得复制 `baisiqi6` 的 host inventory 当作默认值。
4. 没有 account profile 时，优先从当前运行环境和用户已确认的信息得出最小 provenance；无法确认
   `host` 或 `agent` 时标为 `UNVERIFIED`，不要猜测。

## 最小写作纪律

- Issue/PR 正文把 provenance 放在开头，帮助后续评论理解来源。
- 单条评论只记录这次实质贡献者，不复制整条 Worker/Reviewer/Operator 链。
- 多 Agent 共同产出时分别记录其实际角色；没有独立贡献的旁观 Agent 不进入 provenance。
- 不为历史仓库做机械批量回填。从新内容开始采用，旧内容只在再次修改或发生归因争议时补充。
