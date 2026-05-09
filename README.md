# Skills

A collection of AI assistant skills/instructions that extend AI coding agents with domain-specific capabilities.

## Skills

### [Git Resume Builder](./skills/git-resume-builder/)

Extracts project experience from git commit history and generates quantified, value-focused resume descriptions. Analyzes commit messages, diffs, file structures, and tech stacks to produce polished resume bullet points.

- **Trigger:** "整理项目经验" / "resume from git"
- **Output:** Structured markdown with project name, duration, role, tech stack, and key achievements
- **Languages:** 中文 · English

## Usage

These skills are designed to be loaded into AI coding assistants (e.g., opencode, GitHub Copilot, etc.). Each skill in the `skills/` directory contains a `SKILL.md` file with the full instruction set.

To use a skill, tell your AI assistant the trigger phrase, and it will follow the defined workflow.

## License

[MIT](./LICENSE) © 2026 Sam Tan
