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
  python export_aia_sessions.py --list                # 列出会话（含推断项目）
  python export_aia_sessions.py --summary             # 按推断项目汇总
  python export_aia_sessions.py --session <GUID> [--ide-name IntelliJIdea2026.2] [--out-dir …]

所属项目推断：.events 不含项目字段，但含文件路径（查看文件/改动/工具参数等）；
绝对路径与 IDE options/recentProjects.xml 里的已知项目根做最长前缀匹配得出；
部分代理（ACP 等）只记相对项目根的路径，再按"在且仅在一个已知根下存在"归属。
"""

import argparse
import base64
import json
import os
import platform
import re
import sys
from collections import Counter
from pathlib import Path

DEFAULT_IDE = "IntelliJIdea2026.2"
OUT_MD = "aia-session-{guid}.md"
OUT_JSONL = "aia-session-{guid}.jsonl"

PATH_KEYS = {
    "files", "beforepath", "afterpath", "filepath", "parentdir", "workspace",
    "cwd", "targetdir", "path", "dir", "directory", "outpath", "outputpath",
    "destpath", "srcdir", "sourceroot",
}

_REL_ROOT_CACHE = {}


def _norm_relative(s: str):
    """把候选串规整为项目根相对路径；不是相对路径（绝对/带盘符/空）则返回 None。"""
    s = s.replace("\\", "/").strip()
    while s.startswith("./"):
        s = s[2:]
    s = s.rstrip("/")
    if not s or s in (".", "..") or s.startswith("/") or ":" in s.split("/")[0]:
        return None
    return s


def _match_relative(projects: list, rel: str):
    """相对路径（ACP 等代理只记项目根相对路径）归属：在且仅在一个已知项目根下存在时返回该根下标。

    存在于多个根下说明无区分度，返回 None，避免把票投给错误项目。
    """
    s = _norm_relative(rel)
    if s is None:
        return None
    if s not in _REL_ROOT_CACHE:
        hits = [i for i, p in enumerate(projects) if os.path.exists(os.path.join(p, s))]
        _REL_ROOT_CACHE[s] = hits[0] if len(hits) == 1 else -1
    idx = _REL_ROOT_CACHE[s]
    return idx if idx >= 0 else None


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


def load_projects(cfg: Path) -> list:
    """从 IDE 的 options/recentProjects.xml 读取已知项目根目录（最长的在前）。"""
    xml_path = cfg / "options" / "recentProjects.xml"
    if not xml_path.exists():
        return []
    xml = xml_path.read_text(encoding="utf-8-sig", errors="ignore")
    projects = set()
    for m in re.finditer(r'<entry\s+key="([^"]+)"', xml):
        key = m.group(1)
        key = key.replace("$USER_HOME$", str(Path.home()))
        key = key.replace("$APPLICATION_CONFIG_DIR$", str(cfg))
        if "light-edit" in key.lower():
            continue
        key = key.replace("\\", "/").rstrip("/")
        if key:
            projects.add(key)
    return sorted(projects, key=len, reverse=True)


def infer_project(projects: list, events: list):
    """从事件中的路径推断会话所属项目。

    返回 (project | None, 命中数, 参与匹配的路径数)。
    事件不含项目字段；绝对路径以 project 根为前缀的最长匹配作为项目归属；
    相对路径（部分代理只记相对项目根的路径）按在已知根下的唯一存在性归属。
    """
    if not projects:
        return None, 0, 0
    norm = [p.lower() for p in projects]
    counts = Counter()
    total = 0
    candidates = []

    def collect_paths(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, str):
                    if isinstance(k, str) and k.lower() in PATH_KEYS:
                        candidates.append((v, True))
                    elif re.match(r"^[a-zA-Z]:[\\/]", v) or v.startswith("/"):
                        candidates.append((v, False))
                else:
                    collect_paths(v)
        elif isinstance(o, list):
            for v in o:
                collect_paths(v)
        elif isinstance(o, str):
            if re.match(r"^[a-zA-Z]:[\\/]", o) or o.startswith("/"):
                candidates.append((o, False))

    for e in events:
        collect_paths(e)
    for s, keyed in candidates:
        total += 1
        ss = s.replace("\\", "/").lower()
        for idx, p in enumerate(norm):
            if ss == p or ss.startswith(p + "/"):
                counts[idx] += 2
                break
        else:
            if keyed:
                idx = _match_relative(projects, s)
                if idx is not None:
                    counts[idx] += 1
    if counts:
        idx, n = counts.most_common(1)[0]
        return projects[idx], n, total
    return None, 0, total


def infer_project_all(projects: list, events: list) -> list:
    """项目推断的"展开"版：返回所有命中过的项目及命中路径数，按命中数降序。

    一个会话可能同时操作多个项目（或根/子项目都命中），默认只取最优，
    用 --project-all 时按全部命中统计。
    """
    if not projects:
        return []
    norm = [p.lower() for p in projects]
    counts = Counter()

    def collect_paths(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, str):
                    keyed = isinstance(k, str) and k.lower() in PATH_KEYS
                    if not keyed and not (re.match(r"^[a-zA-Z]:[\\/]", v) or v.startswith("/")):
                        continue
                    s = v.replace("\\", "/").lower().rstrip("/")
                    for idx, p in enumerate(norm):
                        if s == p or s.startswith(p + "/"):
                            counts[idx] += 2
                            break
                    else:
                        if keyed:
                            idx = _match_relative(projects, v)
                            if idx is not None:
                                counts[idx] += 1
                else:
                    collect_paths(v)
        elif isinstance(o, list):
            for v in o:
                collect_paths(v)
        elif isinstance(o, str):
            if re.match(r"^[a-zA-Z]:[\\/]", o) or o.startswith("/"):
                s = o.replace("\\", "/").lower().rstrip("/")
                for idx, p in enumerate(norm):
                    if s == p or s.startswith(p + "/"):
                        counts[idx] += 2
                        break

    for e in events:
        collect_paths(e)
    return sorted(((projects[i], c) for i, c in counts.items()),
                  key=lambda pc: (-pc[1], -len(pc[0])))


def render_md(guid: str, agent_raw: str, events: list, project: str = None) -> str:
    out = []
    out.append(f"# AI Assistant 会话导出 {guid}")
    out.append("")
    out.append(f"底层代理: {agent_raw}")
    out.append(f"事件数: {len(events)}")
    if project:
        out.append(f"所属项目: {project}")
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


def cmd_list(hist: Path, projects: list, project=None, unknown: bool = False) -> int:
    rows = []
    for ap in sorted(hist.glob("*.agentsession"), key=lambda p: p.stat().st_mtime, reverse=True):
        guid = ap.stem
        agent_raw = ap.read_text(encoding="utf-8").strip()
        ev = hist / f"{guid}.events"
        n = 0
        proj = None
        if ev.exists():
            try:
                evs = load_events(ev)
                n = len(evs)
                proj, _, _ = infer_project(projects, evs)
            except Exception:
                n = -1
        if unknown and proj:
            continue
        if project and not (proj and project.lower() in proj.lower()):
            continue
        rows.append((ap.stat().st_mtime, guid, proj, agent_raw.split(":", 1)[0], agent_raw, n))
    if not rows:
        print("无匹配会话。")
        return 0
    w = max(len(r[1]) for r in rows)
    pw = max([len(r[2] or "(未知)") for r in rows] + [8])
    for _, guid, proj, agent, agent_raw, n in rows:
        projname = proj.rsplit("/", 1)[-1] if proj else "(未知)"
        print(f"{guid:<{w}}  {projname:<{pw}}  {agent:<24}  events={n:>4}  {agent_raw}")
    print(f"\n共 {len(rows)} 个 .agentsession（其中 .events 有事件记录的 {(sum(1 for r in rows if r[5] > 0))} 个），"
          f"可识别项目 {(sum(1 for r in rows if r[2]))} 个")
    return 0


def cmd_summary(hist: Path, projects: list, project_all: bool = False) -> int:
    acc = Counter()
    tot = Counter()
    for ap in sorted(hist.glob("*.agentsession")):
        guid = ap.stem
        ev = hist / f"{guid}.events"
        if not ev.exists():
            continue
        try:
            evs = load_events(ev)
            if project_all:
                matches = infer_project_all(projects, evs)
                for proj, n in matches:
                    acc[proj] += 1
                    tot[proj] += n
                continue
            proj, n, _ = infer_project(projects, evs)
        except Exception:
            continue
        acc[proj] += 1
        tot[proj] += n
    suffix = "（--project-all：会话按命中的每个项目都计数，合计可超过会话数）" if project_all else ""
    print(f"项目分布（按会话数倒序；共 {sum(acc.values())} 个有 .events 的会话）{suffix}:")
    for p, n in acc.most_common():
        name = p if p else "(未知项目 / 无文件路径可推断)"
        print(f"{n:>4} 个会话  路径命中{tot[p]:>4}  {name}")
    return 0


def cmd_export(hist: Path, guid: str, out_dir: Path, projects: list) -> int:
    evp = hist / f"{guid}.events"
    if not evp.exists():
        print(f"不存在该会话的事件文件: {evp}", file=sys.stderr)
        return 1
    events = load_events(evp)
    asp = hist / f"{guid}.agentsession"
    agent_raw = asp.read_text(encoding="utf-8").strip() if asp.exists() else "(未知/无 .agentsession)"
    proj, _, _ = infer_project(projects, events)
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / OUT_MD.format(guid=guid)
    jsonl_path = out_dir / OUT_JSONL.format(guid=guid)
    md_path.write_text(render_md(guid, agent_raw, events, proj), encoding="utf-8")
    with jsonl_path.open("w", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"OK 可读对话: {md_path} ({md_path.stat().st_size} bytes)")
    print(f"OK 原始JSON: {jsonl_path} ({jsonl_path.stat().st_size} bytes)")
    if proj:
        print(f"所属项目: {proj}（由事件中的文件路径前缀匹配推断）")
    else:
        print("所属项目: 无法推断（事件中没有已知项目内的文件路径）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="导出 JetBrains IDEA AI Assistant 会话")
    ap.add_argument("--list", action="store_true", help="列出所有会话（含推断项目，不导出）")
    ap.add_argument("--summary", action="store_true", help="按推断项目汇总会话数")
    ap.add_argument("--session", help="要导出的会话 GUID")
    ap.add_argument("--ide-name", default=DEFAULT_IDE, help=f"IDE 配置目录名，默认 {DEFAULT_IDE}")
    ap.add_argument("--out-dir", default=None, help="导出目录，默认系统 Downloads")
    ap.add_argument("--project", default=None, help="与 --list 一起用：只列出该项目名/路径含该子串的会话")
    ap.add_argument("--unknown", action="store_true", help="与 --list 一起用：只列出推断不出项目的会话")
    ap.add_argument("--project-all", action="store_true", help="与 --summary 一起用：按命中的每个项目都计数（可跨项目）")
    args = ap.parse_args()

    hist = history_dir(args.ide_name)
    if not hist.is_dir():
        print(f"找不到 aia-task-history: {hist}", file=sys.stderr)
        print(f"IDE 名（当前 {args.ide_name}）不对的话，看看上级目录有哪些：", file=sys.stderr)
        for p in sorted(hist.parent.parent.glob("*")):
            print(f"  {p.name}", file=sys.stderr)
        return 1

    projects = load_projects(hist.parent) if (args.list or args.summary or args.session) else []

    if args.list:
        return cmd_list(hist, projects, args.project, args.unknown)
    if args.summary:
        return cmd_summary(hist, projects, args.project_all)
    if not args.session:
        print("请指定 --session <GUID>，或用 --list 查看现有会话", file=sys.stderr)
        return 2
    out_dir = Path(args.out_dir) if args.out_dir else default_out_dir()
    return cmd_export(hist, args.session, out_dir, projects)


if __name__ == "__main__":
    sys.exit(main())