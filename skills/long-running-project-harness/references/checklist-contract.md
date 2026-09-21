# Checklist 字段与校验契约

仅在登记/修改 checklist、改变风险模式或排查 validator 时读取。开工顺序见 [workflow.md](workflow.md)，packet 新鲜度见 [events-and-packets.md](events-and-packets.md)。

## MVP Checklist 规则

使用 JSON 维护 checklist，因为它容易 diff，也容易被 agent 稳定更新。

**文件名权威规则**：新项目使用 `harness-checklist.json`；`mvp-checklist.json` 是 legacy 文件名，
继续完整可用。runtime 只有唯一 resolver 决定当前 checklist：只有新名/只有旧名都正常读写；
两者都没有或同时存在时 read/mutation fail closed（doctor 只诊断 dual authority，不宣布哪份
active）。从旧名切换到新名运行 `harnessctl migrate-checklist`（同目录 rename，不改 bytes，不提交 Git）。

**重要节点登记规则**：operator 需要新增或调整重要节点时，用 `harnessctl` 落盘，不要手改 JSON：

- `harnessctl add-item <id> --title <text> --acceptance <text> [--priority p0|p1|p2] [--plan <path>] [--dependency <id>]... [--handoff <text>] [--mode ordinary|high-risk]`：只创建 `todo` 节点，不创建 plan 文件、不自动 start、不写 lease/review/workflow 占位对象。`--plan` 文件必须已存在；`--mode` 会写入 mode-only workflow（`{"mode": ...}`）用于开工前显式分类，不传时保持 legacy 无 workflow shape。
- `harnessctl update-item <id> [--title] [--acceptance] [--priority] [--plan] [--verification] [--handoff] [--add-dependency] [--remove-dependency] [--mode ordinary|high-risk]`：不能改 `status`/`owner`/`selected_in_session`/`lease`/`workflow.status`/`review.decision`；未触碰字段与未知兼容字段原样保留。`--mode` 是唯一 `workflow.mode` transition 入口。
- 每个 mutation 都先校验 current、内存变更、再校验 candidate、atomic 写入；commit 前失败原 bytes 不变。
- `deployment_profile=coordinate-managed` 下裸 add/update fail closed（走 Coordinate 入口）；`migrate-checklist` 需要显式 `--ack-managed-profile`（只是防误操作确认，不是 authority token）。

每个 item 至少包含：`id`、`title`、`status`（todo/doing/done/blocked）、`priority`（p0/p1/p2）、`owner`、`selected_in_session`、`updated_at`、`dependencies`、`blocked_by`、`blocked_reason`、`acceptance`、`verification`、`handoff`。

多 agent 兼容扩展字段（推荐）：`workflow`（assigned/running/closeout_requested/changes_requested/closed，可选 `mode`）、`lease`（acquired_at/expires_at/ttl_minutes）、`artifacts`（plan/handoff_packet/review_packet/closeout_packet/branch/pr）、`review`（decision 取 approved/changes_requested/blocked/null；freshness evidence 为 `reviewed_packet_sha256`、`source_plan_sha256`、`reviewed_packet_locator`，由 `review-result` 写入）。

**workflow.mode 两档协议（I9）**：`workflow.mode` 只取 `ordinary` / `high-risk`；
缺失（legacy）时 effective mode 一律为 `high-risk`，不批量回写 legacy item，不新增
第三档，也不是风险评分引擎。

- mode-only shape：`workflow` 不含 `status` 时，仅允许 coarse `todo` 且 key set 恰好为
  `{mode}`；`workflow={}`、`doing + mode-only`、`mode + branch/updated_at 但无 status`
  等残缺 lifecycle 一律校验失败。含 `status` 时继续走既有 lifecycle schema。
- `add-item --mode` 在开工前显式分类（mode-only workflow）；`update-item --mode` 是唯一
  transition 入口，不允许手改 JSON。允许：explicit `ordinary` → `high-risk`（任何未
  done 状态）；legacy missing mode → explicit `high-risk`；legacy 未开始（coarse
  `todo`，workflow status 缺失或 `todo`）→ explicit `ordinary`。拒绝：explicit
  `high-risk` → `ordinary`（降级）；已开始/释放/阻塞/review/closed 的 legacy →
  `ordinary`；相同 explicit mode no-op；`done` item 任何 transition。拒绝时原 checklist
  bytes 不变；unknown compatible workflow fields 保留。
- mode mutation 总是刷新 item `updated_at`；仅当 workflow 已含 lifecycle `status` 时才
  刷新 `workflow.updated_at`。mode-only workflow 只改 `mode`，不新增 timestamp/status，
  首次进入 lifecycle 时由 `ensure_workflow` 初始化。
