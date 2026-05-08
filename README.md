# Git Resume Builder

A skill that extracts and structures project experience from git commit history to generate resume-ready content.

## Description

Automatically analyzes git commit records to produce quantified, value-focused project descriptions suitable for resumes/CVs. Follows best practices: quantify results, specify technologies, highlight business value, and keep it concise.

## Trigger Phrases

Use this skill when users mention any of:
- "整理项目经验"
- "生成简历项目"
- "git 提交 简历"
- "项目经验整理"
- "resume from git"
- "project experience from commits"

## Core Principles

1. **Quantify Results** - Use specific numbers (%, count, time saved, performance gains)
2. **Specify Technologies** - List concrete tech stack, frameworks, tools
3. **Highlight Value** - Focus on business impact and technical achievements
4. **Be Concise** - Resume-ready, bullet-point style

## Workflow

1. **Collect Git Data**: Extract commit history, stats, and file changes for the target author
2. **Analyze Project Structure**: Identify tech stack, modules, and contribution patterns
3. **Extract Key Info**: Project duration, code impact, tech stack, module ownership, key features
4. **Generate Resume Content**: Structure output with project description, tech stack, role, and quantified achievements

## Usage Example

```
帮我用 git 提交记录整理项目经验，作者：tanpenggood
```

The skill will:
- Analyze git log for author "tanpenggood"
- Calculate project duration, commit count, code changes
- Identify tech stack from package.json and file extensions
- Generate resume-ready project experience section

## Output Format

Each project follows this structure:
```markdown
### [Project Name]
**Time**: YYYY.MM - YYYY.MM  
**Role**: [Frontend Engineer / Backend Engineer / Full-stack Engineer / Tech Lead]

**Project Description**:  
[What it is, who uses it, key purpose. 1-2 sentences max.]

**Tech Stack**:  
[Frontend]: [specific frameworks, libraries]  
[Backend]: [specific frameworks, languages]  
[Infrastructure]: [databases, cloud services, CI/CD]

**Key Achievements**:
• [Quantified achievement 1 - use %, count, time, performance]
• [Quantified achievement 2 - focus on value delivered]
• [Quantified achievement 3 - technical complexity solved]
```

## Quality Checklist

Before delivering output, verify:
- [ ] Every bullet has at least one number/metric
- [ ] Tech stack lists specific versions or library names
- [ ] Business value is explicit (not just "optimized" but "reduced X by Y%")
- [ ] Total length fits resume format (3-5 projects, each 4-6 lines)
- [ ] Action verbs used (implemented, optimized, built, refactored)

## Requirements

- Git repository with commit history
- Target author's name or email configured in git
- Node.js environment (for reading package.json)

## Notes

- Replace `<author>` with the user's git config name or email
- For monorepos, analyze each package/subproject separately
- When commit messages are vague ("fix bug", "update code"), infer from file paths and diff stats
- Always confirm with user: author name/email, projects to include, resume format (Chinese/English)
