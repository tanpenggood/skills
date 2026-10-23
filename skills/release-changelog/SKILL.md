---
name: release-changelog
description: 在生产分支发版前，分析指定 git 提交范围内的改动，review 本次发版新增了什么功能、修复了什么 BUG、做了什么优化，评估影响模块与风险（是否涉及脚本执行、数据库迁移、配置/依赖变更、接口兼容性等），最终输出 CHANGELOG-yyyyMMdd.md。当用户提到"发版前 review 一下改动""生成发版 CHANGELOG""分析本次发布的提交记录""发布前检查改了什么""release notes""production release changelog"等需求时使用本 skill。
---

# 发版变更分析（Release CHANGELOG）

## 用途

在把代码部署到生产分支之前，对本次发版涉及的 git 提交做一次完整 review，产出一份供发版评审、回滚预案、上线通报使用的 `CHANGELOG-yyyyMMdd.md`。

产出文档必须回答六个问题：

1. 实现了什么功能
2. 修复了什么 BUG
3. 做了什么优化
4. 影响了哪些模块
5. 是否涉及脚本执行 / 数据迁移 / 配置与依赖变更
6. 有哪些风险与兼容性影响

## 必须向用户确认的信息

**以下两项缺失时必须先询问，不得猜测或自行推断：**

1. **生产分支名** —— 例如 `main`、`master`、`release`、`prod`。
2. **改动范围如何圈定** —— 三选一：
    - 起始 commit hash（从该 commit **之后**到分支最新提交，即 `since..HEAD`）；
    - 单个 merge commit hash（自动解析该 PR 引入的 commits，净 diff 为 `merge^1..merge`，精确）；
    - 或若干指定的 commit hash 列表。

可选项（有默认值，缺失时不必追问）：

| 项 | 默认值 |
| --- | --- |
| 仓库路径 | 当前工作目录；若当前目录不是 git 仓库，再询问用户 |
| 输出目录 | 当前工作区根目录下的 `outputs/`（不存在则创建） |
| 是否包含 merge commit | 不包含 |
| 输出文件名 | `CHANGELOG-yyyyMMdd.md`，yyyyMMdd 取**生成当天**日期 |

若用户一次只给了部分信息，把缺失项一次性问完，不要分批追问。

## 执行流程

### 第 1 步：收集数据

调用 `scripts/collect_commits.py` 一次性拿到结构化数据。核心输出是 **`net_diff`（范围基线 → 终态的净变更）**：基线版本与终态版本的整段 diff、逐文件净增删行、新增/删除文件清单、风险预标注。commit 列表仅保留元数据（hash、作者、message、逐文件清单）用于条目归组与溯源标注，**不逐 commit 采样 diff**。脚本只依赖标准库与 git，不需要安装任何包。

```bash
# 起点 hash 模式（推荐）：净 diff = git diff since..target，精确
python scripts/collect_commits.py --repo <仓库路径> --branch main --since <hash> --out /tmp/rel.json

# 单个 merge / PR 模式：自动解析 PR 分支 commits，净 diff = git diff merge^1..merge，精确
python scripts/collect_commits.py --repo <仓库路径> --branch main --merge <hash> --out /tmp/rel.json

# 显式 commit 列表模式：连续父链时精确，否则脚本标记 exact=false 并给出警告
python scripts/collect_commits.py --repo <仓库路径> --branch main --commits <h1>,<h2>,<h3> --out /tmp/rel.json
```

常用参数：

- `--to <hash>`：结束 commit，默认分支最新提交
- `--module-depth 2`：monorepo 场景把模块聚合到二级目录
- `--diff-budget 240000`：扩大净 diff 采样预算（默认 120000 字符）
- `--max-commits 400`：提交数上限，超出会在报告中标记 `truncated: true`
- `--diff-out <file>`：把基线→终态的完整净 patch 落盘，供后续精读
- `--per-commit-diffs`：额外采样每个 commit 各自的 diff（默认关闭，仅在需要定位某个 commit 的中间状态时使用）

先读脚本输出到 stderr 的摘要，确认提交数量级与范围符合预期。注意三点：

