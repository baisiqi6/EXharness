# Claude Code 与 CC Switch

## 实时核验

```bash
command -v claude
claude --version
claude auth status --text
claude --help
```

本机可能通过 CC Switch 或其他 gateway 改写请求。`--model opus`、`--model sonnet` 只是 Claude Code 的请求标签，不能证明实际下游模型。

## 只读 reviewer

```bash
TASK=/absolute/task/review-request.md
LOG=/absolute/task/claude-review.jsonl

printf '%s\n' "$(cat "$TASK")" | \
  claude -p \
    --safe-mode \
    --strict-mcp-config \
    --mcp-config '{"mcpServers":{}}' \
    --model opus \
    --effort max \
    --output-format stream-json \
    --verbose \
    --permission-mode plan \
    --tools 'Read,Grep,Glob,Bash' \
    --disallowedTools 'Edit,Write,NotebookEdit,Task,Agent,WebFetch,WebSearch' \
  | tee "$LOG"
```

如果 plan/safe mode 拒绝动态测试，让 operator 独立运行测试并把结果作为外部证据；不要为了方便把 reviewer 临时变成可写 worker。

## 可写 worker

只在已授权的隔离 worktree 内使用：

```bash
TASK=/absolute/task/worker-bootstrap.md
LOG=/absolute/task/claude-worker.jsonl

printf '%s\n' "$(cat "$TASK")" | \
  claude -p \
    --model opus \
    --effort max \
    --output-format stream-json \
    --verbose \
    --dangerously-skip-permissions \
  | tee "$LOG"
```

task 文件必须列出修改 allowlist，并明确禁止当前未授权的 reset、clean、commit、merge、push、deploy、SSH 和生产 mutation。结束后 operator 独立检查 diff 与测试。

## 核验实际下游 model

先发起当前 session 请求，再查询最新成功记录：

```bash
sqlite3 -json "$HOME/.cc-switch/cc-switch.db" \
  "SELECT request_model, model, status_code, session_id FROM proxy_request_logs WHERE app_type = 'claude' ORDER BY rowid DESC LIMIT 5;"
```

关联当前 session/request，至少记录：

- Claude Code 请求的 `request_model`；
- gateway 实际 `model`；
- `status_code`；
- `session_id`；
- 查询时间。

不要把一次历史映射永久写成“opus 就是某模型”。Provider、订阅和路由可随时变化；每次关键派发前重新验证。

## Session 与恢复

Claude stream-json 的 init/result event 会给出 session ID。恢复指定 session：

```bash
claude -p \
  --resume '<session-id>' \
  --output-format stream-json \
  --verbose \
  '继续未完成任务；先对照当前 task 文件、Git 状态和测试，不重复已完成工作。'
```

需要保留历史但尝试不同路径时使用 `--fork-session`。不要用旧 session 的文字记忆覆盖当前仓库事实。

## 监督边界

- 使用 stream-json、进程、artifact、Git 和测试作为证据。
- 不读取或转述 private thinking；`--verbose` 用于结构化事件和工具活动，不是索取思维链。
- Claude 自身的 agent team/subagent 能力属于 worker 内部执行方式；顶层 operator 仍负责任务边界、最终 review 与 authority。
