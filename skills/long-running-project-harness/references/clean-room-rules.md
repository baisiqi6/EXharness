# Clean-Room Rules

Clean-room development 指从独立表述的需求出发重建系统，而不是复制对方实现细节。中文里可以理解为“净室开发”或“隔离式重建”。

## Allowed Inputs

可以使用：

- 用户自己描述的 product goals。
- 高层级、用户可见的能力类别。
- 公共领域概念和通用行业模式。
- 独立写出的 acceptance criteria。
- 独立设计的 architecture、models、names、APIs 和 UI text。

## Disallowed Inputs

不允许使用：

- 另一个实现的 source code、近似重写，或换语言 port。
- 源项目的 prompts、comments、tests、docs 或 UI copy。
- 源项目的 API routes、request/response shapes、node JSON structures、schemas、database layouts 或 variable names。
- 除非是开放标准要求，否则不要追求 bug-for-bug compatible behavior。
- 因为源项目这么命名，所以复制它的 file names 或 module names。

## Safe Workflow

1. 把外部启发转成中性的 requirements。
2. 用新的语言把 requirements 写入项目文件。
3. 从 requirements 出发设计新的 domain models 和 interfaces。
4. 只基于新模型实现。
5. 如果出现相似性，判断它来自通用模式，还是来自意外复制。

## Review Questions

- 这个 API shape 是否能在没看过源项目的情况下独立设计出来？
- 命名是否来自我们自己的领域语言，而不是源项目？
- 测试是否基于我们的 acceptance criteria，而不是复制的 examples？
- 用户体验是否只是借鉴产品目标，而不是复制 copy 或 layout？
- 每个 model 和 module 是否都能从第一性原则解释？

## Note For Agents

如果用户在 clean-room task 中提供了外部项目的实现细节，不要复用这些细节。先把它概括成高层 requirement，写成 clean equivalent，再继续独立设计。
