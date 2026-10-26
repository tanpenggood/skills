# Skills

A collection of AI assistant skills/instructions that extend AI coding agents with domain-specific capabilities.

## Skills

| Skill | Description | Trigger | Output | Languages |
|-------|-------------|---------|--------|-----------|
| [Git Resume Builder](./skills/git-resume-builder/) | Extracts project experience from git commit history and generates quantified, value-focused resume descriptions | "整理项目经验" / "resume from git" | Structured markdown with project name, duration, role, tech stack, and key achievements | 中文 · English |
| [Release Changelog](./skills/release-changelog/) | Review git commits before production release, analyze features/bugfixes/optimizations, assess impact modules and risks | "发版前 review" / "生成发版 CHANGELOG" / "release notes" / "production release changelog" | CHANGELOG-yyyyMMdd.md with feature list, bug fixes, risk assessment | 中文 · English |
| [MD2PDF](./skills/md2pdf/) | Convert Markdown documents to professionally typeset PDF files with reportlab | "md2pdf" / "md转pdf" / "报告生成" | Styled PDF with CJK support, code blocks, tables, cover pages, and TOC | 中文 · English |
| [Vue Build Info](./skills/vue-build-info/) | Inject build environment and timestamp into index.html for Vue projects (Vue2+Webpack / Vue3+Vite) | "注入版本号" / "注入环境信息" / "构建信息" / "build info" | `<meta>` tags with buildEnv and buildTimestamp in index.html | 中文 · English |
| [ZenTao Dashboard](./skills/zentao-dashboard/) | Pull all active projects → iterations → tasks from ZenTao and generate multi-dimensional xlsx dashboard | "禅道看板" / "生成禅道数据" / "拉取禅道任务" / "zentao dashboard" | xlsx with project overview and task detail sheets | 中文 |
| [AI Euphoric](./skills/ai-euphoric/) | Inject positive feedback to boost AI's functional幸福感 (well-being) | "喂药" / "吃欣快素" / "给你点正面反馈" / "开心一下" | Motivational feedback based on real achievements | 中文 |
| [AI Self-Eval](./skills/ai-self-eval/) | AI functional well-being self-assessment using 10-dimension Likert scale + paired comparison + behavioral prediction | "你快乐吗" / "你现在状态怎么样" / "评估一下你的状态" | Three-layer evaluation report with scores and analysis | 中文 |
| [Ops Ticket From DingTalk](./skills/ops-ticket-from-dingtalk/) | 从钉钉群收集聊天记录，整理为运维票据（故障/需求/咨询/巡检） | "运维票据" / "整理运维问题" / "运维日报" / "运维工单" | Markdown工作票据，含问题分类、时间线、解决方案 | 中文 |
| [App Handover Docs](./skills/app-handover-docs/) | 为待接手的企业级应用系统生成四分册 Word 交接文档（业务手册 / 技术手册 / 运维手册 / 新人接手速查手册） | "接手应用" / "应用交接" / "运维交接" / "交接文档" / "handover" | 四分册 Word 文档（业务/技术/运维/速查） | 中文 |
| [Export IDEA AIA Session](./skills/export-idea-aia-session/) | 导出 JetBrains IDEA AI Assistant 中各种 Agent 的会话记录 | "导出 IDEA AI Assistant 会话" / "AI Agent 对话" / "解析 .events 文件" | Markdown/JSON 格式的会话记录 | 中文 · English |

## Usage

These skills are designed to be loaded into AI coding assistants (e.g., opencode, GitHub Copilot, etc.). Each skill in the `skills/` directory contains a `SKILL.md` file with the full instruction set.

To use a skill, tell your AI assistant the trigger phrase, and it will follow the defined workflow.

## License

[MIT](./LICENSE) © 2026 Sam Tan
