# 事件、packet 与审查新鲜度

仅在生成/消费 packet、写 verdict 或执行 runtime closeout 时读取。使用 Coordinate 时，操作通过其 lifecycle 入口；下面的 harnessctl 描述 Standalone 语义，不授权绕过 managed authority。

## Event And Packet Protocol

high-risk 模式或显式启用 runtime workflow 时，关键动作必须同时满足：

1. 更新对应的 harness 状态或 packet。
2. 写入 deployment profile 对应的权威 event store。
3. 输出一行可转发到 Discord/KOOK 的事件 header。

ordinary 模式不强制此三联动作。

推荐可见事件类型：

```text
[ASSIGN]  task=<id> actor=<operator> target=<agent> status=assigned
[ACCEPT]  task=<id> actor=<agent> status=running
[RESULT]  task=<id> actor=<agent> target=<reviewer> status=closeout_requested
[REVIEW]  task=<id> actor=<reviewer> status=approved|changes_requested|blocked
[BLOCKER] task=<id> actor=<agent> target=human status=blocked
[CLOSE]   task=<id> actor=<operator> status=done
```

事件落点由 deployment profile 决定。Standalone 的 `events.jsonl` 是 append-only
event log / outbox candidate，当前脚本只写 `publish_status=local_only`；
Coordinate-managed 的权威事件写入 Coordinate DB，本地 `events.jsonl` 只是
fallback/export。事件使用稳定字段并只保存摘要与 artifact paths，不复制长计划或
长审查全文。

Packet 状态机：

- `handoff-packet.md`: 用于转交给另一个 agent；生成时释放旧 owner/lease，记录 `workflow.handoff_target`。
- `review-packet.md`: 用于计划或结果审查，请求 reviewer 输出结构化 decision；high-risk
  嵌入完整 plan snapshot，ordinary 为 lightweight（不嵌 plan 正文，仍带 freshness metadata）。
- `blocker-packet.md`: 表示 item 进入 `blocked`；生成时释放 owner/lease，记录 `workflow.unblock_owner`，必须通过 `unblock` 或明确 override 解阻。
- `closeout-packet.md`: 只表示 ready for closeout review，不允许直接把 item 标为 `done`；
  high-risk 嵌入完整 plan snapshot，ordinary 为 lightweight（同上）。

**派生制品新鲜度契约**：`review-packet.md`、`closeout-packet.md` 与
`current/task_plan.md` 在文件顶部、首个 fenced plan snapshot 之前写入固定
`## Freshness Metadata` 小节（`generated_at`、`source_plan_sha256`、
`canonical_plan_path`、`checklist_item`），作为相对 canonical plan 的 bounded
evidence。canonical plan 文件仍是正文 authority，hash 只是 locator/evidence；
plan 正文内出现形似 freshness header 的内容不会改变解析结果。

packet 正文按 effective mode 裁剪：`high-risk`（含 legacy missing mode）嵌入完整
canonical plan snapshot；`ordinary` packet 不嵌 plan 正文，只保留 `Workflow mode`
说明与 "plan body omitted; read the canonical plan at the locator" 提示，但 freshness
metadata、exact packet bytes、plan hash/locator、checklist_item 校验不弱化。freshness
gate 同样按 mode 裁剪：ordinary 允许 snapshot 缺失，但 packet 若含 snapshot 仍校验其
一致性；ordinary → `high-risk` 升级后，旧 lightweight packet 因缺 snapshot 自动
fail closed，必须重新生成 packet 再 verdict。

**snapshot 解析边界（机器语义）**：机器所称 "snapshot" 特指 `## Canonical Plan
Content` section 内第一个**闭合** fenced block（以等长反引号 fence 关闭）的内容；
section 内 fenced block 之外的额外 prose 不影响解析。ordinary packet 没有该闭合
block 时按 lightweight 处理（合法，不校验）；存在该闭合 block 时一律校验其与当前
canonical plan render 的一致性；重复 `## Canonical Plan Content` heading 一律
fail closed。未闭合 fence、额外 prose 或首个闭合 block 之后的呈现内容不属于结构化
snapshot，不扩张为 Markdown parser 责任——它们仍是 Reviewer 实际阅读并 hash 的
exact packet bytes 的一部分，且 Reviewer 仍须打开 canonical plan 阅读正文。机器只
证明 reviewer 绑定了 exact packet、packet 指向且哈希匹配当前 canonical plan，不
宣称能证明认知阅读。

- `review-result` 只能绑定 reviewer 实际阅读的 exact packet bytes：必须传
  `--reviewed-packet-sha256 <64-hex>`（对 packet 文件自行计算，不得回抄 header；
  协议只要求 exact bytes SHA-256，可用 `shasum -a 256`（macOS）/
  `sha256sum`（Linux）/ PowerShell `Get-FileHash -Algorithm SHA256`（Windows）
  计算，平台命令只是示例，不是 authority），且仅在 workflow phase 为
  `review_requested`（绑 review packet）或 `closeout_requested`（绑 closeout
  packet）时可用；其他 phase fail closed。
  verdict 写入前会校验 packet 字节、`checklist_item`、canonical plan locator、
  `source_plan_sha256` 与内嵌 snapshot，任何失败都不改 checklist。
- `harnessctl validate` 对 legacy packet/pointer、`doing` item 缺少可读 canonical
  plan，以及 active review/closeout phase 缺少绑定 packet 只输出 `WARN`；关闭后的
  `current/*` cache 和历史 events 不进入该检查。新 verdict 必须先重新生成 packet 再审查。
- `mark-done` 在 closeout 后重新验证 checklist 中保存的 `reviewed_packet_sha256`、
  packet 当前 bytes 与当前 plan，approval 后 plan/packet 漂移会 fail closed；
  `--force --reason` 保持为有审计事件的显式 break-glass，可越过 freshness 但必须
  提供非空 reason。

如果目标 agent 不能接手，应运行 `decline <item-id> <actor>`，而不是沉默丢弃 handoff。长任务超过 TTL 时，当前 owner/session 应运行 `renew-lease <item-id> <owner> <session-id>`，避免其他 agent 误判 lease 过期。

只有 reviewer 通过 `review-result <item-id> <reviewer> approved --reviewed-packet-sha256 <64-hex>` 写入 closeout 审查结论后，operator/human 才能运行 `mark-done`。`mark-done` 会释放 owner/lease 并清理 stale current pointer。`--force --reason` 只用于明确 human override，并会写入 event metadata。
