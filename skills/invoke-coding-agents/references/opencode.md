# OpenCode

## 实时核验

```bash
command -v opencode
opencode --version
opencode auth list
opencode run --help
```

OpenCode 可能存在多个 binary；行为不一致时先运行 `which -a opencode`，必要时固定绝对路径。

## One-shot worker/reviewer

```bash
/Users/Admin/.opencode/bin/opencode run \
  --dir /absolute/worktree \
  --model '<provider/model>' \
  --variant high \
  --format json \
  --file /absolute/task/bootstrap.md \
  --title bounded-task \
  '执行附件任务。遵守 allowlist；不得 reset/clean/push/deploy。'
```

只读 reviewer 在 prompt 中明确零 mutation，并在结束后由 operator 检查 Git 状态。`--auto` 会自动批准未显式拒绝的权限，属于危险选项；只在隔离且已授权的 worker 任务使用。

不要依赖 `--thinking` 监督任务。使用 JSON event、tool activity、artifact、Git 与测试状态。

## Session

```bash
opencode session list
```

恢复指定 session：

```bash
/Users/Admin/.opencode/bin/opencode run \
  --session '<session-id>' \
  --dir /absolute/worktree \
  --format json \
  '继续未完成验收；先报告当前状态。'
```

保留上下文但创建新 session 使用 `--fork`。交互模式需要 PTY；退出 TUI 使用 `Ctrl+C`，不要发送不存在或语义不确定的 `/exit`。
