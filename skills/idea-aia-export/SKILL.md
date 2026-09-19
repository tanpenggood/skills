---
name: idea-aia-export
description: 导出 JetBrains IDEA AI Assistant 中各种 Agent（opencode/qoder/codex/claude-acp/codebuddy 等）的会话记录。数据源位于 %APPDATA%\JetBrains\<IDE名>\aia-task-history\，每个会话一组的 .events（AUI_EVENTS_V1，每行一条 base64 的 JSON 事件）、.agentsession（底层会话ID）、.lastid 文件。Use when 用户说导出/备份 IDEA AI Assistant 会话、AI Agent 对话、解析 .events 文件、把 aia-task-history 里的对话导出为 Markdown/JSON、按 GUID 或底层 ses_ 会话 ID 导出。
---

# IDEA AI Assistant 会话导出

JetBrains IDE（IntelliJ IDEA / 其他 JetBrains 产品）里的 AI Assistant 各 Agent 会话都保存在 IDE 配置目录的 `aia-task-history` 下，本地即可读取，无需界面导出功能。

## 存储位置

```
%APPDATA%\JetBrains\<IDE名>\aia-task-history\
```

例如 `C:\Users\<你>\AppData\Roaming\JetBrains\IntelliJIdea2026.2\aia-task-history\`。

IDE 名按版本变化：`IntelliJIdea2026.2`、`IntelliJIdea2026.1`、`PyCharm2026.1` 等，用 `Get-ChildItem "$env:APPDATA\JetBrains"` 确认。

每个会话 = 一个 GUID 开头的同名文件组（目录内共 5 种后缀，按 GUID 关联）：

| 文件 | 内容 |
|------|------|
| `<GUID>.events` | 对话内容本体。第 1 行 `AUI_EVENTS_V1`，之后每行一条 base64 编码的 JSON 事件 |
| `<GUID>.agentsession` | 底层 Agent 会话 ID，如 `acp.registry.opencode:ses_<id>` |
| `<GUID>.lastid` | 事件序号（纯数字） |
| `<GUID>.usage` | 用量统计，格式 `{"used":N,"size":M}`（配额占用），**非对话内容** |
| `<GUID>.unread` | 未读标记，内容 `true`，**非对话内容** |

导出的对象只有 `.events`；`.usage` / `.unread` 不含对话，不要误当会话内容解析。

注意：
- GUID 与截图临时附件文件名（`ai-chat-custom-attachment-temp-file-<GUID>-...`）一致，可据此定位当前会话。
- 只有 `.agentsession` 没有 `.events` 的是空壳会话（打开过但未产生对话记录），没有内容。
- 各 Agent 从 `.agentsession` 前缀区分：`acp.registry.opencode`、`acp.qoder-cli-acp`、`acp.registry.qoder`、`acp.registry.claude-acp`、`acp.registry.codebuddy-code`、`codex` 等。

## 快速使用

脚本：`scripts/export-aia-session.ps1`（Windows PowerShell 5.1，无第三方依赖）

### 1. 列出所有会话

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File <此skill目录>\scripts\export-aia-session.ps1 -List
```

输出：GUID、Agent、底层会话 ID、事件数、更新时间（按时间倒序）。可用 `-IdeName` 切换 IDE（默认 `IntelliJIdea2026.2`）。

### 2. 导出指定会话

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File <此skill目录>\scripts\export-aia-session.ps1 -SessionId <GUID>
```

默认导出到 `%USERPROFILE%\Downloads`（用 `-OutDir` 指定其他目录），按 `<GUID>` 产出固定命名的 2 个文件：

| 默认文件名 | 格式 | 内容 |
|------|------|------|
| `aia-session-<GUID>.jsonl` | JSON Lines | 原始解码事件，每行一条完整 JSON（含未被 md 截断的工具全文） |
| `aia-session-<GUID>.md` | Markdown | 可读对话：每轮 = `## 用户` → `### 思考` → `### 工具 / 终端命令 / 查看文件` → `### AI`（markdown 流式分块已按 stepId 合并为完整回复） |

例：`SessionId=c2011737-ffca-4bb0-beb3-cd2c7414a42f` → `Downloads\aia-session-c2011737-ffca-4bb0-beb3-cd2c7414a42f.jsonl` 与 `...md`。

### 3. 按底层会话 ID 找 GUID

```powershell
Get-ChildItem <aia-task-history> -Filter *.agentsession | Where-Object { (Get-Content $_ -Raw) -match 'ses_xxxx' }
```

## 事件类型说明（解码 `.events` 时用）

- `ChatSessionUserPromptEvent` — 用户提问（含 `attachments` 附件）
- `ChatSessionMessageBlockEvent`，其 `event.kind` 决定块类型：
  - `AgentThoughtBlockUpdatedEvent` — 模型思考
  - `MarkdownBlockUpdatedEvent` — 回复文本，按 `stepId` 流式分块，**需累积合并**
  - `ToolBlockUpdatedEvent` — 工具调用（`toolType`/`status`/`args`/`output`）
  - `TerminalBlockUpdatedEvent` — 终端命令（含 `commandLanguage`）
  - `ViewFilesBlockUpdatedEvent` — 查看的文件列表

md 导出对超长内容有截断保护（工具 output 2500 字符、args 1200 字符），完整原文以 `.jsonl` 为准。

## 常见问题

### 找不到我想导出的那个会话？

用 `-List` 看更新时间倒序列表，或用 `.agentsession` 里的 `ses_` 底层 ID 反查。DATA 在 `Get-ChildItem "$env:APPDATA\JetBrains\IntelliJIdea2026.2\aia-task-history" -Filter *.events | Sort-Object LastWriteTime -Descending` 最顶部。

### 普通 AI Assistant 聊天（不启动 Agent）的会话在这吗？

不一定。`aia-task-history` 专门存 Agent 会话。不跑 Agent 的普通问答会话可能存于别的插件目录，不在本 skill 范围。

### 导出是加密的吗？

不是。`.events` 只是 base64，无加密，`[Convert]::FromBase64String` 直接可解。注意文件含完整工具输出与文件路径，可能含敏感信息，分享前注意脱敏。