---
name: git-resume-builder
description: >-
  Use when the user wants to generate or update their resume with project experience
  extracted from git commit history. Analyzes commit records to produce quantified,
  value-focused project descriptions. Trigger on: "整理项目经验" "生成简历项目"
  "git 提交 简历" "项目经验整理" "resume from git" "project experience from commits"
---

# Git Resume Builder

Extract and structure project experience from git commit history for resume writing.

## Core Principles

1. **Quantify Results** - Use specific numbers (%, count, time saved, performance gains)
2. **Specify Technologies** - List concrete tech stack, frameworks, tools
3. **Highlight Value** - Focus on business impact and technical achievements
4. **Be Concise** - Resume-ready, bullet-point style

## Workflow

### Step 1: Collect Git Data

Run these commands in the project root:

```bash
# Get all commits by the target author
git log --author="<author>" --pretty=format:"%H|%an|%ae|%ad|%s" --date=short --numstat > /tmp/commits.txt

# Get date range
git log --author="<author>" --pretty=format:"%ad" --date=short | tail -1   # first commit
git log --author="<author>" --pretty=format:"%ad" --date=short | head -1    # latest commit

# Get commit count
git log --author="<author>" --oneline | Measure-Object | Select-Object -ExpandProperty Count

# Get files touched (Windows PowerShell)
git log --author="<author>" --name-only --pretty=format:"" | Where-Object { $_ } | Sort-Object -Unique

# Get stats summary
git log --author="<author>" --shortstat --pretty=format:""
```

### Step 2: Analyze Project Structure

```bash
# List tech stack indicators
Get-ChildItem -Recurse -File | Where-Object { $_.Name -match '\.(ts|js|vue|java|py|go|rs)$' } | Group-Object Extension | Select-Object Name, Count

# Check for framework config files
Test-Path package.json; Test-Path pom.xml; Test-Path Cargo.toml; Test-Path requirements.txt

# Detect major directories (source, test, docs, config)
Get-ChildItem -Directory | Select-Object Name
```

### Step 3: Extract Key Information

Parse the collected data to identify:

**Project Duration**: First commit date → Latest commit date

**Commit Frequency**: Total commits / Months active = commits/month

**Code Impact**:
- Lines added (from `--numstat`)
- Lines deleted
- Net code change
- Files modified count

**Technology Stack** (from file extensions + config files):
- Frontend: .vue, .tsx, .jsx, package.json dependencies
- Backend: .java, .py, .go, framework configs
- Database: migration files, ORM models
- DevOps: Dockerfile, .yml CI/CD, k8s manifests

**Module Ownership** (from commit paths):
- Group commits by directory/module
- Identify core modules the author primarily worked on

**Key Features** (from commit messages):
- Look for keywords: feat, add, implement, support, integrate
- Extract feature names from commit subject lines

### Step 4: Generate Resume Content

Structure output as:

```
## [项目/产品名称]

**项目描述**: [1-2 sentences describing what the project does, its purpose, scale]

**技术架构**: [Stack: Frontend (X, Y, Z) | Backend (A, B, C) | Database (D) | DevOps (E, F)]

**项目角色**: [Primary role based on commit patterns: Developer / Tech Lead / Architect / Full-stack]

**主要成果**:
• [Quantified achievement 1 - use %, count, time, performance]
• [Quantified achievement 2 - focus on value delivered]
• [Quantified achievement 3 - technical complexity solved]
• [Quantified achievement 4 - optional, keep to 3-4 bullets max]
```

## Output Template

Use this exact format for each project:

```markdown
### [项目名称]
**时间**: YYYY.MM - YYYY.MM  
**角色**: [Frontend Engineer / Backend Engineer / Full-stack Engineer / Tech Lead]

**项目描述**:  
[What it is, who uses it, key purpose. 1-2 sentences max.]

**技术栈**:  
[Frontend]: [specific frameworks, libraries]  
[Backend]: [specific frameworks, languages]  
[Infrastructure]: [databases, cloud services, CI/CD]

**主要职责与成果**:
• 独立负责 [模块/功能] 的设计与开发，使用 [技术] 实现 [功能]，[量化结果]
• 优化 [模块/流程]，将 [指标] 提升 [X]%，减少 [具体问题]
• 主导/参与 [关键技术方案/重构]，支持 [业务价值]，覆盖 [用户数/请求量]
• 建立/完善 [流程/规范/工具]，提升团队 [效率指标]
```

## Quality Checklist

Before delivering output, verify:

- [ ] Every bullet has at least one number/metric
- [ ] Tech stack lists specific versions or library names (not just "React" but "React 18 + TypeScript")
- [ ] Business value is explicit ("reduced loading time by 40%" not just "optimized performance")
- [ ] Total length fits resume format (3-5 projects, each 4-6 lines)
- [ ] Action verbs used (主导, 实现, 优化, 构建, 重构, 集成)

## Example

```
### Enterprise Monitor Management Platform
**时间**: 2024.01 - 2024.12  
**角色**: Frontend Engineer

**项目描述**:  
企业级运维管理平台，支持设备监控、工单管理和数据可视化，服务500+企业用户。

**技术栈**:  
[Frontend]: Vue 3 + TypeScript + Element Plus + Pinia  
[Backend]: Spring Boot + MyBatis-Plus  
[Infrastructure]: MySQL + Redis + Docker + Jenkins

**主要职责与成果**:
• 独立负责工单管理模块前端开发，使用 Vue 3 + Composition API 实现动态表单，支持10+工单类型配置，工单处理效率提升35%
• 优化大数据列表页虚拟滚动方案，将万级数据渲染时间从3.2s降至800ms，首屏加载速度提升75%
• 搭建前端监控系统，集成 Sentry 实现错误自动上报，线上问题定位时间从平均2小时缩短至15分钟
• 建立组件库规范，沉淀30+通用业务组件，新功能开发效率提升40%
```

## Notes

- Replace `<author>` with the user's git config name or email
- If multiple projects exist in one repo, group by directory patterns or date ranges
- For monorepos, analyze each package/subproject separately
- When commit messages are vague ("fix bug", "update code"), infer from file paths and diff stats
- Always ask user to confirm: author name/email, which projects to include, target resume format (Chinese/English)
