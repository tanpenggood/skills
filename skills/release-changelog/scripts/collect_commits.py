#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""收集 git 提交范围的结构化数据，供发版 CHANGELOG 分析使用。

核心思想：净变更优先（net diff first）。
发版评审关心的是「范围基线版本 → 终态」的整体差异，而不是范围内逐个 commit 的中间演变：
- 范围内新建的文件：净 diff 中即为完整终态，直接按新代码理解，无需逐 commit 追踪演变；
- 范围内来回修改、最终相互抵消的改动：不出现在净 diff 中，也不应进 CHANGELOG；
- commit message 与 hash 只用于条目归组和溯源标注，事实认定以净 diff 为准。

只依赖 Python 标准库与本机 git，不依赖任何第三方包。

用法：
  # 起点 commit（不含）到分支最新提交：净 diff = git diff since..target（精确）
  python collect_commits.py --repo D:/code/myapp --branch main --since 3f9a1c2 --out report.json

  # 单个 merge commit（PR 合入）：自动解析 PR 分支 commits，净 diff = git diff merge^1 merge（精确）
  python collect_commits.py --repo . --branch main --merge 75435a71 --out report.json

  # 显式 commit 列表：为连续父链时净 diff 精确；否则标记 exact=false 并给出警告
  python collect_commits.py --repo . --branch release --commits abc1234,def5678 --out report.json

  # 完整净 patch 落盘，供后续精读
  python collect_commits.py --repo . --branch main --since 3f9a1c2 --out report.json --diff-out full.diff

  # 旧行为：额外采样每个 commit 各自的 diff（仅在需要定位某个 commit 时使用）
  python collect_commits.py ... --per-commit-diffs
