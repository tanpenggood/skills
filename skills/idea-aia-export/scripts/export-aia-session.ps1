<#
.SYNOPSIS
    导出 JetBrains IDEA AI Assistant 会话（aia-task-history 下的 .events 文件）。

.DESCRIPTION
    读取 %APPDATA%\JetBrains\<IdeName>\aia-task-history\<GUID>.events（AUI_EVENTS_V1：
    每行一条 base64 的 JSON 事件），解码为可读 Markdown 对话 + 原始 JSONL。
    支持 -List 列出全部会话。

    Windows PowerShell 5.1，无第三方依赖。

.PARAMETER SessionId
    要导出的会话 GUID（文件名主名）。用了 -List 时忽略。

.PARAMETER List
    只列出 aia-task-history 下的所有会话，不导出。

.PARAMETER IdeName
    JetBrains IDE 配置目录名，默认 IntelliJIdea2026.2。

.PARAMETER OutDir
    导出目录，默认 %USERPROFILE%\Downloads。

.EXAMPLE
    .\export-aia-session.ps1 -List

.EXAMPLE
    .\export-aia-session.ps1 -SessionId c2011737-ffca-4bb0-beb3-cd2c7414a42f

.EXAMPLE
    .\export-aia-session.ps1 -SessionId 1ef88ff5-7352-4d64-9d1f-80f191fd21a3 -IdeName IntelliJIdea2026.1 -OutDir D:\backup\aia
#>
[CmdletBinding()]
param(
    [string]$SessionId,
    [switch]$List,
    [string]$IdeName = 'IntelliJIdea2026.2',
    [string]$OutDir
)

$ErrorActionPreference = 'Stop'
$history = Join-Path $env:APPDATA "JetBrains\$IdeName\aia-task-history"
if (-not (Test-Path -LiteralPath $history)) {
    throw "找不到 aia-task-history: $history`n请确认 IDE 名（当前 $IdeName），可用 Get-ChildItem `"$env:APPDATA\JetBrains`" 查看"
}

if ($List) {
    $rows = Get-ChildItem -LiteralPath $history -File -Filter *.agentsession |
        Sort-Object LastWriteTime -Descending |
        ForEach-Object {
            $guid = $_.BaseName
            $agentRaw = (Get-Content -LiteralPath $_.FullName -Raw).Trim()
            $events = Test-Path -LiteralPath (Join-Path $history "$guid.events")
            [PSCustomObject]@{
                GUID       = $guid
                Agent      = ($agentRaw -split ':')[0]
                AgentSesID = $agentRaw
                Events     = if ($events) { (Get-Content -LiteralPath (Join-Path $history "$guid.events") | Measure-Object -Line).Lines - 1 } else { 0 }
                Updated    = $_.LastWriteTime
            }
        }
    $rows | Format-Table -AutoSize -Wrap
    Write-Output "共 $($rows.Count) 个 .agentsession（其中 .events 有事件记录的 $(($rows | Where-Object { $_.Events -gt 0 }).Count) 个）"
    return
}

if ([string]::IsNullOrWhiteSpace($SessionId)) {
    throw '请指定 -SessionId <GUID>，或用 -List 查看现有会话'
}

$eventsPath = Join-Path $history "$SessionId.events"
if (-not (Test-Path -LiteralPath $eventsPath)) {
    throw "不存在该会话的事件文件: $eventsPath`n试试 -List 确认 GUID"
}

