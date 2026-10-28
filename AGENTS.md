# EXharness Agent 指南

> 本文件是仓库级长期准则，供在本仓库工作的 agent、模型与维护者使用。
> **修改本文件必须由人类明确授权**：agent 只能提出建议和草案，通过 PR 提交，不得擅自编辑。
> 跨 session、换模型或长任务中途记不清流程时，先重读本文件与 [README](README.md)，不要凭记忆操作。

> **工作区治理规范入口**：本仓库遵循 skill
> [git-workspace-governance](skills/git-workspace-governance/SKILL.md) 的 canonical / worktree /
> 清理备份 / 发布 SHA 边界；接手、清理或发布核对前先跑只读体检：
>
> ```bash
> python3 skills/git-workspace-governance/references/scripts/check_workspace_state.py --repo .
> ```

## 1. 项目定位

EXharness 是面向长期工程项目与多 agent 协作的 **skill 集合（monorepo）**。三个 skill 互相独立、各自安装、互不依赖：

| Skill | 职责 |
|---|---|
| [long-running-project-harness](skills/long-running-project-harness/SKILL.md) | 长期项目协议：任务账本、交接/审查/closeout、runtime 边界 |
| [invoke-coding-agents](skills/invoke-coding-agents/SKILL.md) | 调起、监督、恢复、验收本地外部 coding agent CLI |
| [git-workspace-governance](skills/git-workspace-governance/SKILL.md) | 仓库级工作区治理：canonical/main、worktree、清理备份、发布 SHA、只读体检 |

三者可单独使用，也可组合；任何一方都不得把其它 skill 当成硬依赖。

## 2. 接手顺序

1. 读 [README](README.md)（定位、最小组合、安装方式）与本文件。
2. 跑只读工作区体检（见文首命令）；warning 只是线索，不自动修复、不阻塞其他独立任务。
3. 确认任务归属：已有分支 / worktree 优先恢复，不为同一任务重复开工。
4. 在独立 worktree 中工作，改动走 PR；涉及清理、备份、发布时另行取得授权。

## 3. 工作区与 Git 规则

本仓库遵循 [git-workspace-governance](skills/git-workspace-governance/SKILL.md) 的完整规范；即使环境未安装该 skill，以下边界仍然适用：

- canonical checkout 只保持 `main`；任务使用独立 worktree 与 `codex/<task>` 分支，从最新 `origin/main` 的精确 ref 创建；
- 不直推或强推 `main`，不改写已推送的共享历史；
- 提交走 PR + CI + 独立复审；合并需要授权；
- 清理、备份、发布分别需要授权：没有授权只输出候选清单；
- 禁止 `git clean`、`reset --hard`、`checkout --`、`worktree remove --force` 或批量 `prune` 来“把树弄干净”；
- 发布前分别读回四个 SHA（合入提交 / 本地 main / 远程 main / 部署 HEAD）；合并 ≠ 发布。

安装该 skill 时，按需加载更细的 references：`state-model`、`recovery`、`backup-and-cleanup`、
`release-verification`、`health-check`。其他项目建议由人类授权后，把本 skill 的入口登记进它们自己的
instructions 文件（写法见 skill 的 `project-onboarding` 参考）。

## 4. 目录结构

```text
skills/<skill-name>/
├── SKILL.md              # 必需：入口与路由，保持薄
├── agents/openai.yaml    # 可选：agent 元数据
├── references/           # 重内容：按需读取
│   ├── *.md
│   └── scripts/          # 可执行工具与 tests/
├── scripts/              # 可选：跨项目 thin wrapper
└── subskills/            # 可选：progressive disclosure 子 skill
```

```text
.github/workflows/test.yml  # CI：Linux 3.12–3.14 矩阵 + Windows
LICENSE                     # MIT
README.md                   # 对外入口
```

## 5. 写 skill 的硬性约定

- **薄入口**：`SKILL.md` 只放原则、决策表、路由；细节放 `references/`，按需读取，不一次性展开。
- **frontmatter**：必须有 `name`（与目录同名、小写连字符）和 `description`（第三人称、以 `Use when...` 开头、只写触发条件，不总结流程，尽量 ≤ 500 字符）。
- **自包含**：每个 skill 单独复制安装后必须可用；不得引用其它 skill 的路径或要求它存在。跨 skill 只能出现在“可选集成（非依赖）”表里，用能力名 + 示例名 + fallback。
- **禁止机器绝对路径**：skill 内不出现用户主目录、Windows 盘符等本机特有路径，示例统一用 `<placeholder>`。
- **脚本**：只用 Python 标准库；只读工具不得 fetch 或修改状态；可跨项目直接运行。跨项目入口用 thin wrapper，语义实现放 `references/scripts/`。
- **Clean-Room**：不复制外部产品的源码、prompt、文档、测试或命名约定；只借鉴通用方法。
- **语言**：README 与说明文档用中文；skill 的 `description` 用英文触发式；代码注释保持简洁。
- **测试**：每个 skill 的行为测试放 `references/.../tests/`，用标准库 `unittest`；新增能力必须带测试。

## 6. 测试与 CI（提交前本地必须跑）

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s skills/long-running-project-harness/references/tests -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s skills/git-workspace-governance/references/scripts/tests -p 'test_*.py'
bash -n skills/long-running-project-harness/references/scripts/harnessctl
```

CI 位于 `.github/workflows/test.yml`：Linux 3.12 / 3.13 / 3.14 矩阵 + Windows。
新增或修改 skill、脚本时，同步更新 CI 与 README 的验证说明。

## 7. 修改与发布流程

1. 新任务从最新 `origin/main` 建 `codex/<task>` 分支与独立 worktree；
2. 一个 commit 只包含一个逻辑目标，不混入无关格式化或批量重排；
3. 提交 PR，等 CI 与独立复审通过后由有权限者合并；
4. 版本发布（tag、发布副本、公告）是独立授权动作，不能从“合并”推导出来；
5. 不覆盖他人未提交内容，不批量清理其他会话的工作树；
6. 结束时报告：实际改了什么、跑了哪些验证、哪些留待用户确认。

## 8. 常见反模式

| 反模式 | 后果 |
|---|---|
| 擅自修改 `AGENTS.md` 或项目 instructions | 越权修改项目准则；先建议并取得人类授权 |
| 把整份 skill 文档贴进入口文件 | 重复、漂移、上下文膨胀 |
| 让一个 skill 依赖另一个 skill 才能工作 | 用户单独安装时直接失效 |
| 在 skill 里写机器绝对路径或本机用户名 | 无法发布，且泄露本机信息 |
| 直接改 `main`、强推或顺手清理别人的树 | 破坏共享历史与并行工作 |
| “反正能重新拉依赖，先整包备份” | 备份失控；只保不可再生的最小集合 |
| 改完不跑测试，等 CI 才发现 | 反馈慢、浪费复审时间 |
| 把合并当成发布 | 用户/生产看到的版本并没有变 |

## 9. 相关入口

- [README](README.md)：定位、最小组合、安装与验证
- [long-running-project-harness](skills/long-running-project-harness/SKILL.md)
- [invoke-coding-agents](skills/invoke-coding-agents/SKILL.md)
- [git-workspace-governance](skills/git-workspace-governance/SKILL.md) 与
  [只读体检契约](skills/git-workspace-governance/references/health-check.md)
