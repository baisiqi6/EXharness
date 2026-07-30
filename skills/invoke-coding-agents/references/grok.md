# Grok Build CLI

这里记录独立的 `grok` coding-agent CLI。若只是通过 OMP 选择 Grok/xAI model，仍读取 [omp.md](omp.md)，不要创建第二套调用流程。

## 实时核验

```bash
command -v grok
grok --version
grok inspect
grok models
```

`grok inspect` 会显示当前目录实际加载的 rules、skills、agents、plugins、MCP、hooks 和 permissions。Grok 可兼容读取 Claude/Codex 配置；调用陌生 checkout 前先检查这些来源，不能假设它是 bare runtime。

`grok models` 可能在远端刷新失败后保留缓存列表。区分刷新错误、cached available models、default model 和本轮 `modelUsage`，不要仅凭旧 default 断言实际模型。

## 只读 reviewer

不需要 shell 或动态测试时使用严格工具 allowlist：

```bash
sid=$(uuidgen | tr '[:upper:]' '[:lower:]')
grok \
  --prompt-file /absolute/task/review-request.md \
  --cwd /absolute/project \
  --model '<current-model-id>' \
  --session-id "$sid" \
  --output-format streaming-json \
  --tools 'read_file,grep,list_dir' \
  --disallowed-tools 'run_terminal_cmd,search_replace,Agent' \
  --permission-mode dontAsk \
  --disable-web-search \
  --no-subagents \
  --no-memory \
  --max-turns 20
```

Grok `--tools` 使用内部 tool ID；shell 是 `run_terminal_cmd`，不是 `bash`。如果 review 需要 Git、测试或其他 shell 核验，优先由 operator 独立运行；确需 Grok 执行时，使用 `--allow 'Bash(git *)'` 等窄规则、OS sandbox 和结束后的零 mutation 检查。不要把“read-only command”分类当作安全边界。

## 可写 worker

只在已授权的隔离 worktree 使用：

```bash
sid=$(uuidgen | tr '[:upper:]' '[:lower:]')
grok \
  --prompt-file /absolute/task/worker-bootstrap.md \
  --cwd /absolute/worktree \
  --model '<current-model-id>' \
  --session-id "$sid" \
  --output-format streaming-json \
  --permission-mode acceptEdits \
  --disable-web-search \
  --no-subagents \
  --no-memory \
  --max-turns 40
```

也可让 Grok 创建隔离 worktree：

```bash
grok --worktree=bounded-task --worktree-ref=<reviewed-base> --prompt-file /absolute/task/worker-bootstrap.md
```

`--always-approve`、`--yolo` 和 `--permission-mode bypassPermissions` 等价于自动批准工具。只有外部已经提供等强隔离且任务明确授权时才使用；它们不授予 commit、push、merge、deploy 或生产 authority。

## Structured output 与 model 证据

`--output-format json` 在结束后返回一个对象；`streaming-json` 实时返回 `text`、`thought`、`end`、`error` 等事件。监督时跳过 `thought` 内容，只读取：

- `sessionId`、`requestId`；
- `type`、timestamp/进程状态；
- `stopReason`、error category；
- `modelUsage`、usage/cost completeness；
- 最终 text/verdict。

以本轮 `end.modelUsage`、当前 `grok models` 和必要的 provider metadata 共同核验实际 model。调用参数只表示 requested model。

## Session 与恢复

Grok 的 session root：

```text
~/.grok/sessions/<encoded-cwd>/<session-id>/
```

其中 `updates.jsonl` 是 resume/restore 的权威 conversation log，`summary.json` 是索引摘要。不要读取 `~/.grok/auth.json`、MCP credential 或 transcript 中的 private thought。

列出当前目录 session：

```bash
grok sessions list
```

恢复必须使用 `--resume`：

```bash
grok \
  --prompt-file /absolute/task/correction.md \
  --cwd /absolute/worktree \
  --resume '<session-id>' \
  --output-format streaming-json
```

`--session-id` 只创建新 session，不能恢复已有 session。需要保留历史但尝试不同方向时，将 `--resume`、`--fork-session` 与一个新的 `--session-id` 组合。脚本不要用 `--continue` 猜“最近 session”，多项目并行时始终传精确 ID。
