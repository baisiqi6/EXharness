# ZCode CLI

这里说明 Operator 直接调用本机 ZCode CLI 的最小契约。若任务需要 Coordinate 的 durable job、lease、receipt、跨宿主机执行或 Discord delivery，应使用 Coordinate/MultiNexus 已注册的 ZCode executor；不要在本 reference 里复制第二套控制面。

## 实时发现

ZCode 可能没有安装成 `PATH` 中的 `zcode`。macOS app bundle 的常见入口是：

```text
/Applications/ZCode.app/Contents/Resources/glm/zcode.cjs
```

每次调用前核验当前机器上的真实入口和版本，不把这个示例路径当成跨主机契约：

```bash
if command -v zcode >/dev/null 2>&1; then
  zcode --version
else
  ZCODE_JS="${ZCODE_JS:-/Applications/ZCode.app/Contents/Resources/glm/zcode.cjs}"
  test -f "$ZCODE_JS"
  node "$ZCODE_JS" --version
fi
```

当前已核验的 `0.16.3` 支持 `--prompt`、`--cwd`、`--mode`、`--attach`、`--json`、`--resume`、`--max-turns` 以及 tool allow/deny list。升级后先重新读取 `--help`；不要假设 vendor contract 永久不变。

不要把 `~/.zcode/cli/config.json` 整份打印到日志、prompt 或 review packet。它可能同时包含 model metadata 与 credential。只提取完成本轮身份核验所必需的非敏感字段。

## 独立 reviewer

ZCode 的 headless `--prompt` 默认 permission mode 是 `yolo`。只读 review 必须显式选择更窄的 mode 和 tools；默认使用新 session，不恢复 worker session：

```bash
ZCODE_JS="${ZCODE_JS:-/Applications/ZCode.app/Contents/Resources/glm/zcode.cjs}"
node "$ZCODE_JS" \
  --prompt '读取附件并独立审查。禁止编辑、提交、push、SSH、deploy 和生产 mutation。按 P0-P3 输出 findings，最后给唯一 verdict。' \
  --attach /absolute/task/review-request.md \
  --cwd /absolute/repo-or-worktree \
  --mode plan \
  --allowed-tools 'Read Grep Glob' \
  --max-turns 20 \
  --json \
  --no-color
```

`plan` 和 tool allowlist 是执行护栏，不是不可绕过的 sandbox，也不授予业务 authority。只读 reviewer 需要 Git 或测试证据时，优先由 Operator 在外部独立执行并把结果作为附件提供。确需让 ZCode 执行 shell 时，只能在隔离 worktree/snapshot 内授予有界权限，并在结束后检查 Git 状态、允许修改路径和外部副作用。

若当前 CLI 的 tool 名称与示例不一致，以实时 `--help` 和 runtime tool registry 为准；无法建立窄 allowlist 时 fail closed，不要回退到 `yolo`。

## 有界 worker

可写任务只在已授权的隔离 worktree 内使用 `edit` 或经核验后更合适的窄 mode，并把完整任务契约放入 attachment：

```bash
ZCODE_JS="${ZCODE_JS:-/Applications/ZCode.app/Contents/Resources/glm/zcode.cjs}"
node "$ZCODE_JS" \
  --prompt '严格按 worker bootstrap 实现；越过 allowlist 或需要新增 authority 时立即停止。' \
  --attach /absolute/task/worker-bootstrap.md \
  --cwd /absolute/isolated-worktree \
  --mode edit \
  --max-turns 40 \
  --json \
  --no-color
```

先用一次无副作用的小任务核验当前版本各 mode 的真实能力。不要仅凭 `build`、`edit`、`plan` 的名称推断权限，也不要用 `yolo` 代替明确的 allowlist、Git/网络边界或 merge/deploy authority。

## Model 与 native evidence

ZCode 的 model/variant 由当前 session 或本机配置选择，`0.16.3` 没有通用的 headless `--model` 或 reasoning flag。可以把 reviewer 的请求配置为当前偏好的 `GLM-5.3`、reasoning variant `max`，但必须区分三层事实：

1. Operator 请求的 model/variant；
2. ZCode 当前安全提取出的非敏感配置或 `/model` 状态；
3. provider-native runtime event 实际证明的下游 model/variant。

`0.16.3 --json` 的稳定可用字段包括 `sessionId`、`response` 和 `projection.status`/`projection.turnCount`，它们不能单独证明实际 model。若本轮没有可信 runtime model evidence，就把 actual model 标为 `UNVERIFIED`；不得把 UI 标签、配置值或历史映射写成“实际使用了 GLM-5.3 Max”。发生 fallback 或 identity mismatch 时，应显式报告并让 Operator 决定是否接受结果。

保存本轮 stdout JSON 的受控 locator 和 `sessionId`。监督只读取 session 状态、turn count、工具名、时间戳和最终文本，不转述 private reasoning，也不长期保存不必要的 tool-result artifact。

## 精确恢复

对同一任务做有界纠正时，使用先前 JSON 返回的精确 `sess_...`：

```bash
ZCODE_JS="${ZCODE_JS:-/Applications/ZCode.app/Contents/Resources/glm/zcode.cjs}"
node "$ZCODE_JS" \
  --resume "$SESSION_ID" \
  --prompt '只处理 correction attachment 中的未完成项；先核对当前 worktree，不重复已完成工作。' \
  --attach /absolute/task/correction.md \
  --cwd /absolute/repo-or-worktree \
  --mode plan \
  --json \
  --no-color
```

示例沿用只读 `plan`。如果恢复的是可写 worker，必须由 Operator 重新选择已授权的窄 mode；不能因为旧 session 曾有写权限就自动继承。

多项目并行时不要使用 `--continue` 猜测当前目录的最近 session。恢复前重新核验 `cwd`、Git 状态、任务边界和 authority；session history 不是当前 workspace 状态的权威来源。

## Direct CLI 与 managed executor

- Operator 在当前宿主机直接做一次性 review/worker 调用：使用本 reference。
- 项目已经由 Coordinate 管理，且需要 job/attempt、provider session、delivery、lease 或跨宿主机恢复：通过 scoped Coordinate authority 选择已注册的 ZCode executor。
- EXharness checklist 记录的是重要任务节点和 plan，不维护 provider 清单，也不因新增 ZCode 创建第二份 agent registry。

两种入口最终都必须保留相同边界：唯一 `cwd/worktree`、独立 provider session、明确 authority、可定位 native evidence，以及 Operator 的最终验收。
