# 源码与工程记录一致性

适用于需要在跨 worktree、长期分支和换会话时自动发现记录漂移的项目。
四入口共用一个纯 Python 标准库内核，复用已有正式文档、task locator 与状态权威。
检查能证明文件及其来源的对应关系；复核声明不独立证明作者理解正确或任务已验收。

## 采用与配置

先在现有 `harness-config.json` 的 `coverage` 段声明一组真实范围，固定受审采用起点。
示例中的提交与路径必须替换为项目实际值；不会自动采用全仓所有历史任务或 worktree。

```json
{
  "coverage": {
    "version": 1,
    "enabled": true,
    "adopted_at": "<reviewed-commit>",
    "source_roots": ["src/**"],
    "exclude": ["src/generated/**"],
    "defaults": {"warn_at": 1, "block_at": 3},
    "groups": [
      {
        "id": "payments",
        "sources": ["src/payments/**"],
        "record": {"item": "payments-012"},
        "rules": ["record", "review"],
        "policy": {"warn_at": 1, "block_at": 2}
      },
      {
        "id": "search",
        "sources": ["src/search/**"],
        "record": {"path": "docs/search.md"},
        "rules": ["record", "review"]
      }
    ],
    "handoff": true,
    "history_limit": 2000
  }
}
```

`record` 选择路径或已有 item，两者不能同时给出。item 使用同一 canonical plan resolver，
保留历史路径、双 locator 冲突检查及 Standalone 的外置计划。分支名和 `current` 仅作恢复线索。
路径模式以仓库为根，`*` 匹配一层，`**` 匹配任意层。圈定根中新增且未被任何组覆盖的源码
属于确定错误；重叠组分别核对。源码不能包含自身复核记录以形成循环，应明确拆分范围。

`record` 检查正式记录可用，是硬规则；`review` 按可配置阈值累计未复核源码变化。
关键组可以将 `block_at` 设为 1。缺 coverage、disabled 或坏配置时，显式新检查不返回 passed。
旧 `validate` 的 warning-only 兼容语义保持。配置只登记关系，不复制任务状态、计划正文或 owner。

## 四个入口与快照

```sh
<scripts>/harnessctl drift --snapshot worktree --format json
<scripts>/harnessctl remind --snapshot staged
<scripts>/harnessctl baseline --base <trusted-commit> --fingerprint <finding-id> --output <baseline.json>
<scripts>/harnessctl reconcile --item payments-012 --output <task-artifacts>/reconciliation.json
```

`drift` 默认只读工作区诊断；HEAD、index 与未暂存变化分开报告。
`remind` 默认读取实际 index，包括 `GIT_INDEX_FILE`。源码、文档、证据和候选配置均从冻结的
同一输入读取，未暂存修复不能帮助旧暂存内容通过。读取竞争、冲突、缺 Git 对象或必要历史
都报告 incomplete，不自动 fetch、改 refs、暂存、提交或执行配置中的命令。
源码身份遵守 Git 内建 text/EOL 转换，因此干净的 autocrlf checkout 不增加欠账；`read()`
仍保留物理原始字节。自定义 clean/process filter 不执行，快照遇到无法证明的转换、ident
或 working-tree-encoding 会报告 incomplete。

输出为 text 或相同结构的 JSON findings，包含作用域、证据、稳定指纹及建议动作。
退出码 0 表示无阻断（仍可能有 warning），1 表示确定违规或阈值阻断，2 表示检查不完整。
同时存在 error 和 incomplete 时保留两者，门禁均不通过。

## 核对记录与累计欠账

在该组的正式记录中保留一个小型结构化块。source digest 可从 `drift --format json` 的 group
取得；它是所选源码路径、类型、模式和内容身份的稳定投影，不要求提交记录自己的最终 SHA。

````markdown
```exharness-review
{
  "version": 1,
  "group": "payments",
  "rule": "review/v1",
  "scope_digest": "<reported-scope-digest>",
  "source_digest": "<reported-source-digest>",
  "decision": "reviewed-no-doc-change",
  "actor": "<reviewer>",
  "reason": "已核对付款失败分支及回归，现有行为文档仍准确。",
  "basis": {
    "parent": "<fixed-source-context-commit>",
    "review": "对照本次错误处理改动与原验收条件逐项核验。"
  },
  "item": "payments-012"
}
```
````

需要改文档时使用 `decision: updated`。只改日期、current 指针或无关段落不能成为新核对点。
`reviewed-no-doc-change` 只处理该作用域的语义欠账，不消除结构错误、交接错误或 incomplete。
理由必须说明实际复核依据，项目要求的独立审查继续走原审批流程。

欠账沿可证明的 first-parent 从受审起点或独立核对块的真实引入/刷新点累计：相关源码投影每变
一次计一次，空提交与无关提交不计，额外暂存变化计一次。源码 A→B→A 不把旧签收当作新签收。
刷新须更新实质复核依据。同提交更新源码和核对块可用，无最终 SHA 自引用。
核对点的机器依据是该独立块在实际历史中的首次引入/刷新及对应源码/范围；`basis.parent`
保留固定来源上下文，不要求等于 squash/rebase 后的新父提交，也不单独产生核对权威。
规则或范围变化不能无条件沿用旧证据；历史重写、浅克隆或扫描上限不能替换为“零欠账”。

## 受信 CI 与 hook

本地 hook 由项目现有 hook 管理器串接以下只读命令，不覆盖 `core.hooksPath`。

