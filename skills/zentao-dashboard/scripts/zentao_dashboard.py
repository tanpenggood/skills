"""
ZenDao Dashboard Generator
Usage: python zentao_dashboard.py <host> <port> <cookie> [output_xlsx]

Fetches all "进行中" projects -> their non-closed executions -> all tasks -> xlsx
"""

import re, json, sys, os, http.client
from datetime import datetime


def ensure_stdout():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def fetch(url_path, host, port, cookie):
    conn = http.client.HTTPConnection(host, port, timeout=30)
    conn.request("GET", url_path, headers={"Cookie": cookie})
    resp = conn.getresponse()
    data = resp.read().decode("utf-8")
    conn.close()
    return data


def extract_zenDao_json(html):
    m = re.search(r'<script>data = "(.+?)";</script>', html, re.DOTALL)
    if not m:
        return None
    raw = m.group(1)
    raw = raw.replace('\\"', '"').replace("\\\\", "\\").replace("\\/", "/")
    raw = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", raw)
    return json.loads(raw)


def extract_project_rows(html):
    projects = []
    for m in re.finditer(r'<tr data-id="(\d+)"[^>]*data-status="doing">', html):
        pid = m.group(1)
        snippet = html[m.start() : m.start() + 500]
        nm = re.search(r"class='c-name text-left' title='([^']+)'", snippet)
        name = nm.group(1) if nm else f"Project {pid}"
        projects.append({"id": pid, "name": name})
    return projects


STATUS_MAP = {
    "doing": "进行中", "wait": "未开始", "done": "已完成", "closed": "已关闭",
}

def extract_execution_rows(html):
    execs = []
    for m in re.finditer(r"<tr[^>]*data-id='(\d+)'[^>]*>(.*?)</tr>", html, re.DOTALL):
        eid = m.group(1)
        snippet = m.group(2)
        status_m = re.search(r"class='status-(\w+)\s+text-center'", snippet)
        status = status_m.group(1) if status_m else ""
        if status == "closed":
            continue
        nm = re.search(r"<a[^>]*title='([^']+)'", snippet)
        name = nm.group(1) if nm else f"Execution {eid}"
        date_matches = re.findall(r"(\d{4}-\d{2}-\d{2})", snippet)
        begin = date_matches[0] if len(date_matches) > 0 else ""
        end = date_matches[1] if len(date_matches) > 1 else ""
        execs.append({
            "id": eid, "name": name, "status": STATUS_MAP.get(status, status),
            "begin": begin, "end": end,
        })
    return execs


def fetch_account_map(host, port, cookie, projects):
    mapping = {}
    for proj in projects:
        url = f"/zentao/project-team-{proj['id']}.html"
        try:
            html = fetch(url, host, port, cookie)
            for tr_m in re.finditer(r"<tr>(.*?)</tr>", html, re.DOTALL):
                tr_html = tr_m.group(1)
                am = re.search(r"deleteMemeber\([^,]+,\s*\"([^\"]+)\"", tr_html)
                rm = re.search(r"<a\s+[^>]*>([^<]+)</a>", tr_html)
                if am and rm:
                    mapping[am.group(1)] = rm.group(1).strip()
        except Exception as ex:
            print(f"  WARN: failed to fetch team for project [{proj['id']}]: {ex}")
    if mapping:
        print(f"  -> fetched {len(mapping)} members across all projects")
    return mapping


def map_account(name, account_map):
    return account_map.get(name, name)


def parse_hours(val):
    if isinstance(val, (int, float)):
        v = float(val)
    else:
        v = float(str(val).rstrip("h"))
    return int(v) if v == int(v) else v


