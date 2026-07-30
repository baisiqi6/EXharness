# Oh My Pi（OMP）

## 实时核验

```bash
command -v omp
omp --version
omp --help
omp models
omp usage
```

使用 `omp models` 的当前 provider/model 标识。不要把历史上可用的 Kimi、GLM、DeepSeek、MiniMax 或 xfyun 路由硬编码为永久优先级。

## 非交互调用

```bash
omp -p \
  --cwd=/absolute/worktree \
  --add-dir=/absolute/read-only-context \
  --model='<current-provider/model>' \
  --thinking=high \
  --mode=json \
  --max-time=30m \
  --session-dir=/absolute/task/sessions \
  '@/absolute/task/worker-bootstrap.md' \
  '严格执行 bootstrap；不得扩大修改范围或执行未授权的 commit/push/deploy。'
```

`@file` 会把文件加入初始消息。任务材料较长时优先使用这一方式。

只读 reviewer 可用 `--no-tools` 做纯文本审阅；若需要代码/Git/测试核验，则按当前 OMP 配置选择工具和 approval mode：

```bash
omp -p \
  --cwd=/absolute/project \
  --model='<current-provider/model>' \
  --thinking=high \
  --mode=json \
  --tools=read,bash,search,find \
  --approval-mode=always-ask \
  '@/absolute/task/review-request.md'
```

`always-ask` 会自动批准被 OMP 归类为 read-only 的工具；Bash 是否需要确认取决于命令与当前 policy。若非交互模式因此拒绝必要的只读 Bash，由 operator 独立运行该核验，或在隔离环境和明确边界下选择更宽模式并在结束后证明零 mutation。

运行前以 `omp --help` 和一次无 mutation smoke 确认本机工具名；extension 可增加或替换工具，不能把示例列表当成永恒 schema。当前配置也可能把 `tools.approvalMode` 设为 `yolo`，因此 reviewer 必须显式覆盖为 `always-ask`。

普通可写 worker 可显式使用 `--approval-mode=write`，它会批准 read 与 workspace-write 工具。`--auto-approve` 或 `--approval-mode=yolo` 只能在已授权的隔离 workspace 中使用。它们都不授予 commit、push、deploy 或生产 authority。

## Session 与恢复

默认 session root 是：

```text
~/.omp/agent/sessions/
```

也可以用 `--session-dir` 把 task session 明确落到 task evidence 目录。恢复：

```bash
omp -p \
  --resume='<session-id-or-session-path>' \
  --cwd=/absolute/worktree \
  --mode=json \
  '继续未完成任务；先核验当前 Git 状态与任务权威文件。'
```

不要使用 `--print-thoughts` 作为 supervisor 依赖。`--hide-thinking` 只改变 TUI 展示，也不代表模型没有进行内部推理。

## 交互模式

确实需要多轮对话时使用 PTY 启动 `omp`，保存进程 session ID并轮询。优先用非交互 `-p` 完成普通 bounded task，减少 TUI 按键和确认状态的不确定性。