- `net_diff.exact` 为 false 时（非连续 commit 列表、未指定起点），净 diff 可能混入范围外改动，优先改用 `--since` 或 `--merge` 模式重跑；
- `summary.additions/deletions` 是**净**增删行数，可能与各 commit 增删行之和不一致（范围内重复修改会抵消），这是预期行为，影响模块表格以净数字为准；
- 若 `truncated` 为 true，提示用户缩小范围或提高 `--max-commits`。

### 第 2 步：深度阅读净变更

分析深度固定为**深度模式**：必须通读 `net_diff.patches`（基线 → 终态的净 diff），以净变更为唯一事实来源。

核心原则——净变更优先：

1. **只分析「基线版本 → 终态」的整体差异，不逐 commit 分析范围内中间演变。** 范围内新建的文件，净 diff 中即为完整终态，直接按新代码理解，无需关心它经历了几个 commit 才写成这样；先建后改、来回调整的中间过程不进 CHANGELOG。
2. **commit message、hash、作者只用于归组与溯源**：把净变更归组成功能/修复/优化条目，并在条目上标注溯源 hash。不要按 commit 逐条复述，不要凭 commit message 下结论。
3. 阅读顺序：先读 `summary`、`modules`、`risk_items`、`breaking_notes`、`net_diff.new_files`/`deleted_files` 建立整体认知，再通读 `net_diff.patches` 判定每处净变更的真实意图。
4. `net_diff.patches` 被预算截断或信息不足时，用 `git show <target>:<path>` 读终态全文、`git diff <baseline> <target> -- <path>` 补充单文件，必要时加 `--per-commit-diffs` 重跑定位某个 commit。
5. 对 `risk_items` 涉及的每个文件，确认是否真的需要人工执行脚本、是否真的改了表结构。

### 第 3 步：分类与风险判定

加载并遵循 `references/classification.md`：

- 改动类型按「新功能 > BUG 修复 > 性能优化 > 依赖 > 配置 > 重构 > 其他」取最高优先级，**以净 diff 事实为准，不迷信 commit message**；commit 的 type message（feat/fix/...）仅用于条目归组。
- 只改测试/文档的改动不进功能与修复章节。
- 风险项逐个复核并给出结论与建议动作，禁止原样罗列脚本输出。
- 判断不清的条目放进「待确认事项」，不要臆测。

### 第 4 步：生成文档

1. 以 `assets/CHANGELOG-template.md` 为骨架，复制到输出目录并重命名。
2. 填充各章节；模板里的 `<!-- -->` 注释是写作指引，填充完成后删除。
3. 无内容的章节保留标题并写「无」，不要整段删掉（便于评审确认"确实没有"）。
4. 章节顺序：破坏性提示 → 新增功能 → 问题修复 → 性能优化 → 依赖与配置 → 脚本与迁移 → 影响模块 → 风险 → 发版检查项 → 待确认 → 提交清单。

写作要求：

- 每个功能/修复/优化条目必须带 commit hash，便于追溯。
- 语言简洁具体，写清「改了什么、为什么、影响谁」，避免复述 commit message。
- 影响模块表格按改动量降序。
- 涉及脚本执行时，写清：脚本路径、作用、执行时机（发版前/后）、执行人、失败如何回滚。
- 净 diff 中出现新增对外 API 接口（Controller 新增路由方法、proto/openapi 新增路由定义）时，在「发版检查项」中逐条列出接口完整路径，提醒在云平台网关上配置、发布并授权给相应应用；未配置网关的新接口下游调用会返回 404。

### 第 5 步：交付

- 用 `present_files` 把生成的 `CHANGELOG-yyyyMMdd.md` 呈现给用户。
- 回复里用简短文字点出：本次发版 N 个 commit、核心变化一句话概括、以及**最高的 1-3 个风险点**，便于用户快速决策。

## 注意事项

- **净变更优先**：范围内 commit 的中间演变（先建后改、来回调整、最终抵消的改动）不单独分析，也不进 CHANGELOG；文档描述的是基线→终态的差异。
- 只做静态分析与文档产出，**不要执行仓库里的任何脚本**。
- 不要向仓库提交、打 tag、push 或创建分支。
- 仓库工作区若有未提交改动，在「待确认事项」中提示用户；未提交改动不在分析范围内。
- 分析范围跨度很长或提交数超过 200 时，在文档开头提示「本次范围较大，建议拆分发版」。
- 生成日期用当天日期，用 `date +%Y%m%d` 获取，不要心算。
