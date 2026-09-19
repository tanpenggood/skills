#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导出 JetBrains IDEA AI Assistant 会话（aia-task-history 下的 .events 文件）。

跨平台（Windows / macOS / Linux），仅依赖 Python 3 标准库。自动按操作系统定位
JetBrains 配置目录：
  Windows: %APPDATA%\\JetBrains\\<IDE>\\aia-task-history
  macOS:   ~/Library/Application Support/JetBrains/<IDE>/aia-task-history
  Linux:   ~/.config/JetBrains/<IDE>/aia-task-history

用法：
  python export_aia_sessions.py --list
  python export_aia_sessions.py --session <GUID> [--ide-name IntelliJIdea2026.2] [--out-dir …]
"""

import argparse
import base64
import json
import os
import platform
import sys
from pathlib import Path

DEFAULT_IDE = "IntelliJIdea2026.2"
OUT_MD = "aia-session-{guid}.md"
OUT_JSONL = "aia-session-{guid}.jsonl"


def history_dir(ide_name: str) -> Path:
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:  # Linux / 其它
        base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "JetBrains" / ide_name / "aia-task-history"


def default_out_dir() -> Path:
    if platform.system() == "Windows":
        return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Downloads"
    return Path.home() / "Downloads"


def load_events(events_path: Path) -> list:
    raw = events_path.read_bytes()
    lines = raw.split(b"\n")
    if lines[0].strip() != b"AUI_EVENTS_V1":
        raise ValueError(f"意外的文件头: {lines[0]!r}")
    events = []
    for ln in lines[1:]:
        ln = ln.strip()
        if not ln:
            continue
        events.append(json.loads(base64.b64decode(ln).decode("utf-8")))
    return events


def render_md(guid: str, agent_raw: str, events: list) -> str:
    out = []
    out.append(f"# AI Assistant 会话导出 {guid}")
    out.append("")
    out.append(f"底层代理: {agent_raw}")
    out.append(f"事件数: {len(events)}")
    out.append("")

    md_chunk = ""
    md_step = None

    def flush() -> None:
        nonlocal md_chunk, md_step
        if md_step is not None and md_chunk.strip():
            out.append(f"### AI (step {md_step})")
            out.append("")
            out.append(md_chunk.strip())
            out.append("")
        md_chunk = ""
        md_step = None

    for e in events:
        t = str(e.get("type", ""))
        if t.endswith("ChatSessionUserPromptEvent"):
            flush()
            out.append("## 用户")
            out.append("")
            out.append(str(e.get("prompt", "")))
            out.append("")
            atts = e.get("attachments")
            if atts:
                out.append("附件: " + ", ".join(str(a.get("name", "")) for a in atts))
                out.append("")
        elif t.endswith("ChatSessionMessageBlockEvent"):
            ev = e.get("event", {})
            kind = str(ev.get("kind", ""))
            step = ev.get("stepId")
            status = ev.get("status")
            if kind.endswith("AgentThoughtBlockUpdatedEvent"):
                flush()
                out.append(f"### 思考 step {step}")
                out.append("")
                out.append(str(ev.get("text", "")))
                out.append("")
            elif kind.endswith("MarkdownBlockUpdatedEvent"):
                if md_step is not None and md_step != step:
                    flush()
                md_step = step
                md_chunk += str(ev.get("textChunk", ""))
            elif kind.endswith("ToolBlockUpdatedEvent"):
                flush()
                out.append(f"### 工具: {ev.get('toolType')} [{status}] step {step}")
                out.append("")
                args = ev.get("args")
                if args:
                    s = json.dumps(args, ensure_ascii=False, separators=(",", ":"))
                    if len(s) > 1200:
                        s = s[:1200] + " ...(截断)"
                    out.append("参数: " + s)
                    out.append("")
                o = ev.get("output")
                if o is not None:
                    o = str(o)
                    if len(o) > 2500:
                        o = o[:2500] + " ...(截断)"
                    out.append(o)
                    out.append("")
                if ev.get("details"):
                    out.append("详情: " + str(ev["details"]))
                    out.append("")
            elif kind.endswith("TerminalBlockUpdatedEvent"):
                flush()
                out.append(f"### 终端命令 [{status}]")
                out.append("")
                out.append("```")
                out.append(str(ev.get("command", "")))
                out.append("```")
                out.append("")
            elif kind.endswith("ViewFilesBlockUpdatedEvent"):
                flush()
                out.append(f"### 查看文件 [{status}] step {step}")
                out.append("")
                for f in ev.get("files", []):
                    out.append("- " + str(f.get("path", "")))
                if ev.get("details"):
                    out.append("")
                    out.append("详情: " + str(ev["details"]))
                out.append("")
            else:
                flush()
                out.append(f"### 事件 {kind} step {step} [{status}]")
                if ev.get("text"):
                    out.append("")
                    out.append(str(ev["text"]))
                out.append("")
        else:
            out.append(f"## 其它事件: {t}")
            out.append("")
    flush()
    return "\n".join(out)


def cmd_list(hist: Path) -> int:
    rows = []
    for ap in sorted(hist.glob("*.agentsession"), key=lambda p: p.stat().st_mtime, reverse=True):
        guid = ap.stem
        agent_raw = ap.read_text(encoding="utf-8").strip()
        ev = hist / f"{guid}.events"
        n = 0
        if ev.exists():
            try:
                n = len(load_events(ev))
            except Exception:
                n = -1
        rows.append((ap.stat().st_mtime, guid, agent_raw.split(":", 1)[0], agent_raw, n))
    if not rows:
        print(f"({hist}) 下没有 .agentsession，换个 --ide-name 试试？")
        return 0
    w = max(len(r[1]) for r in rows)
    for _, guid, agent, agent_raw, n in rows:
        print(f"{guid:<{w}}  {agent:<24}  events={n:>4}  {agent_raw}")
    print(f"\n共 {len(rows)} 个 .agentsession（其中 .events 有事件记录的 {(sum(1 for r in rows if r[4] > 0))} 个）")
    return 0


def cmd_export(hist: Path, guid: str, out_dir: Path) -> int:
    evp = hist / f"{guid}.events"
    if not evp.exists():
        print(f"不存在该会话的事件文件: {evp}", file=sys.stderr)
        return 1
    events = load_events(evp)
    asp = hist / f"{guid}.agentsession"
    agent_raw = asp.read_text(encoding="utf-8").strip() if asp.exists() else "(未知/无 .agentsession)"
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / OUT_MD.format(guid=guid)
    jsonl_path = out_dir / OUT_JSONL.format(guid=guid)
    md_path.write_text(render_md(guid, agent_raw, events), encoding="utf-8")
    with jsonl_path.open("w", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"OK 可读对话: {md_path} ({md_path.stat().st_size} bytes)")
    print(f"OK 原始JSON: {jsonl_path} ({jsonl_path.stat().st_size} bytes)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="导出 JetBrains IDEA AI Assistant 会话")
    ap.add_argument("--list", action="store_true", help="列出所有会话（不导出）")
    ap.add_argument("--session", help="要导出的会话 GUID")
    ap.add_argument("--ide-name", default=DEFAULT_IDE, help=f"IDE 配置目录名，默认 {DEFAULT_IDE}")
    ap.add_argument("--out-dir", default=None, help="导出目录，默认系统 Downloads")
    args = ap.parse_args()

    hist = history_dir(args.ide_name)
    if not hist.is_dir():
        print(f"找不到 aia-task-history: {hist}", file=sys.stderr)
        print(f"IDE 名（当前 {args.ide_name}）不对的话，看看上级目录有哪些：", file=sys.stderr)
        for p in sorted(hist.parent.parent.glob("*")):
            print(f"  {p.name}", file=sys.stderr)
        return 1

    if args.list:
        return cmd_list(hist)
    if not args.session:
        print("请指定 --session <GUID>，或用 --list 查看现有会话", file=sys.stderr)
        return 2
    out_dir = Path(args.out_dir) if args.out_dir else default_out_dir()
    return cmd_export(hist, args.session, out_dir)


if __name__ == "__main__":
    sys.exit(main())