"""

import argparse
import json
import os
import re
import subprocess
import sys

REC = "\x1e"  # 记录分隔符：每个 commit 一条
SEP = "\x1f"  # 字段分隔符

NUMSTAT_RE = re.compile(r"^(\d+|-)\t(\d+|-)\t(.*)$")

CONVENTIONAL_RE = re.compile(
    r"^(?P<type>feat|fix|perf|refactor|docs|test|build|ci|chore|style|revert|hotfix)"
    r"(?:\((?P<scope>[^)]*)\))?(?P<breaking>!)?\s*[::]?\s*(?P<desc>.*)$",
    re.IGNORECASE,
)

# 风险信号：按路径模式匹配。命中即代表该改动可能影响发版稳定性。
RISK_PATTERNS = [
    ("数据库变更/迁移", r"(^|/)(migrations?|migrate|alembic|flyway|liquibase|db/migration)(/|$)|\.sql$"),
    ("脚本执行", r"\.(sh|bash|zsh|ps1|bat|cmd)$|(^|/)(scripts?|deploy|deployment|ops|tools)(/|$)|(^|/)(Makefile|Dockerfile|docker-compose[^/]*)$"),
    ("CI/CD 流水线", r"(^|/)(\.github/workflows|\.gitlab-ci\.yml|\.circleci|Jenkinsfile|azure-pipelines[^/]*|\.drone\.yml|bitbucket-pipelines\.yml)(/|$)"),
    ("配置/环境变量", r"(^|/)(config|conf|settings|etc)(/|$)|\.(env|properties|ini|conf|toml|yml|yaml)$|(^|/)application(-[a-z0-9]+)?\.(yml|yaml|properties)$|(^|/)\.env"),
    ("依赖升级", r"(^|/)(package\.json|package-lock\.json|yarn\.lock|pnpm-lock\.yaml|requirements[^/]*\.txt|Pipfile|Pipfile\.lock|pyproject\.toml|poetry\.lock|pom\.xml|build\.gradle(\.kts)?|go\.mod|go\.sum|Cargo\.toml|Cargo\.lock|Gemfile|Gemfile\.lock|[^/]*\.csproj|[^/]*\.sln)$"),
    ("接口契约/协议", r"\.(proto|graphql|gql|thrift|wsdl)$|(^|/)(openapi|swagger)[^/]*\.(json|yaml|yml)$|(^|/)(api|apis|controller|controllers|routes?|rpc|grpc)(/|$)"),
    ("鉴权/安全", r"(^|/)(auth|authn|authz|security|permission|permissions|rbac|crypto|secret|secrets|token|jwt|session|oauth)(/|$)|(auth|security|permission|token|secret|password|credential|encrypt|decrypt|signature)[^/]*\.(py|java|go|ts|tsx|js|jsx|rb|cs|php)$"),
    ("基础设施/编排", r"(^|/)(terraform|tf|k8s|kubernetes|helm|charts?|ansible|puppet|chef)(/|$)|\.(tf|tfvars|ya?ml)$"),
    ("前端/UI", r"\.(vue|tsx|jsx|svelte|html|css|scss|less)$|(^|/)(src/views|src/pages|pages|components|web|frontend|ui)(/|$)"),
    ("测试代码", r"(^|/)(tests?|__tests__|spec|specs|e2e|cypress)(/|$)|\.(test|spec)\.[a-z]+$"),
    ("文档", r"\.(md|mdx|rst|adoc)$|(^|/)(docs?|doc)(/|$)"),
]

BREAKING_MARKERS = [
    r"BREAKING[ -]CHANGE",
    r"breaking[:\s]",
    r"不兼容",
    r"破坏性",
]

# 需要阅读 diff 的「核心代码」扩展名
CODE_EXT = {
    ".py", ".java", ".kt", ".go", ".ts", ".tsx", ".js", ".jsx", ".vue",
    ".rb", ".php", ".cs", ".c", ".cc", ".cpp", ".h", ".hpp", ".rs", ".swift",
    ".scala", ".groovy", ".sql", ".sh", ".proto",
}

# 净 diff 单文件 patch 采样上限（字符）
PATCH_PER_FILE_CAP = 12000


def run_git(repo, args, check=True):
    cmd = ["git", "-C", repo] + args
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
    )
    if check and proc.returncode != 0:
        raise RuntimeError("git 命令失败: %s\n%s" % (" ".join(cmd), proc.stderr.strip()))
    return proc.stdout


def resolve_repo(repo):
    out = run_git(repo, ["rev-parse", "--show-toplevel"], check=False).strip()
    if not out:
        raise RuntimeError("不是一个 git 仓库: %s" % repo)
    return out.replace("/", os.sep)


def resolve_commit(repo, rev):
    out = run_git(repo, ["rev-parse", "--verify", "--quiet", rev + "^{commit}"], check=False).strip()
    return out or None


def strip_body_tail(block):
    """pretty 输出块里，主体之后会紧跟 numstat 行，需把两者切开。"""
    lines = block.split("\n")
    numstat = []
    idx = len(lines)
    while idx > 0:
        m = NUMSTAT_RE.match(lines[idx - 1])
        if not m:
            break
        numstat.insert(0, m.group(0))
        idx -= 1
    body = "\n".join(lines[:idx]).rstrip("\n")
    return body, numstat


def parse_numstat(rows):
    files = []
    add_sum = del_sum = 0
    for row in rows:
        m = NUMSTAT_RE.match(row)
        if not m:
            continue
        a, d, path = m.group(1), m.group(2), m.group(3)
        # 二进制文件
        if a == "-" or d == "-":
            binary = True
            a = d = 0
        else:
            binary = False
            a, d = int(a), int(d)
            add_sum += a
            del_sum += d
        # 重命名：git 可能输出 "a => b" 或 "dir/{a => b}"
        if " => " in path:
            old, new = path.split(" => ", 1)
            if "{" in old and "}" in new:
                prefix = old.split("{")[0]
                old_name = old.split("{")[1]
                suffix = new.split("}")[1]
                old = prefix + old_name + suffix
                new = prefix + new.split("}")[0].replace("{", "") + suffix
            files.append({
                "status": "rename",
                "path": new.strip(),
                "old_path": old.strip().lstrip("{").rstrip("}"),
                "additions": a,
                "deletions": d,
                "binary": binary,
            })
        else:
            files.append({
                "status": "modify",
                "path": path.strip(),
                "additions": a,
                "deletions": d,
                "binary": binary,
            })
    return files, add_sum, del_sum


def classify_by_message(subject):
    m = CONVENTIONAL_RE.match(subject.strip())
    if not m:
        return None, None, False
    return m.group("type").lower(), (m.group("scope") or None), bool(m.group("breaking"))


def detect_risks(path):
    hits = []
    for label, pattern in RISK_PATTERNS:
        if re.search(pattern, path, re.IGNORECASE):
            hits.append(label)
    return hits


def module_of(path, depth):
    parts = path.split("/")
    if len(parts) == 1:
        parts = path.split(os.sep)
    if len(parts) == 1:
        return "(根目录)"
    return "/".join(parts[:min(depth, len(parts) - 1)])


def collect_commits(repo, revs, include_merges, max_commits):
    pretty = REC + SEP.join(["%H", "%an", "%ae", "%aI", "%s", "%b"])
    args = ["log", "--numstat", "--find-renames", "--date-order",
            "--pretty=format:" + pretty]
    if not include_merges:
        args.append("--no-merges")
    args += revs

    raw = run_git(repo, args)
    commits = []
    for block in raw.split(REC):
        block = block.strip("\n")
        if not block.strip():
            continue
        parts = block.split(SEP, 5)
        if len(parts) < 6:
            continue
        h, author, email, date, subject, tail = parts
        body, numstat_rows = strip_body_tail(tail)
        files, adds, dels = parse_numstat(numstat_rows)
        ctype, scope, breaking = classify_by_message(subject)
        commits.append({
            "hash": h.strip(),
            "short_hash": h.strip()[:8],
            "author": author,
            "email": email,
            "date": date.strip(),
            "subject": subject.strip(),
            "body": body.strip(),
            "type_hint": ctype,
            "scope_hint": scope,
            "breaking_hint": breaking,
            "additions": adds,
            "deletions": dels,
            "files": files,
        })
        if len(commits) >= max_commits:
            break
    return commits


# ---------------- 净变更（net diff）----------------

def net_name_status(repo, baseline, target):
    """基线→终态的文件状态列表（A/M/D/R/C/T）。"""
    out = run_git(repo, ["diff", "--name-status", "--find-renames", baseline, target], check=False)
    files = []
    for line in out.splitlines():
        if not line.strip():
            continue
        cols = line.split("\t")
        st = cols[0][0]
        if st in ("R", "C") and len(cols) >= 3:
            files.append({"status": st, "old_path": cols[1], "path": cols[2]})
        elif len(cols) >= 2:
            files.append({"status": st, "old_path": None, "path": cols[1]})
    return files


def net_files_with_stats(repo, baseline, target, commits):
    """合并 name-status、numstat 与 commit 触及记录，得到净变更文件清单。

    additions/deletions 为基线→终态的净增删行数（范围内重复修改已抵消）；
    commits 为触及该路径的 commit 短 hash 列表，仅用于溯源标注。
    """
    rows = run_git(repo, ["diff", "--numstat", "--find-renames", baseline, target], check=False).splitlines()
    stat_by_path = {}
    for r in rows:
        if not NUMSTAT_RE.match(r):
            continue
        fs, _, _ = parse_numstat([r])
        for f in fs:
            stat_by_path[f["path"]] = f

    touched = {}
    for c in commits:
        for f in c["files"]:
            touched.setdefault(f["path"], set()).add(c["short_hash"])

    merged = []
    for item in net_name_status(repo, baseline, target):
        st = stat_by_path.get(item["path"], {})
        merged.append({
            "status": item["status"],
            "path": item["path"],
            "old_path": item.get("old_path"),
            "additions": st.get("additions", 0),
            "deletions": st.get("deletions", 0),
            "binary": st.get("binary", False),
            "commits": sorted(touched.get(item["path"], set())),
        })
    return merged


def net_patch_priority(f):
    """净 diff patch 采样优先级：修改的核心代码 > 修改的其他文件 > 新增文件 > 重命名。删除/二进制不采样。"""
    st = f["status"]
    ext = os.path.splitext(f["path"])[1].lower()
    is_code = ext in CODE_EXT
    if st == "M":
        return 0 if is_code else 1
    if st == "A":
        return 2 if is_code else 3
    if st in ("R", "C", "T"):
        return 4
    return 9


def collect_net_diff(repo, baseline, target, net_files, budget):
    patches = []
    remaining = budget
    truncated = False
    ordered = sorted(
        (f for f in net_files if f["status"] != "D" and not f["binary"]),
        key=lambda f: (net_patch_priority(f), -(f["additions"] + f["deletions"])),
    )
    for f in ordered:
        if remaining <= 0:
            truncated = True
            break
        paths = [p for p in (f.get("old_path"), f["path"]) if p]
        try:
            patch = run_git(repo, ["diff", "--no-color", "--unified=3", baseline, target, "--"] + paths, check=False)
        except Exception:
            continue
        if not patch.strip():
            continue
        cap = min(PATCH_PER_FILE_CAP, remaining)
        if len(patch) > cap:
            patch = patch[:cap] + "\n... [已截断]"
            truncated = True
        remaining -= len(patch)
        patches.append({"path": f["path"], "status": f["status"], "patch": patch})
    return {"patches": patches, "truncated": truncated}


def check_chain(repo, ordered_hashes):
    """判断 commit 序列是否构成连续父链（保证净 diff 精确）。"""
    for prev, cur in zip(ordered_hashes, ordered_hashes[1:]):
        parent = run_git(repo, ["rev-parse", "--verify", "--quiet", cur + "^"], check=False).strip()
        if parent != prev:
            return False
    return True


def enrich_net(net_files, commits, module_depth):
    """基于净变更文件清单做模块聚合与风险扫描（不逐 commit 扫描）。"""
    modules = {}
    risk_items = []
    total_add = total_del = 0
    new_files, deleted_files = [], []
    for f in net_files:
        if f["status"] == "A":
            new_files.append(f["path"])
        if f["status"] == "D":
            deleted_files.append(f["path"])
        mod = module_of(f["path"], module_depth)
        m = modules.setdefault(mod, {"module": mod, "commits": set(), "additions": 0,
                                     "deletions": 0, "files": {}})
        m["additions"] += f["additions"]
        m["deletions"] += f["deletions"]
        m["files"][f["path"]] = f["additions"] + f["deletions"]
        m["commits"].update(f["commits"])
        total_add += f["additions"]
        total_del += f["deletions"]
        for label in detect_risks(f["path"]):
            risk_items.append({
                "category": label,
                "path": f["path"],
                "status": f["status"],
                "additions": f["additions"],
                "deletions": f["deletions"],
                "commits": f["commits"],
            })
        if f["binary"]:
            risk_items.append({"category": "二进制文件变更", "path": f["path"], "status": f["status"],
                               "additions": 0, "deletions": 0, "commits": f["commits"]})
        if f["deletions"] >= 200:
            risk_items.append({"category": "大规模删除", "path": f["path"], "status": f["status"],
                               "additions": f["additions"], "deletions": f["deletions"],
                               "commits": f["commits"]})
    module_list = []
    for m in modules.values():
        module_list.append({
            "module": m["module"],
            "commits": len(m["commits"]),
            "additions": m["additions"],
            "deletions": m["deletions"],
            "files": sorted(m["files"].items(), key=lambda kv: kv[1], reverse=True),
        })
    module_list.sort(key=lambda m: m["additions"] + m["deletions"], reverse=True)
    return {
        "modules": module_list,
        "risk_items": risk_items,
        "new_files": sorted(new_files),
        "deleted_files": sorted(deleted_files),
        "totals": {"additions": total_add, "deletions": total_del, "files_changed": len(net_files)},
    }


def collect_breaking_notes(commits):
    notes = []
    for c in commits:
        text = c["subject"] + "\n" + (c["body"] or "")
        for pat in BREAKING_MARKERS:
            if re.search(pat, text, re.IGNORECASE):
                notes.append({"commit": c["short_hash"], "subject": c["subject"]})
                break
        if c["breaking_hint"] and not any(n["commit"] == c["short_hash"] for n in notes):
            notes.append({"commit": c["short_hash"], "subject": c["subject"]})
    return notes


def collect_per_commit_diffs(repo, commits, budget):
    """旧行为：逐 commit 采样核心代码 diff。仅在需要定位某个 commit 的中间状态时使用。"""
    candidates = []
    for c in commits:
        for f in c["files"]:
            ext = os.path.splitext(f["path"])[1].lower()
            if ext in CODE_EXT and not f["binary"]:
                candidates.append((f["additions"] + f["deletions"], c, f))
    candidates.sort(key=lambda x: x[0], reverse=True)

    diffs = []
    remaining = budget
    for size, c, f in candidates:
        if remaining <= 0:
            break
        try:
            patch = run_git(repo, ["show", "--format=", "--patch", "--no-color",
                                   "--unified=3", c["hash"], "--", f["path"]], check=False)
        except Exception:
            continue
        if not patch.strip():
            continue
        if len(patch) > 8000:
            patch = patch[:8000] + "\n... [已截断]"
        if len(patch) > remaining:
            patch = patch[:remaining] + "\n... [已达 diff 预算上限]"
        remaining -= len(patch)
        diffs.append({"commit": c["short_hash"], "path": f["path"], "patch": patch})
    return diffs


def main():
    p = argparse.ArgumentParser(description="收集 git 提交范围数据用于发版 CHANGELOG 分析（净变更优先）")
    p.add_argument("--repo", default=".", help="git 仓库路径，默认当前目录")
    p.add_argument("--branch", help="生产分支名（main/master/release 等）")
    p.add_argument("--since", help="起始 commit（不含该 commit），到结束 commit 为止")
    p.add_argument("--to", help="结束 commit，默认分支最新提交")
    p.add_argument("--commits", help="显式指定的 commit hash，逗号分隔")
    p.add_argument("--merge", help="单个 merge commit hash：解析其 PR 分支 commits，净 diff = merge^1..merge")
    p.add_argument("--include-merges", action="store_true", help="包含 merge commit")
    p.add_argument("--max-commits", type=int, default=400, help="最多分析多少条 commit")
    p.add_argument("--module-depth", type=int, default=1, help="模块聚合的目录层级，默认 1")
    p.add_argument("--diff-budget", type=int, default=120000, help="净 diff patch 采样的字符预算")
    p.add_argument("--per-commit-diffs", action="store_true",
                   help="额外采样每个 commit 各自的 diff（默认关闭，仅在需定位某个 commit 时使用）")
    p.add_argument("--out", help="JSON 输出文件，默认输出到 stdout")
    p.add_argument("--diff-out", help="可选：把基线→终态的完整净 patch 写入文件")
    args = p.parse_args()

    if not args.commits and not args.merge and not args.branch:
        p.error("必须提供 --branch（生产分支），或提供 --merge / --commits")

    repo = resolve_repo(args.repo)

    baseline = target = None
    range_desc = ""
    exact = True
    net_warning = None

    if args.merge:
        parents = run_git(repo, ["rev-list", "--parents", "-n", "1", args.merge]).split()
        if len(parents) < 3:
            p.error("%s 不是 merge commit（父提交少于 2 个）" % args.merge)
        merge_full, p1, p2 = parents[0], parents[1], parents[2]
        subject = run_git(repo, ["log", "-1", "--format=%s", merge_full]).strip()
        commits = collect_commits(repo, ["%s..%s" % (p1, p2)], False, args.max_commits)
        baseline, target = p1, merge_full
        range_desc = "merge %s「%s」（PR 分支 %d 个 commit）" % (merge_full[:8], subject, len(commits))
    elif args.commits:
        hashes = [h.strip() for h in args.commits.split(",") if h.strip()]
        resolved = []
        for h in hashes:
            full = resolve_commit(repo, h)
            if not full:
                p.error("无法解析 commit: %s" % h)
            resolved.append(full)
        # 逐条拉取，按时间升序排列后校验是否构成连续父链
        commits = []
        for h in resolved:
            commits += collect_commits(repo, ["-1", h], args.include_merges, args.max_commits)
        commits.sort(key=lambda c: c["date"])
        ordered = [c["hash"] for c in commits]
        if ordered:
            baseline = ordered[0]
            target = ordered[-1]
            base_parent = run_git(repo, ["rev-parse", "--verify", "--quiet", baseline + "^"], check=False).strip()
            if base_parent:
                baseline = base_parent
            if len(ordered) >= 2 and not check_chain(repo, ordered):
                exact = False
                net_warning = ("指定的 commit 不是连续父链，净 diff（%s → %s）可能包含范围内其他 commit 的改动；"
                               "建议改用 --since 或 --merge 模式" % (baseline[:8], target[:8]))
        range_desc = "显式指定 %d 个 commit（%s → %s）" % (
            len(resolved),
            ordered[0][:8] if ordered else "-",
            ordered[-1][:8] if ordered else "-",
        )
    else:
        branch_commit = resolve_commit(repo, args.branch)
        if not branch_commit:
            p.error("无法解析生产分支: %s" % args.branch)
        to = args.to or args.branch
        to_commit = resolve_commit(repo, to)
        if not to_commit:
            p.error("无法解析结束 commit: %s" % to)
        if args.since:
            from_commit = resolve_commit(repo, args.since)
            if not from_commit:
                p.error("无法解析起始 commit: %s" % args.since)
            revs = ["%s..%s" % (args.since, to)]
            baseline, target = from_commit, to_commit
            range_desc = "%s..%s" % (args.since[:8], to_commit[:8])
        else:
            revs = [to]
            exact = False
            net_warning = "未指定范围起点（--since/--merge/--commits），无法计算净 diff；请提供 --since 或 --merge"
            range_desc = "%s (全量，未指定起点)" % args.branch
        commits = collect_commits(repo, revs, args.include_merges, args.max_commits)

    if not commits:
        sys.stderr.write("警告：该范围内没有找到任何 commit\n")

    # commit 列表按时间倒序输出（与 CHANGELOG 提交清单一致）
    commits_desc = list(reversed(commits))
    for c in commits_desc:
        c["modules"] = sorted({module_of(f["path"], args.module_depth) for f in c["files"]})

    if baseline and target:
        net_files = net_files_with_stats(repo, baseline, target, commits)
        net = collect_net_diff(repo, baseline, target, net_files, args.diff_budget)
        net_extra = enrich_net(net_files, commits, args.module_depth)
    else:
        net_files = []
        net = {"patches": [], "truncated": False}
        net_extra = {"modules": [], "risk_items": [], "new_files": [], "deleted_files": [],
                     "totals": {"additions": 0, "deletions": 0, "files_changed": 0}}
        exact = False

    all_authors = {}
    dates = []
    for c in commits:
        all_authors[c["author"]] = all_authors.get(c["author"], 0) + 1
        dates.append(c["date"])

    report = {
        "repo": repo,
        "branch": args.branch,
        "range": range_desc,
        "truncated": len(commits) >= args.max_commits,
        "analysis_mode": "net-diff",
        "baseline": baseline[:12] if baseline else None,
        "target": target[:12] if target else None,
        "net_diff": {
            "exact": bool(exact and baseline and target),
            "warning": net_warning,
            "files": net_files,
            "new_files": net_extra["new_files"],
            "deleted_files": net_extra["deleted_files"],
            "patches": net["patches"],
            "truncated": net["truncated"],
        },
        "summary": {
            "commits": len(commits),
            "additions": net_extra["totals"]["additions"],
            "deletions": net_extra["totals"]["deletions"],
            "files_changed": net_extra["totals"]["files_changed"],
            "authors": sorted(all_authors.items(), key=lambda kv: kv[1], reverse=True),
            "first_commit_date": min(dates) if dates else None,
            "last_commit_date": max(dates) if dates else None,
        },
        "modules": net_extra["modules"],
        "risk_items": net_extra["risk_items"],
        "breaking_notes": collect_breaking_notes(commits),
        "commits": commits_desc,
        "diffs": collect_per_commit_diffs(repo, commits, args.diff_budget) if args.per_commit_diffs else [],
    }

    if args.diff_out:
        if baseline and target:
            blob = run_git(repo, ["diff", "--no-color", baseline, target], check=False)
        else:
            revs_args = ["--all"] if not args.branch else []
            blob = run_git(repo, ["log", "--patch", "--no-color"] + revs_args, check=False)
        with open(args.diff_out, "w", encoding="utf-8") as fh:
            fh.write(blob)
        report["net_diff"]["full_diff_file"] = os.path.abspath(args.diff_out)

    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(payload)
        sys.stderr.write(
            "已写入 %s（%d 个 commit，净变更 %d 个文件 +%-d/-%-d，净diff精确=%s，%d 个模块，%d 条风险信号）\n"
            % (args.out, len(commits),
               net_extra["totals"]["files_changed"],
               net_extra["totals"]["additions"],
               net_extra["totals"]["deletions"],
               report["net_diff"]["exact"],
               len(net_extra["modules"]), len(net_extra["risk_items"]))
        )
    else:
        sys.stdout.write(payload)


if __name__ == "__main__":
    main()