if ([string]::IsNullOrWhiteSpace($OutDir)) {
    $OutDir = Join-Path $env:USERPROFILE 'Downloads'
}
if (-not (Test-Path -LiteralPath $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir | Out-Null
}

$agentSesPath = Join-Path $history "$SessionId.agentsession"
$agentRaw = if (Test-Path -LiteralPath $agentSesPath) { (Get-Content -LiteralPath $agentSesPath -Raw).Trim() } else { '(未知/无 .agentsession)' }

$lines = Get-Content -LiteralPath $eventsPath
if ($lines[0] -ne 'AUI_EVENTS_V1') { throw "意外的文件头: $($lines[0])" }

$decoded = for ($i = 1; $i -lt $lines.Count; $i++) {
    $base64 = $lines[$i].Trim()
    if ($base64 -eq '') { continue }
    [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($base64))
}

$outJsonl = Join-Path $OutDir "aia-session-$SessionId.jsonl"
$outMd    = Join-Path $OutDir "aia-session-$SessionId.md"

$decoded | Set-Content -Encoding UTF8 $outJsonl

$sb = New-Object System.Text.StringBuilder
[void]$sb.AppendLine("# AI Assistant 会话导出 $SessionId")
[void]$sb.AppendLine('')
[void]$sb.AppendLine("底层代理: $agentRaw")
[void]$sb.AppendLine("事件数: $($decoded.Count)")
[void]$sb.AppendLine('')

$mdChunk = ''
$mdStep = $null

function FlushMd {
    param($text, $step)
    if ($null -ne $step -and $text.Trim() -ne '') {
        [void]$script:sb.AppendLine("### AI (step $step)")
        [void]$script:sb.AppendLine('')
        [void]$script:sb.AppendLine($text.Trim())
        [void]$script:sb.AppendLine('')
    }
    $script:mdChunk = ''
    $script:mdStep = $null
}

foreach ($jsonline in $decoded) {
    $e = $jsonline | ConvertFrom-Json
    switch ($e.type) {
        'com.intellij.ml.llm.chat.shared.ChatSessionUserPromptEvent' {
            FlushMd -text $mdChunk -step $mdStep
            [void]$sb.AppendLine('## 用户')
            [void]$sb.AppendLine('')
            [void]$sb.AppendLine([string]$e.prompt)
            [void]$sb.AppendLine('')
            if ($null -ne $e.attachments -and $e.attachments.Count -gt 0) {
                [void]$sb.AppendLine('附件: ' + (($e.attachments | ForEach-Object { $_.name }) -join ', '))
                [void]$sb.AppendLine('')
            }
        }
        'com.intellij.ml.llm.chat.shared.ChatSessionMessageBlockEvent' {
            $ev = $e.event
            switch -Regex ($ev.kind) {
                '^.*AgentThoughtBlockUpdatedEvent$' {
                    FlushMd -text $mdChunk -step $mdStep
                    [void]$sb.AppendLine("### 思考 step $($ev.stepId)")
                    [void]$sb.AppendLine('')
                    [void]$sb.AppendLine([string]$ev.text)
                    [void]$sb.AppendLine('')
                }
                '^.*MarkdownBlockUpdatedEvent$' {
                    if ($mdStep -and $mdStep -ne $ev.stepId) { FlushMd -text $mdChunk -step $mdStep }
                    $mdStep = $ev.stepId
                    $mdChunk += [string]$ev.textChunk
                }
                '^.*ToolBlockUpdatedEvent$' {
                    FlushMd -text $mdChunk -step $mdStep
                    [void]$sb.AppendLine("### 工具: $($ev.toolType) [$($ev.status)] step $($ev.stepId)")
                    [void]$sb.AppendLine('')
                    if ($ev.args) {
                        $argsStr = $ev.args | ConvertTo-Json -Compress
                        if ($argsStr.Length -gt 1200) { $argsStr = $argsStr.Substring(0, 1200) + ' ...(截断)' }
                        [void]$sb.AppendLine('参数: ' + $argsStr)
                        [void]$sb.AppendLine('')
                    }
                    if ($ev.output) {
                        $o = [string]$ev.output
                        if ($o.Length -gt 2500) { $o = $o.Substring(0, 2500) + ' ...(截断)' }
                        [void]$sb.AppendLine($o)
                        [void]$sb.AppendLine('')
                    }
                    if ($ev.details) {
                        [void]$sb.AppendLine('详情: ' + [string]$ev.details)
                        [void]$sb.AppendLine('')
                    }
                }
                '^.*TerminalBlockUpdatedEvent$' {
                    FlushMd -text $mdChunk -step $mdStep
                    [void]$sb.AppendLine("### 终端命令 [$($ev.status)]")
                    [void]$sb.AppendLine('')
                    [void]$sb.AppendLine('```')
                    [void]$sb.AppendLine([string]$ev.command)
                    [void]$sb.AppendLine('```')
                    [void]$sb.AppendLine('')
                }
                '^.*ViewFilesBlockUpdatedEvent$' {
                    FlushMd -text $mdChunk -step $mdStep
                    [void]$sb.AppendLine("### 查看文件 [$($ev.status)] step $($ev.stepId)")
                    [void]$sb.AppendLine('')
                    foreach ($f in $ev.files) { [void]$sb.AppendLine('- ' + [string]$f.path) }
                    if ($ev.details) {
                        [void]$sb.AppendLine('')
                        [void]$sb.AppendLine('详情: ' + [string]$ev.details)
                    }
                    [void]$sb.AppendLine('')
                }
                default {
                    [void]$sb.AppendLine("### 事件 $($ev.kind) step $($ev.stepId) [$($ev.status)]")
                    if ($ev.text) {
                        [void]$sb.AppendLine('')
                        [void]$sb.AppendLine([string]$ev.text)
                    }
                    [void]$sb.AppendLine('')
                }
            }
        }
        default {
            [void]$sb.AppendLine("## 其它事件: $($e.type)")
            [void]$sb.AppendLine('')
        }
    }
}
FlushMd -text $mdChunk -step $mdStep

$sb.ToString() | Set-Content -Encoding UTF8 $outMd

Write-Output "OK 可读对话: $outMd ($((Get-Item -LiteralPath $outMd).Length) bytes)"
Write-Output "OK 原始JSON: $outJsonl ($((Get-Item -LiteralPath $outJsonl).Length) bytes)"