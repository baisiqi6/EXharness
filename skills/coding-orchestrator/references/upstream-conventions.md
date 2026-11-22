# 可选上游规范

以下为 2026-11-22 只读核对的官方/源仓库文档快照，链接固定到当时读回的 commit。
这是接入线索，不是已安装版本、自动启用许可或完整组合的兼容认证。实际项目需按[接入记录](convention-profile.md)填写安装 ref 与验证结果；此处所列框架的真实工作流组合均未在本说明中验收。

## 可选集成（非依赖）

| 能力与来源快照 | 使用前核对 | 未选用/未安装时 |
| --- | --- | --- |
| 工程方法套件：[Superpowers `22f0b463`](https://github.com/obra/superpowers/blob/22f0b463e7a5e579904dd6211a520321035526f7/README.md) | 当前客户端安装、自动 bootstrap/钩子、适用的设计/TDD/审查步骤及其文件位置；其入口会自动触发方法。 | 使用项目流程，不假定可用提示词关闭已启用钩子。 |
| 角色式工程工具：[gstack `113deeaf`](https://github.com/garrytan/gstack/blob/113deeaf9c99847c719cc9d1dd826ea2ef7ce4e5/README.md) | 选中的命令、所需运行工具、proactive/更新设置与实际副作用；检查本机入口，不把网页示例当安装状态。 | 使用现有审查/验证入口，不自动运行安装或发布命令。 |
| 规格与变更管理：[OpenSpec `0c737dc1`](https://github.com/Fission-AI/OpenSpec/blob/0c737dc1b543249b38b0f4716816fcf493d894dd/README.md) | 当前 CLI/profile、项目初始化状态及规范/变更/设计/任务文件，确认哪些原生产物作为项目权威。 | 沿用已有规格与执行计划。 |
| 可组合工程流程：[spec-kit `a4d57122`](https://github.com/github/spec-kit/blob/a4d571229e164e440f8950cac034607bae7b7518/README.md) | 当前 integration、项目约定、启用的 extension/preset/workflow；复用其原生扩展和正式产物，不叠加另一执行计划。 | 使用项目已有流程，按需要再选择特定能力。 |
| 通用编码约束，四项社区版：[Karpathy 指南 `2c606141`](https://github.com/multica-ai/andrej-karpathy-skills/blob/2c606141936f1eeef17fa3043a72095b4765b9c2/skills/karpathy-guidelines/SKILL.md) | 来源、当前安装内容与项目是否选用。 | 使用项目约定与相称验证。 |
| 同类约束的七项社区扩展：[Karpathy 扩展 `7f0e3953`](https://github.com/sumonrh/karpathy-skills-for-antigravity-and-codex/blob/7f0e3953724db00729d0774639dc2a052de95635/skills/karpathy-guidelines/SKILL.md) | 它与四项版是不同来源；同名入口按精确来源区分，按任务缺口选用，不能用条数推导更适合。 | 保持已有选择，不自动替换四项版或同时加载两版。 |

结构分析能力与通用编码约束职责不同，可按同一任务的具体需要补充；独立调用它不要求装某个固定版本的通用指南。
用户自建规范同样通过接入记录选择，优先保留用户自己的内容和存储位置。
