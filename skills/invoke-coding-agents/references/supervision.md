# 外部 Agent 监督协议

## 证据层级

从强到弱关联：

1. provider-native session event/JSONL 的 init、model、tool、timestamp、stop reason 与最终结果；
2. OS process 是否存在、CPU/IO 与退出码；
3. task artifact、测试报告和 Git diff 是否推进；
4. agent 的自然语言状态声明；
5. 终端暂时没有输出。

任何单一证据都不应独立决定 worker 是否正常。文件没有变化可能表示仍在读取或规划；JSONL 有活动也不证明最终结果正确。

## 两次观察规则

对安静 session：

1. 记录第一次观察时间、native JSONL size/mtime、最后安全 event 类型、进程状态和 artifact/Git 状态。
2. 等待一个与任务相称的短间隔，通常 10～30 秒；不要做超过 60 秒的阻塞等待。
3. 第二次读取相同指标。
4. JSONL/tool event 或 artifact 有推进则判定 active。
5. 进程存在但两个周期无推进，只判定 possibly idle/stalled，先检查 permission prompt、rate limit、context compaction、网络或测试运行。
6. 只有进程已退出且无成功结果，或存在明确 fatal/error/terminal event，才判定 dead/failed。

## 只读取安全字段

允许监督：

- session ID、cwd、model、provider；
- event type、tool name、timestamp；
- exit code、stop reason、rate-limit/error category；
- artifact path、Git status、diff stat、测试摘要；
- 最终 text/verdict。

不要读取、复制或转述 `thinking`、private reasoning、credential/token、raw secret scan 或无边界 dirty patch。

## 模型核验

按以下顺序判断实际 model：

1. provider-native init/runtime/model-change event；
2. 当前请求对应的可信 gateway/proxy metadata；
3. CLI 结果中的 model usage；
4. 调用参数；
5. UI 标签或历史配置。

如果层级冲突，保留原始值并标明 `REQUESTED_MODEL` 与 `OBSERVED_MODEL`，不要强行统一。

## 并行任务

为每条任务线建立最小 tuple：

```text
(project, cwd/worktree, provider, provider_session_id, task_id, evidence_locator)
```

相同物理 agent 但不同 session 不会天然混淆 provider 对话；真正需要防护的是共享 cwd、branch、临时文件、channel、deployment target 或 authority。

## 完成判断

worker 完成至少需要：

- 进程正常退出或明确 end-turn；
- 输出满足任务 contract；
- 修改范围没有越界；
- 必需测试有可复核结果；
- 没有未授权 commit/push/deploy/生产 mutation。

高风险任务还需要独立 reviewer 和 operator gate。Reviewer 的 `APPROVE` 只在 prompt 明确的范围内有效，不能隐式授权后续 mutation。

## 恢复与纠正

- 小修正且原 session 状态可信：使用 provider resume。
- 需要独立 review：创建 fresh session，不 resume worker。
- session 上下文已污染、模型映射改变或工作目录错误：创建 fresh session，并从 canonical task 文件恢复。
- 不向 correction prompt 粘贴期望答案；提供可复核事实、失败测试和明确 acceptance。
