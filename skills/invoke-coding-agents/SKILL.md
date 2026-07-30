---
name: invoke-coding-agents
description: Invoke, supervise, resume, and verify local external coding-agent CLIs such as Claude Code, Qoder CLI, Grok Build, Oh My Pi (OMP), OpenCode, and Codex CLI. Use when delegating implementation, plan review, code review, testing, or bounded research to another agent process; when a worker appears silent or stuck; when the actual provider/model mapping must be verified; or when multiple agent sessions must run without confusing projects, worktrees, or evidence.
---

# Invoke Coding Agents

把外部 coding agent 当成有明确输入、权限、session、工作目录和验收条件的受监督进程。不要只发送一句自然语言后等待结果。

## 先选择任务 profile

- **只读 reviewer**：读取代码、Git history、测试结果并独立核验；默认不授予写入、commit、push、SSH 或部署权限。
- **普通 worker**：只在指定 workspace/worktree 内实现一个有界任务；默认不授予 merge、push、deploy 或生产 mutation。
- **高风险 worker/reviewer**：先建立 task plan、authority、rollback 与验收 gate，再调用 provider。不要靠 CLI 的自动批准模式代替产品级 authority。

普通任务不要机械套用高风险仪式。高风险任务也不能因为 provider 支持 `auto`、`yolo` 或 bypass 权限就跳过 gate。

## 调用流程

1. **实时发现**
   - 运行 `command -v <binary>`、`<binary> --version` 和当前 model/provider 列表。
   - 使用实际解析出的 binary；不同 shell、GUI、PTY 与非交互进程的 `PATH` 可能不同。
   - 不把历史 model 映射、UI 标签或旧 session 当作当前 provider 事实。

2. **固定执行边界**
   - 指定唯一 `cwd`；跨仓库只添加确实需要的目录。
   - 写任务时列出允许修改路径、禁止事项、测试、最终输出和 hard stop。
   - 可写任务优先使用隔离 worktree。相同物理 agent 可以同时服务多个项目，但必须使用不同 session 和不同 workspace/worktree。

3. **创建可定位 session**
   - 优先使用 provider 支持的显式 session ID/name。
   - 保存 CLI 进程 ID、provider session ID、工作目录和 provider-native transcript/JSONL locator。
   - one-shot 优先使用非交互 print/run/exec 模式；确需多轮交互时才使用 PTY/TUI。

4. **使用结构化输出**
   - 在 provider 支持时使用 JSON/JSONL/stream-json。
   - 不把终端暂时无输出解释为卡死；按 [supervision.md](references/supervision.md) 关联进程、native event、artifact 和 Git 状态。

5. **验证实际身份**
   - 从 provider-native init/runtime/model event 或可信 proxy metadata 核对实际 model。
   - 调用参数只代表请求意图，不必然代表下游实际模型。

6. **验收与收口**
   - worker 自述、测试通过、reviewer verdict 和 operator acceptance 是不同证据。
   - 独立检查 allowlist、diff、测试、未授权 mutation 和 dirty baseline。
   - 记录最终 verdict、测试/部署 receipt 和 session locator；中间轮次按 retention policy 归档。

## Provider 路由

只加载当前要调用的 reference：

- Qoder CLI：读取 [qoder.md](references/qoder.md)。
- Claude Code / CC Switch：读取 [claude-code.md](references/claude-code.md)。
- Grok Build CLI：读取 [grok.md](references/grok.md)。
- Oh My Pi / OMP：读取 [omp.md](references/omp.md)。
- OpenCode：读取 [opencode.md](references/opencode.md)。
- Codex CLI：读取 [codex.md](references/codex.md)。
- 监督、JSONL、idle/dead 判断：读取 [supervision.md](references/supervision.md)。

不要为了调用一个 provider 而加载所有 provider 手册。

## Prompt 最小契约

每个派发 prompt 至少明确：

```text
角色：worker / independent reviewer
目标：一个可验证结果
cwd/worktree：绝对路径
允许读取：路径或 commit 范围
允许修改：精确 allowlist；只读任务写“无”
禁止：reset/clean/commit/push/merge/SSH/deploy/production 等当前未授权行为
验收：测试、diff、verdict 或 receipt
停止条件：越界、事实无法核验、需要新增 authority
输出：中文为主体，命令、路径、identifier、token 保留英文
```

长 prompt 优先写入 task-scoped 文件或使用 CLI attachment/file 参数，避免多层 shell quoting 改写内容。

## 权限原则

- CLI sandbox/permission mode 是执行护栏，不是业务 authority。
- 只读 reviewer 若需要 Bash，应只运行只读命令；若 provider 的非交互权限系统会拒绝 Bash，可以在外部隔离和严格 prompt 下使用 bypass，但必须在结束后独立核验零 mutation。
- 可写 worker 的 bypass/yolo 仅用于已授权的隔离 workspace；不得因此扩大 Git、网络、生产或部署权限。
- 不让 worker 自行批准自己的 plan、结果或 merge/deploy gate。
- 不读取、复制或要求 provider 暴露 private chain-of-thought。provider 公开的状态、工具调用和最终解释足以监督任务。

## 并行隔离

不同 session ID 能隔离 provider 对话，但不能单独保证项目安全。并行任务同时满足：

- 不同 provider session ID；
- 明确且正确的 project `cwd`；
- 可写任务使用不同 worktree 或互不重叠 allowlist；
- 每条任务线独立保存 prompt、native evidence 与 verdict；
- 不共用会被覆盖的临时文件、branch 或 deployment authority。

不要为每个任务新增复杂的全局租约实体；只有真实共享资源存在冲突风险时，才使用 Coordinate lease、channel binding 或其他持久 authority。