- 机器化的是 mode 与 packet/freshness 行为，不是自动风险检测。Operator 在 ordinary item
  中发现部署、secret、authority、schema、不可逆 mutation 等高风险动作时，必须先
  `update-item --mode high-risk`、更新 plan，并重新生成受影响 packet；runtime 不假装能
  理解任意 shell 命令的风险语义。

**机器时间戳契约**：runtime 自动写入的 machine timestamp——checklist root/item/workflow/review 的 `updated_at`、packet 的 `Updated at`、activate 自动 scaffold 的 plan `Updated at`——一律使用完整 UTC ISO-8601 `YYYY-MM-DDTHH:MM:SSZ`（`harness_common.iso_z()`），保证可比较且时区语义唯一。legacy `YYYY-MM-DD` 继续被 validator 接受、可正常读取，历史节点不会被全量重写。人类叙述性日期（如 Session Log 的 `### YYYY-MM-DD` 标题、packet 正文中的自然语言日期）按本地语境保留，不强制机器化。

Branch 字段协议：`workflow.branch` 是工作分支，通常由 `git.branch_namespace` 生成；`artifacts.branch` 与其保持一致；`artifacts.pr` 是 PR 链接；远程 agent 不得改非自己 namespace 下的 branch，除非 human 明确授权。

Canonical plan locator：一个 item 只有一个语义答案（`plan_path` 或 `artifacts.plan` 之一，或两者标准化后相同）；冲突时 fail closed，不静默选择。没有 locator 时 activation 可以 scaffold 默认
`tasks/<id>/plan.md`；已有 locator 但文件缺失时 fail closed，不偷偷重建。Standalone 允许 operator
在 checklist 中明确选择 external absolute plan locator（repo-local 协议 + 外部 task artifact root 的
split layout）；这是 operator 选择，只做 lexical/regular-file 校验，不构成 containment 安全保证。

除非验证结果已经记录在 `progress.md`，否则不要把 item 标成 `done`。
除非用户明确要求 override，否则不要启动 dependencies 未完成的 item。
除非 reviewer 已 approved，coding agent 不应自行把 item 标为 `done`；使用 `closeout` + `review-result --reviewed-packet-sha256 <64-hex>` + `mark-done`。
如果 item 被其他 owner 的 active lease 占用，不要覆盖；选择其他 item，等待 operator，或使用带 reason 的 human override。

模板见 [planning-files-template.md](planning-files-template.md)。

## Checklist 校验

创建或修改 checklist（`harness-checklist.json` 或 legacy `mvp-checklist.json`）后，优先运行校验脚本：

```bash
python3 "$CLAUDE_SKILL_DIR/scripts/validate-checklist.py" path/to/checklist.json
# 实例化后：不传路径时走 resolver 决定当前 checklist
scripts/harness/harnessctl validate
```

校验只有一份 semantic implementation（`references/scripts/validate_checklist.py`）；顶层
`scripts/validate-checklist.py` 只是 thin wrapper，两者对相同输入保持 stdout/stderr/exit code parity。
脚本只读取和校验 JSON，不会修改文件。它检查必填字段、顶层字段类型、`status`、`priority`、`doing`
ownership、`done` verification，以及 `dependencies` / `blocked_by` 引用是否存在。

### 显式 item 引用 lint（I10）

`harnessctl validate` 还会在 JSON/locator/freshness 检查后，对 canonical harness root 下的 `.md`
文件做 warning-only 的显式 item 引用 lint，未知 ID 只输出 `WARN:`，不改变退出码、不阻止 mutation：

- 覆盖三种显式形式：inline code `` `item:<id>` ``（反引号内支持含空格 ID）、裸 `item:<token>`
  （只支持不含空白的 ID，剥句末标点与 `*` / `**` emphasis 标记；underscore emphasis 不属 V1
  grammar，尾随 `_` 保留在 candidate 中）、canonical plan 路径 `tasks/<id>/plan.md`
  （带 harness 前缀的 `docs/project-harness/tasks/<id>/plan.md` 同样识别）。
- 不猜任意 prose：历史裸 ID（如 `mvp-999` 不带前缀）不覆盖；fenced code block 内容不扫描；
  占位符 `item:<id>` / `tasks/<id>/plan.md` 忽略；不含显式 grammar 的 URL、命令与空 `item:` 不误报
  （URL 中真正含 `tasks/<id>/plan.md` 的仍会 lint）。
- 新计划中的跨 item 引用请使用上述显式语法（模板已要求），让漂移可被机械发现。
