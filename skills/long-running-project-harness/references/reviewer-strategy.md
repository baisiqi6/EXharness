# Reviewer 策略

Reviewer 的职责是帮助 Operator 回到真实问题和产品目标，而不是机械执行 checklist，
也不是为了证明审查有价值而制造 finding。独立审查的核心是判断与 mutation authority
分离；它不等于每一轮都必须更换 Reviewer、模型或 session。

## 1. 先选择上下文模式

根据本轮审查目的选择一种模式，并在 verdict 中说明选择理由：

- **continuity**：沿用同一 Reviewer session，适合验证上一轮 finding 的连续修订。
  Reviewer 可以保留问题演进，但必须重新读取当前代码、diff 和验证证据，不得用旧
  verdict 代替本轮核验。
- **fresh**：使用上下文更纯净的 Reviewer session，适合争议判断、明显锚定风险、架构
  转向或高风险最终 closeout。只提供完成判断所需的事实，不灌入历史结论。
- **limited-fresh**：使用新 session，并提供底层目标、用户约束、canonical plan、当前代码
  与真实 diff、non-goals 和必要证据，但不提供前几轮 verdict 或已被取代的审查叙事。
  普通最终 closeout 默认优先采用此模式。

上下文选择服务于审查目的，不作为仪式。若 continuity 足以可靠验证一个局部修复，就不
重复启动多个 Reviewer；若历史结论可能形成锚定，仅仅换模型但复制全部旧 verdict 也不算
fresh review。

## 2. Reviewer 要回答的问题

Reviewer 从以下层次判断实现，而不是只对照表面指标：

1. 用户真正要解决的问题和产品初心是什么？
2. 当前实现是否直接解决了这个问题，还是只满足了代理指标？
3. 是否存在 authority 更清楚、状态更少、局部性更强的实现？
4. 防御代码是否对应可证明的真实风险，还是为假想反例堆叠复杂度？
5. 是否遵守第一性原理、奥卡姆剃刀、最小机制和局部修改原则？
6. 需求、代码、测试、文档、receipt 与真实 runtime evidence 是否一致？
7. 哪些代码、字段、状态或流程可以删除、合并或推迟，而不损害核心正确性？

“更简单”不是为了减少行数；只有当更小的实现同样覆盖真实问题、failure mode 和 authority
边界时，才应作为改进建议。不要为了删而删，也不要把未来可能性自动升级为当前 P1。

## 3. 输入契约

Reviewer prompt 至少提供：

- 底层目标、产品动机和用户约束；
- canonical architecture、source of truth 与不可破坏的 authority boundary；
- 本轮真实代码、diff 和完成判断所必需的历史；
- 明确的 non-goals 和允许的读取、mutation 范围；
- 当前测试、runtime、Git 或 receipt 证据及其来源；
- 本轮 context mode 及选择理由。

默认 Reviewer 是只读角色。读取更多上下文、复用 session 或更换 session 都不会自动授予
commit、merge、push、deploy、delete 或 production mutation authority。

## 4. Finding 与 Verdict

只报告可执行且有实质影响的 finding。每项 P0-P3 finding 至少说明：

- **Evidence**：可定位的代码、diff、测试或 runtime 事实；
- **Impact**：它会破坏哪个真实目标、契约或 failure boundary；
- **Minimal counterexample**：能复现风险的最小场景；
- **Minimal correction**：不扩大范围的最小修正。

明确区分 code fact、worker/reviewer claim、receipt、独立验证的 runtime fact 和
`UNVERIFIED`。没有实质风险时应输出 `APPROVE`；不得为了保持“严格”而制造问题。

常用 verdict：

- `APPROVE`：目标、边界和证据一致，无需阻塞修正；
- `CHANGES_REQUESTED`：存在可执行的阻塞 finding；
- `BLOCKED`：缺少完成判断所必需的事实或 authority，且无法安全继续。

## 5. 连续修订与最终收口

- 针对上一轮 finding 的局部修订，可由同一 Reviewer 在 continuity 模式下复核。
- 架构转向、争议结论、明显锚定风险或高风险 closeout，使用 fresh；一般最终 closeout
  优先 limited-fresh。
- Reviewer verdict 是证据，不是最终 mutation authority。Operator 仍需核对实际 diff、测试、
  allowlist 和 authority 后才能接纳结果或推进 lifecycle。
