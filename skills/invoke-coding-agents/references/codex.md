# Codex CLI

## 实时核验

```bash
command -v codex
codex --version
codex exec --help
```

Codex 可以使用 `--skip-git-repo-check` 在非 Git 目录运行；代码任务仍优先在 Git repo/worktree 中执行，以便检查变更。

## 只读 reviewer

```bash
codex exec \
  --cd /absolute/project \
  --sandbox read-only \
  --json \
  --model '<current-model>' \
  '独立审查当前变更；不得修改文件。按严重度输出 findings 和最终 verdict。'
```

## 可写 worker

```bash
codex exec \
  --cd /absolute/worktree \
  --sandbox workspace-write \
  --json \
  --model '<current-model>' \
  '执行 task 文件中的有界实现。仅修改 allowlist；不得 commit、push、merge、deploy。'
```

避免使用 `--dangerously-bypass-approvals-and-sandbox`；只有外部已经提供等强隔离并明确授权时才可考虑。`workspace-write` 也不等于获得 Git remote 或生产 authority。

## Session 与输出

`--json` 把事件作为 JSONL 输出；provider-native session 通常保存在：

```text
~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl
```

恢复前查看当前 CLI 帮助：

```bash
codex exec resume --help
```

然后使用显式 session ID，避免 `--last` 在多个项目并行时续接到错误任务。

Codex CLI 的 `model_context_window` 是客户端预算，不能单独证明服务端模型具有相同上下文容量。模型和上下文判断应以当前 model catalog/service 事实为准。