```sh
python3 <trusted-runtime>/consistency_cli.py remind --repo . --snapshot staged
```

PR 与 merge queue 由受信工作流固定 base、head 和实际 tested result：

```sh
python3 <trusted-runtime>/consistency_cli.py remind --repo <checkout> \
  --config <repo-relative-config> --snapshot ci \
  --base <trusted-base> --head <pr-head> --result <tested-result> \
  --integration merge --format json
```

merge/squash/merge-group 按实际结果投影计变化；fast-forward/rebase 需要可证明的实际集成历史，
按进入集成线的相关提交累计，证据不足时报 incomplete。不能假设 checkout HEAD 就是目标，
也不能在每个小 PR 将旧欠账归零。

checker 来自已受审固定版本。第一次采用新工具是显式 bootstrap，不能声称旧 base 已运行一个
尚不存在的能力。工具锁住 base 的既有覆盖义务和阈值，再检查候选新增/加严及基线清理。
新增源码可在同 PR 加有效覆盖；删除规则、放宽阈值、扩 baseline 不能帮该 PR 绕过旧义务。
纯策略迁移按原有 protected review 评审后对后续变更生效，不新建授权系统。

维护者将真实执行的 job 设为 required；skipped/neutral 不能视作完成全检。工具不自行修改
分支保护。`consistency-contract` 区分实例能力、配置和本地 hook 观测；本地不能证明远程
required CI 的设置。全局 skill、项目复制脚本、有效配置和部署验收分别核对。

## 基线与对账

baseline 只显式输出选中的、固定受信历史快照可复现的旧 finding 指纹，不自动接收当前所有
问题，不产生已复核声明。配置 `coverage.baseline` 指向审阅后的仓库相对 JSON 文件。
baseline 与 reconcile 的 `--output` 只新建提案工件；已有完全相同内容是幂等 no-op，已有
不同内容会拒绝覆盖。更新提案使用新工件路径，审阅后沿项目原流程修改正式文件。
新证据、新范围、规则语义变化不能复用旧指纹；必要输入、生命周期错误不可豁免。
修复后同步删失效条目，随后复发仍须可见。候选新增基线在固定 base 复现，修复与清理同 PR 可通过。

reconcile 默认生成 task-scoped 草稿，列明源码锚点、变化、现有记录、未知项与建议落点。
Standalone 显式应用：

```sh
<scripts>/harnessctl reconcile --item payments-012 --apply <draft.json> --confirm --actor <owner> --session <session>
```

应用前重读来源、正式记录原始字节和既有 writer/lease；并发变化拒绝，不覆盖。观察采用有界追加，
若不遵守租约的编辑器恰在最终核验后写入，保留其内容并报告冲突，需检查已追加的观察后再试。
重复应用同一草稿
保持幂等。只在原记录追加观察说明，不推断 done、批准或部署状态，不增事件类别。
计划改变后原 packet 字节审批自然失效，须按原生命周期重新核验。
Coordinate-managed 只输出交给既有受控入口的草稿，不能把本地 export/events 或文件写入
冒充 DB-live 状态。

## 外置计划与交接

本地工作区保留原外置 canonical plan，报告其来源。CI 需要受信调用方提供已获准外部仓库的
固定 revision 只读 checkout/mount 与精确 path/blob，或已有足够的受信 receipt。
通过 `--external-records <caller-manifest>` 提供固定输入，例如：

```json
{"version": 1, "records": [{
  "locator": "<original-absolute-task-locator>",
  "repo": "<authorized-fixed-checkout>",
  "revision": "<fixed-external-commit>",
  "path": "<repo-relative-record-path>",
  "blob": "<exact-git-blob>"
}]}
```

原 locator 与受信挂载可以位于不同目录，映射由受信调用方提供，实际 revision/path/blob 需核对。
外置复核块可在 `basis.source_commit` 明确指定已提交源码的精确锚点；内核核验它在本项目采用后
的 first-parent 历史上，并与 scope/source digest 对应，随后从该固定点累计，而非每次读文件重签。
未提交新内容不能借旧 source_commit 清账。仅有当前外部文件而没有可复算源码锚点时，复核检查
列为 incomplete；记录存在性仍可单独核验。候选自报 hash 或本地镜像不证明
Coordinate DB 最新状态。必需证据缺失时报 incomplete，不复制第二份正文或静默排除该组。

采用后 handoff 包写到任务正式工件根中的 `handoff-<item>.md`，绑定 item、接收人、计划原始
字节，关联实现范围还绑定源码投影。accept 在租约/状态变更前核验；失配时刷新或拒收。
新 handoff 同时保留原始计划摘要与 Git 对象身份，用声明的 text/EOL 转换核对暂存计划；
旧 review/closeout 的 exact-byte 审批语义不变，不自动改写历史哈希。

```sh
<scripts>/harnessctl handoff <item> <same-target> --refresh
```

refresh 只更新同一待交接任务的派生包/locator，不重复指派、释放租约或发业务动作。旧路径
可读并可显式刷新迁移；共享 progress 摘录仅为生成时观察，其它任务进展不会使交接过期。
派生包不得覆盖任何 canonical plan 或无关已有文件；只有同任务原派生包可以更新。

已有业务项目先只读对照，维护者确认具体范围、阈值及外部证据入口后再逐步采用。
升级 skill 不自动安装业务 hook、替换实例规范或更改服务端状态。