def parse_tasks(task_data, exec_name, account_map):
    rows = []
    for item in task_data:
        tid = item["id"]
        nh = item["name"]
        tm = re.search(r"title='([^']+)'", nh)
        name = tm.group(1) if tm else ""

        pri = ""
        ph = item.get("pri", "")
        if "高" in ph:
            pri = "高"
        elif "中" in ph:
            pri = "中"
        elif "低" in ph:
            pri = "低"

        assigned = item.get("assignedToRealName", "") or ""
        sh = item.get("status", "")
        sm = re.search(r"title='([^']+)'", sh)
        status = sm.group(1) if sm else ""

        est = parse_hours(item.get("estimate", "0h"))
        con = parse_hours(item.get("consumed", "0h"))
        left = parse_hours(item.get("left", "0h"))
        progress = item.get("progress", 0)
        team = item.get("team", [])
        bug_ids = ",".join(re.findall(r"bug-view-(\d+)", nh))

        if assigned in ("Closed", "", None):
            assigned = ""

        persons = []
        person_ests = []
        if not team:
            if assigned:
                persons.append(assigned)
                person_ests.append(str(est) if est != int(est) else str(int(est)))
        else:
            for t in team:
                h = parse_hours(t.get("estimate", 0))
                p = map_account(t["account"], account_map)
                if p and p not in ("Closed", ""):
                    persons.append(p)
                    person_ests.append(str(h) if h != int(h) else str(int(h)))

        rows.append(
            {
                "id": tid,
                "exec_name": exec_name,
                "name": name,
                "pri": pri,
                "assigned": assigned,
                "status": status,
                "estimate": est,
                "consumed": con,
                "left": left,
                "progress": progress,
                "persons": " / ".join(persons),
                "person_hours": " / ".join(person_ests),
                "bug_ids": bug_ids,
            }
        )
    return rows


def generate_xlsx(all_rows, projects, execs, output_path):
    try:
        import openpyxl
        from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
    except ImportError:
        print("ERROR: openpyxl not installed. Run: pip install openpyxl")
        sys.exit(1)

    wb = openpyxl.Workbook()

    hfont = Font(bold=True, size=11, color="FFFFFF")
    hfill = PatternFill("solid", fgColor="4472C4")
    halign = Alignment(horizontal="center", vertical="center")
    border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    # ===== Sheet 1: 项目总览 =====
    ws1 = wb.active
    ws1.title = "项目总览"
    headers1 = [
        "项目编号", "项目名称", "迭代数", "所属迭代", "迭代ID", "迭代状态",
        "计划开始", "计划完成", "是否延期", "任务数",
        "总预计(h)", "总消耗(h)", "总剩余(h)",
    ]
    for ci, h in enumerate(headers1, 1):
        c = ws1.cell(row=1, column=ci, value=h)
        c.font, c.fill, c.alignment, c.border = hfont, hfill, halign, border

    today_str = datetime.now().strftime("%Y-%m-%d")
    ri = 2
    for proj in projects:
        p_execs = [e for e in execs if e["project_name"] == proj["name"]]
        for e in p_execs:
            exec_tasks = [r for r in all_rows if r["exec_name"] == e["name"]]
            task_count = len(exec_tasks)
            total_est = sum(r["estimate"] for r in exec_tasks)
            total_con = sum(r["consumed"] for r in exec_tasks)
            total_left = sum(r["left"] for r in exec_tasks)
            is_delayed = ""
            if e["end"] and e["end"] < today_str and e["status"] not in ("已完成", "已关闭"):
                is_delayed = "已延期"
            vals = [
                int(proj["id"]), proj["name"], len(p_execs), e["name"], int(e["id"]),
                e["status"], e["begin"], e["end"], is_delayed, task_count,
                total_est, total_con, total_left,
            ]
            for ci, v in enumerate(vals, 1):
                c = ws1.cell(row=ri, column=ci, value=v)
                c.border = border
                c.alignment = halign if ci not in {2, 4} else Alignment(vertical="center")
            ri += 1

    ws1.column_dimensions["A"].width = 10
    ws1.column_dimensions["B"].width = 40
    ws1.column_dimensions["D"].width = 36
    for col in "CEFGHIJKL":
        ws1.column_dimensions[col].width = 12

    # ===== Sheet 2: 任务明细 =====
    ws2 = wb.create_sheet("任务明细")
    headers2 = [
        "任务ID", "所属迭代", "任务名称", "优先级", "当前指派",
        "状态", "预计(h)", "消耗(h)", "剩余(h)", "进度(%)",
        "指派给", "来源Bug",
    ]
    for ci, h in enumerate(headers2, 1):
        c = ws2.cell(row=1, column=ci, value=h)
        c.font, c.fill, c.alignment, c.border = hfont, hfill, halign, border

    STATUS_FILLS = {
        "未开始": PatternFill("solid", fgColor="FFF2CC"),
        "进行中": PatternFill("solid", fgColor="D9EAD3"),
        "已完成": PatternFill("solid", fgColor="D0E0F0"),
        "已取消": PatternFill("solid", fgColor="F4CCCC"),
        "已关闭": PatternFill("solid", fgColor="E0E0E0"),
    }

    TIME_COLS = {7, 8, 9}
    for ri, r in enumerate(all_rows, 2):
        vals = [
            int(r["id"]), r["exec_name"], r["name"], r["pri"], r["assigned"],
            r["status"], r["estimate"], r["consumed"], r["left"], r["progress"],
            r["persons"], r["bug_ids"],
        ]
        for ci, v in enumerate(vals, 1):
            c = ws2.cell(row=ri, column=ci, value=v)
            c.border = border
            c.alignment = halign if ci not in {2, 3, 5, 11, 12} else Alignment(vertical="center", wrap_text=True)
            if ci in TIME_COLS and isinstance(v, (int, float)):
                c.number_format = "0.##" if isinstance(v, float) else "0"

        if r["status"] in STATUS_FILLS:
            ws2.cell(row=ri, column=6).fill = STATUS_FILLS[r["status"]]

    widths2 = [8, 40, 52, 8, 18, 10, 10, 10, 10, 10, 24, 14]
    for i, w in enumerate(widths2):
        ws2.column_dimensions[chr(65 + i)].width = w

    ws1.freeze_panes = "A2"
    ws2.freeze_panes = "A2"

    wb.save(output_path)
    return True


