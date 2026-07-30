# Qoder CLI

## 实时核验

优先使用绝对 binary，避免非交互 shell 找不到 `qoder` alias：

```bash
command -v qodercli
/Users/Admin/.local/bin/qodercli --version
/Users/Admin/.local/bin/qodercli --list-models
```

model 名必须使用 `--list-models` 的当前精确值，例如 `Qwen3.8-Max-Preview`，不要写成自然语言别名。

## 独立 reviewer

需要 Bash 复核 Git 与测试时：

```bash
sid=$(uuidgen | tr '[:upper:]' '[:lower:]')
/Users/Admin/.local/bin/qodercli \
  -p \
  --model Qwen3.8-Max-Preview \
  --reasoning-effort high \
  --permission-mode bypass_permissions \
  --tools Read Grep Glob Bash \
  --output-format stream-json \
  --max-output-tokens 12000 \
  --cwd /absolute/project-or-harness \
  --add-dir /absolute/product-repo \
  --attachment /absolute/task/review-request.md \
  --session-id "$sid" \
  --name bounded-independent-review \
  '读取附件并独立核验。禁止编辑、提交、push、deploy 和未授权生产操作。按 P0-P3 输出 findings，最后给唯一 verdict。'
```

`bypass_permissions` 让非交互 Bash 可执行，也意味着 CLI 不再替 operator 阻止 mutation。必须依靠只读任务边界、工具 allowlist、隔离目录和结束后的独立 Git 检查。

不需要 Bash 时使用更严格的调用：

```bash
/Users/Admin/.local/bin/qodercli \
  -p \
  --model Qwen3.8-Max-Preview \
  --permission-mode dont_ask \
  --tools Read Grep Glob \
  --cwd /absolute/project \
  --attachment /absolute/task/review-request.md \
  '执行只读审查，不得修改任何文件。'
```

`dont_ask` 是“无法确认时拒绝”，不是自动批准。非交互 session 遇到需要确认的 Bash 时可能返回：

```text
Permission confirmation required but no interactive handler is available.
```

## Session 与 native evidence

Qoder session JSONL 通常位于：

```text
~/.qoder/projects/<由-cwd-编码的目录>/<session-id>.jsonl
```

按显式 session ID 定位：

```bash
find "$HOME/.qoder/projects" -name "$sid.jsonl" -print
```

从 stream init/runtime-config 和 assistant message 的 `model` 字段核对实际模型。旧版本可能记录内部别名，例如 `qmodel_preview`；保留原始字段并说明 alias，不凭 UI 标签改写。

监督时只读取安全 metadata、tool name、timestamp、stop reason 和最终文本；不要读取或转述 `thinking` 正文。

## 恢复

```bash
/Users/Admin/.local/bin/qodercli \
  -p \
  --resume "$sid" \
  --cwd /absolute/project \
  --output-format stream-json \
  '继续上一任务，只处理未完成的验收项；先报告当前状态，不重复已完成工作。'
```

恢复前重新检查 worktree、任务文件与权限边界，不能假设旧 session 的现实状态仍有效。