def main():
    ensure_stdout()

    args = sys.argv[1:]
    if len(args) < 3:
        print("Usage: python zentao_dashboard.py <host> <port> <cookie> [output_xlsx]")
        print("  <host>    ZenDao server host (e.g. 127.0.0.1)")
        print("  <port>    ZenDao server port (e.g. 10086)")
        print("  <cookie>  Cookie string from browser DevTools")
        print("  [output]  Optional output xlsx path")
        sys.exit(1)

    host = args[0]
    port = int(args[1])
    cookie = args[2]
    default_dir = os.path.join(os.getcwd(), "outputs")
    os.makedirs(default_dir, exist_ok=True)
    output_path = args[3] if len(args) > 3 else os.path.join(
        default_dir, f"禅道数据看板_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    )

    # Step 1: Doing projects
    print("Fetching doing projects...")
    ph = fetch("/zentao/project-browse-0-doing.html", host, port, cookie)
    projects = extract_project_rows(ph)
    print(f"Found {len(projects)} doing projects.")

    # Step 1.5: Fetch account → realname mapping from first project's team page
    print("Fetching account mapping...")
    account_map = fetch_account_map(host, port, cookie, projects)

    # Step 2: Doing executions per project
    all_execs = []
    for proj in projects:
        print(f"  Project [{proj['id']}] {proj['name']} ...")
        try:
            eh = fetch(f"/zentao/project-execution-all-{proj['id']}.html", host, port, cookie)
            execs = extract_execution_rows(eh)
            for e in execs:
                e["project_name"] = proj["name"]
            all_execs.extend(execs)
            print(f"    -> {len(execs)} executions")
        except Exception as ex:
            print(f"    ERROR: {ex}")

    # Step 3: All tasks per execution
    all_rows = []
    for exec_ in all_execs:
        print(f"  Execution [{exec_['id']}] {exec_['name']} ...")
        try:
            th = fetch(f"/zentao/execution-task-{exec_['id']}-all-0--27-1000-1.html", host, port, cookie)
            td = extract_zenDao_json(th)
            if td:
                rows = parse_tasks(td, exec_["name"], account_map)
                all_rows.extend(rows)
                print(f"    -> {len(rows)} tasks")
            else:
                print("    -> no data")
        except Exception as ex:
            print(f"    ERROR: {ex}")

    if not all_rows:
        print("No tasks found. Check cookie validity.")
        sys.exit(1)

    # Step 4: Generate xlsx
    print(f"\nGenerating {output_path} ...")
    generate_xlsx(all_rows, projects, all_execs, output_path)
    print(f"Done! {len(projects)} projects, {len(all_execs)} executions, {len(all_rows)} tasks.")


if __name__ == "__main__":
    main()
