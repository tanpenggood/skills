#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scan_repo.py — 企业级应用源码静态扫描器

用途：对一个陌生应用的源码仓库做全量静态扫描，产出结构化的"系统事实快照"，
      作为 AI 编写《应用交接文档》（业务/技术/运维/新人速查四分册）的素材底稿。

支持栈：
  - Java / Maven / Spring Boot / Spring Cloud / MyBatis / JPA / Dubbo
  - Python (requirements / pyproject / Flask / FastAPI / Django / Celery)
  - Node.js (package.json / Express / Nest)

设计原则：
  - 纯标准库，零依赖，可直接用系统 python 运行
  - 只采集"事实"（代码里客观存在的东西），不做推断和猜测
  - 静态启发式扫描必然有误报漏报，输出仅供 AI 二次核实，不可直接当结论

用法：
  python scan_repo.py <repo_path> [-o output_dir] [--depth N]

输出：在 output_dir 下生成一组 markdown 文件 + 一份 JSON 汇总。
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------- 常量配置

VERSION = "1.0.0"

SKIP_DIRS = {
    ".git", ".svn", ".hg", ".idea", ".vscode", ".settings",
    "target", "build", "dist", "out", "bin", "obj",
    "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache",
    "venv", ".venv", "env", "virtualenv", "site-packages",
    ".gradle", ".mvn", "coverage", ".next", ".nuxt", "vendor",
    "_handover_scan",
}

# 参与代码扫描的扩展名及其语言
CODE_EXT = {
    ".java": "Java", ".kt": "Kotlin", ".scala": "Scala", ".groovy": "Groovy",
    ".py": "Python",
    ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
    ".cs": "C#", ".go": "Go", ".rb": "Ruby", ".php": "PHP",
    ".sql": "SQL",
    ".yml": "YAML", ".yaml": "YAML", ".xml": "XML", ".properties": "Properties",
    ".json": "JSON", ".toml": "TOML", ".conf": "Config", ".env": "Env",
    ".sh": "Shell", ".bat": "Shell", ".ps1": "Shell",
    "Dockerfile": "Docker", ".dockerfile": "Docker",
    ".md": "Markdown", ".html": "HTML", ".css": "CSS", ".vue": "Vue",
}

MAX_FILE_BYTES = 2 * 1024 * 1024   # 单文件超过 2MB 跳过内容分析
LANG_LINE_LIMIT = 200000           # 单语言累计扫描行数上限，防止超大仓库卡死

# 依赖 -> 中间件/能力映射（决定"技术架构"章节里画什么框）
MW_HINTS = {
    r"mysql-connector|com\.mysql|mysql:mysql": "MySQL 数据库",
    r"postgresql|org\.postgresql": "PostgreSQL 数据库",
    r"oracle|ojdbc": "Oracle 数据库",
    r"sqlserver|mssql-jdbc": "SQL Server 数据库",
    r"clickhouse": "ClickHouse 列存数据库",
    r"dameng|dm-jdbc": "达梦数据库（国产化）",
    r"kingbase": "人大金仓数据库（国产化）",
    r"oceanbase": "OceanBase 数据库",
    r"mybatis": "MyBatis ORM",
    r"hibernate|spring-boot-starter-data-jpa|javax\.persistence|jakarta\.persistence": "JPA/Hibernate ORM",
    r"druid|hikari": "数据库连接池",
    r"shardingsphere|sharding-jdbc": "ShardingSphere 分库分表",
    r"dynamic-datasource": "多数据源",
    r"spring-boot-starter-data-redis|jedis|lettuce|redisson": "Redis 缓存",
    r"spring-kafka|kafka-clients": "Kafka 消息队列",
    r"spring-rabbit|amqp": "RabbitMQ 消息队列",
    r"rocketmq": "RocketMQ 消息队列",
    r"activemq|artemis": "ActiveMQ 消息队列",
    r"elasticsearch|spring-boot-starter-data-elasticsearch": "Elasticsearch 检索",
    r"mongodb|mongo-driver": "MongoDB 文档库",
    r"clickhouse-driver": "ClickHouse",
    r"spring-cloud-openfeign|feign": "OpenFeign 声明式 HTTP 调用",
    r"dubbo": "Dubbo RPC",
    r"grpc": "gRPC RPC",
    r"thrift": "Thrift RPC",
    r"sentinel": "Sentinel 流控熔断",
    r"hystrix": "Hystrix 熔断",
    r"resilience4j": "Resilience4j 容错",
    r"nacos": "Nacos 注册中心/配置中心",
    r"eureka": "Eureka 注册中心",
    r"consul": "Consul 注册中心",
    r"zookeeper|curator": "ZooKeeper 协调服务",
    r"apollo": "Apollo 配置中心",
    r"spring-cloud-config": "Spring Cloud Config 配置中心",
    r"xxl-job": "XXL-JOB 分布式任务调度",
    r"quartz": "Quartz 定时任务",
    r"elastic-job": "ElasticJob 任务调度",
    r"powerjob": "PowerJob 任务调度",
    r"spring-boot-starter-security|shiro|sa-token": "认证鉴权框架",
    r"jwt|jjwt": "JWT 令牌鉴权",
    r"oauth2": "OAuth2 授权",
    r"cas-?client": "CAS 单点登录",
    r"minio": "MinIO 对象存储",
    r"aliyun.*oss|aliyun-sdk-oss": "阿里云 OSS 对象存储",
    r"aliyun.*sms|dysmsapi": "阿里云短信",
    r"cos-?api|qcloud": "腾讯云 COS 对象存储",
    r"qiniu": "七牛云存储",
    r"fastdfs": "FastDFS 文件存储",
    r"nginx-ingress|ingress": "Ingress 网关",
    r"spring-cloud-gateway": "Spring Cloud Gateway 网关",
    r"zuul": "Zuul 网关",
    r"skywalking|opentracing|micrometer|prometheus|actuator": "链路追踪/监控埋点",
    r"logback|log4j2?|slf4j": "日志框架",
    r"sentry": "Sentry 异常上报",
    r"poi|easyexcel": "Excel 导入导出",
    r"itext|pdfbox": "PDF 生成",
    r"zxing|qrcode": "二维码生成",
    r"weixin|wx-java|wechat": "微信生态对接",
    r"alipay": "支付宝对接",
    r"swagger|springdoc|knife4j|openapi": "接口文档（Swagger/OpenAPI）",
    r"lombok": "Lombok 代码简化",
    r"fastjson|jackson|gson": "JSON 序列化",
    r"hutool": "Hutool 工具库",
    r"guava": "Guava 工具库",
    r"mapstruct": "MapStruct 对象映射",
    r"junit|mockito|testcontainers": "单元测试框架",
    r"selenium|playwright": "UI 自动化测试",
    r"flyway|liquibase": "数据库版本迁移",
    r"celery": "Celery 异步任务队列",
    r"django": "Django 框架",
    r"flask": "Flask 框架",
    r"fastapi": "FastAPI 框架",
    r"sqlalchemy": "SQLAlchemy ORM",
    r"redis.*python|aioredis": "Redis 缓存",
    r"pymysql|psycopg2|cx_Oracle": "数据库连接驱动",
    r"gunicorn|uwsgi": "WSGI 应用服务器",
    r"express": "Express 框架",
    r"nest": "Nest 框架",
    r"koa": "Koa 框架",
    r"typeorm|sequelize|prisma|mongoose": "Node ORM",
    r"bull|agenda|node-cron|node-schedule": "Node 任务调度",
    r"socket\.io|ws": "WebSocket 实时通信",
    r"axios|request\b|got": "HTTP 客户端",
    r"passport|jsonwebtoken|bcrypt": "Node 认证鉴权",
}

SENSITIVE_KEY_PAT = re.compile(
    r"(password|passwd|secret|token|private[-_]?key|access[_-]?key|"
    r"app[_-]?secret|api[_-]?key|credential|signature|凭证|密码|密钥)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------- 基础工具

def try_decode(raw: bytes) -> str:
    """容错解码：UTF-8 -> GB18030 -> Latin-1"""
    for enc in ("utf-8-sig", "gb18030", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return ""


def read_text(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return ""
        return try_decode(path.read_bytes())
    except OSError:
        return ""


# 根 pom 关键属性（JDK 版本、编码、框架版本）—— label 与正则必须显式配对，
# 不可用字符串切分推导 label，否则会把正则碎片带进来。
POM_PROP_PATTERNS = [
    ("java.version", r"<java\.version>([^<]+)<"),
    ("maven.compiler.source", r"<maven\.compiler\.source>([^<]+)<"),
    ("maven.compiler.target", r"<maven\.compiler\.target>([^<]+)<"),
    ("maven.compiler.release", r"<maven\.compiler\.release>([^<]+)<"),
    ("spring-boot.version", r"<spring-boot\.version>([^<]+)<"),
    ("spring.cloud.version", r"<spring\.cloud\.version>([^<]+)<"),
    ("project.build.sourceEncoding", r"<project\.build\.sourceEncoding>([^<]+)<"),
]


def iter_files(root: Path):
    """遍历仓库文件，跳过无关目录"""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            p = Path(dirpath) / fn
            yield p


def rel(p: Path, root: Path) -> str:
    try:
        return str(p.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(p)


def md_table(headers, rows, max_rows=None):
    """生成 markdown 表格，自动转义竖线。rows 为 None/空时返回提示语"""
    if not rows:
        return "_（静态扫描未发现）_\n"
    if max_rows:
        rows = rows[:max_rows]
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        cells = [str(c).replace("|", "\\|").replace("\n", " ") for c in r]
        cells = [c[:300] for c in cells]  # 截断超长单元格
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def clean_comment(text: str) -> str:
    """压缩注释文本为单行"""
    if not text:
        return ""
    text = re.sub(r"^\s*\*+\s?", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*//+\s?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.strip("*/#-=").strip()
    return text[:160]


def classify_comment(line: str) -> int:
    """判断该行是否为注释起始,返回类型: 0非 1块注释起始 2行注释"""
    s = line.strip()
    if s.startswith("/*"):
        return 1
    if s.startswith("//") or s.startswith("*") or s.startswith("///"):
        return 2
    return 0


# ---------------------------------------------------------------- 采集器：仓库概览

def scan_overview(root: Path, files: list) -> dict:
    lang_counter = Counter()
    line_counter = Counter()
    file_counter = Counter()
    big_files = []
    total_bytes = 0

    for p in files:
        ext = p.suffix.lower()
        if p.name.lower().startswith("dockerfile"):
            ext = "Dockerfile"
        lang = CODE_EXT.get(ext)
        if lang is None:
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        total_bytes += size
        file_counter[lang] += 1
        big_files.append((size, rel(p, root)))

        if lang in ("Java", "Python", "JavaScript", "TypeScript", "SQL", "XML"):
            if line_counter[lang] >= LANG_LINE_LIMIT:
                continue
            txt = read_text(p)
            if txt:
                line_counter[lang] += txt.count("\n") + 1

        # 语言分布按文件数（对权重偏低的语言也能体现）
        lang_counter[lang] += 1

    big_files.sort(reverse=True)
    top_big = [(sz, fp) for sz, fp in big_files[:15] if sz > 200 * 1024]

    return {
        "total_files": len(files),
        "total_size_mb": round(total_bytes / 1024 / 1024, 2),
        "file_count_by_lang": dict(file_counter.most_common()),
        "line_count_code": dict(line_counter.most_common()),
        "large_files": top_big,
    }


def scan_git(root: Path) -> dict:
    """采集 git 元信息：远程、最近提交、活跃贡献者、热点文件"""
    info = {}
    if not (root / ".git").exists():
        return {"available": False}

    # 关闭 quotepath，否则中文文件名会被 git 转义成八进制序列
    GIT = ["git", "-c", "core.quotepath=false"]

    def run(args, timeout=15):
        try:
            r = subprocess.run(GIT + args, cwd=str(root), timeout=timeout,
                               capture_output=True, text=True,
                               encoding="utf-8", errors="ignore")
            if r.returncode == 0:
                return r.stdout.strip()
        except Exception:
            pass
        return ""

    def run_raw(args, timeout=15):
        try:
            r = subprocess.run(GIT + args, cwd=str(root), timeout=timeout,
                               capture_output=True)
            if r.returncode == 0:
                return try_decode(r.stdout).strip()
        except Exception:
            pass
        return ""

    info["available"] = True
    info["remote"] = run_raw(["remote", "-v"]) or ""
    info["branch"] = run(["branch", "-vv"]) or ""
    log = run(["log", "-15", "--date=short",
               "--pretty=format:%h|%ad|%an|%s"])
    info["recent_commits"] = [l for l in log.splitlines() if l.strip()]
    # 近半年贡献者排名 —— 用于文档里"该找谁问"
    since = run(["log", "--since=180 days ago", "--pretty=format:%an"])
    authors = [a.strip() for a in since.splitlines() if a.strip()]
    info["active_authors"] = Counter(authors).most_common(12)
    # 最近改动热点文件 —— 反映系统正在进行的工作区域
    hot = run(["log", "--since=180 days ago", "--name-only", "--pretty=format:"])
    hotfiles = [h for h in hot.splitlines()
                if h.strip() and not any(s in h for s in SKIP_DIRS)]
    info["hot_files"] = Counter(hotfiles).most_common(20)
    return info


# ---------------------------------------------------------------- 采集器：构建与依赖

def scan_maven(root: Path, files: list) -> dict:
    poms = [p for p in files if p.name.lower() == "pom.xml"]
    result = {"modules": [], "root_pom": None, "dependencies": [],
              "props": [], "build": []}
    if not poms:
        return result

    # 选层级最浅的作为根 pom
    poms.sort(key=lambda p: len(p.parts))
    root_pom = poms[0]
    result["root_pom"] = rel(root_pom, root)

    # 递归解析每个 pom
    for p in poms:
        txt = read_text(p)
        if not txt:
            continue
        # 去注释
        txt_xml = re.sub(r"<!--.*?-->", "", txt, flags=re.S)
        artifact = re.search(r"<artifactId>([^<]+)</artifactId>(?!(?:(?!<parent|<artifac)[\s\S]){0,400}?</parent>)", txt_xml)
        packaging = re.search(r"<packaging>([^<]+)</packaging>", txt_xml)
        modules = re.findall(r"<module>([^<]+)</module>", txt_xml)
        parent = re.search(r"<parent>\s*<groupId>([^<]+)</groupId>\s*<artifactId>([^<]+)</artifactId>\s*<version>([^<]+)</version>", txt_xml, re.S)
        # 子模块列表
        if modules:
            result["modules"].append({
                "pom": rel(p, root), "modules": modules,
            })
        # parent 继承关系
        if parent and not parent.group(2).startswith("spring-boot"):
            pass
        # 依赖
        for dep in re.findall(r"<dependency>(.*?)</dependency>", txt_xml, re.S):
            g = re.search(r"<groupId>([^<]+)</groupId>", dep)
            a = re.search(r"<artifactId>([^<]+)</artifactId>", dep)
            v = re.search(r"<version>([^<]+)</version>", dep)
            s = re.search(r"<scope>([^<]+)</scope>", dep)
            o = re.search(r"<optional>([^<]+)</optional>", dep)
            if g and a:
                result["dependencies"].append({
                    "ga": f"{g.group(1).strip()}:{a.group(1).strip()}",
                    "version": v.group(1).strip() if v else "(继承父 pom / BOM)",
                    "scope": s.group(1).strip() if s else "compile",
                    "from": rel(p, root),
                })

    # 去重
    seen = set()
    uniq = []
    for d in result["dependencies"]:
        key = (d["ga"], d["from"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(d)
    result["dependencies"] = uniq

    # 根 pom 关键属性（JDK 版本、编码、Spring Boot 版本）
    root_txt = re.sub(r"<!--.*?-->", "", read_text(root_pom), flags=re.S)
    for label, pat in POM_PROP_PATTERNS:
        for m in re.finditer(pat, root_txt):
            result["props"].append((label, m.group(1).strip()))
    pb = re.search(r"<parent>\s*<groupId>([^<]+)</groupId>\s*<artifactId>([^<]+)</artifactId>\s*<version>([^<]+)</version>", root_txt, re.S)
    if pb:
        result["parent"] = f"{pb.group(1)}:{pb.group(2)}:{pb.group(3)}"
    return result


def scan_python_deps(root: Path, files: list) -> dict:
    r = {"requirements": [], "pyproject": [], "files": []}
    for p in files:
        name = p.name.lower()
        if name.startswith("requirements") and p.suffix.lower() in (".txt", ".lock", ""):
            txt = read_text(p)
            for line in txt.splitlines():
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("-"):
                    r["requirements"].append((line, rel(p, root)))
            r["files"].append(rel(p, root))
        elif name in ("pyproject.toml", "pipfile", "poetry.lock", "setup.py"):
            if name == "pyproject.toml":
                txt = read_text(p)
                for m in re.finditer(r'^\s*([A-Za-z0-9_\-\[\]]+)\s*=\s*["\']([^"\']+)["\']', txt, re.M):
                    r["pyproject"].append((m.group(1), m.group(2), rel(p, root)))
                for m in re.finditer(r'^\s*"([a-zA-Z0-9\-_]+)', txt, re.M):
                    pass
            r["files"].append(rel(p, root))
    return r


def scan_node_deps(root: Path, files: list) -> dict:
    r = {"packages": [], "workspaces": []}
    for p in files:
        if p.name.lower() != "package.json":
            continue
        if "node_modules" in str(p):
            continue
        txt = read_text(p)
        try:
            data = json.loads(txt)
        except Exception:
            continue
        entry = {
            "file": rel(p, root),
            "name": data.get("name", ""),
            "version": data.get("version", ""),
            "scripts": data.get("scripts", {}),
            "deps": list(data.get("dependencies", {}).keys()),
            "devDeps": list(data.get("devDependencies", {}).keys()),
        }
        r["packages"].append(entry)
        if data.get("workspaces"):
            r["workspaces"].append((rel(p, root), data["workspaces"]))
    return r


def infer_middleware(dep_names: list) -> list:
    """根据依赖名推断中间件"""
    found = []
    joined = " ".join(dep_names).lower()
    for pat, label in MW_HINTS.items():
        try:
            if re.search(pat, joined, re.IGNORECASE):
                found.append(label)
        except re.error:
            continue
    # 去重保序
    out = []
    for f in found:
        if f not in out:
            out.append(f)
    return out


# ---------------------------------------------------------------- 采集器：Java 源码语义

JAVA_METHOD_KW = {"if", "for", "while", "switch", "catch", "return", "new",
                  "synchronized", "else", "do", "try", "throw", "throws",
                  "public", "private", "protected", "static", "class", "interface"}

JAVA_HTTP_ANN = ("GetMapping", "PostMapping", "PutMapping", "DeleteMapping",
                 "PatchMapping", "RequestMapping")


def _extract_path_from_ann(ann_body: str) -> str:
    """从注解括号内提取路径"""
    # value={"/a","/b"} 或 "/a" 或 value="/a", produces="..."
    strs = re.findall(r'"([^"]*)"', ann_body)
    paths = [s for s in strs if s.startswith("/") or s.startswith("${")]
    if paths:
        return ",".join(dict.fromkeys(paths)) if len(paths) > 1 else paths[0]
    return ""


def _join_path(base: str, sub: str) -> str:
    """拼接类级路径与方法级路径，处理空值与重复斜杠"""
    base = (base or "").strip()
    sub = (sub or "").strip()
    if not sub:
        return base or "/"
    if not base:
        return sub
    return (base.rstrip("/") + "/" + sub.lstrip("/")).replace("//", "/")


def _extract_http_method_from_rm(ann_body: str) -> str:
    m = re.search(r"method\s*=\s*RequestMethod\.(\w+)", ann_body)
    if m:
        return m.group(1).upper()
    return "ALL"


def _find_method_signature(lines: list, start_idx: int, maxtolines=6) -> tuple:
    """从注解位置向下找方法名"""
    for i in range(start_idx + 1, min(start_idx + 1 + maxtolines, len(lines))):
        line = lines[i]
        s = line.strip()
        if not s or s.startswith("//") or s.startswith("*") or s.startswith("@"):
            continue
        m = re.findall(r"\b([A-Za-z_]\w*)\s*\(", s)
        if m:
            cand = m[-1]
            if cand in JAVA_METHOD_KW:
                # 关键字干扰，尝试同一行其他候选
                cand2 = [x for x in m if x not in JAVA_METHOD_KW]
                if not cand2:
                    continue
                cand = cand2[-1]
            return cand, i
    return "", -1


def _collect_doc(lines: list, idx: int) -> str:
    """向上采集最近的注释/Swagger 描述作为接口说明"""
    parts = []
    j = idx - 1
    steps = 0
    while j >= 0 and steps < 14:
        s = lines[j].strip()
        if not s:
            j -= 1
            steps += 1
            if parts:
                break
            continue
        if s.endswith("*/") or s.startswith("*") or s.startswith("//") or s.startswith("/*"):
            # 行注释才收；块注释从 /* 起算
            if s.startswith("/*"):
                parts.append(clean_comment(s))
                break
            parts.append(clean_comment(s))
            j -= 1
            steps += 1
            continue
        m = re.search(r'@(ApiOperation|Operation|Api|ApiOperationSupport)\s*\((.*)\)', s)
        if m:
            v = re.findall(r'"([^"]*)"', m.group(2))
            sm = re.search(r'summary\s*=\s*"([^"]*)"', m.group(2))
            if sm:
                parts.append(clean_comment(sm.group(1)))
            elif v:
                parts.append(clean_comment(v[0]))
            j -= 1
            steps += 1
            continue
        break
    return clean_comment(" ".join(reversed(parts)))


def scan_java_sources(root: Path, files: list) -> dict:
    r = {
        "endpoints": [], "entities": [], "jobs": [], "mq": [],
        "feign": [], "dubbo": [], "configs": [], "rest_security": [],
        "main_classes": [], "mapper_files": [], "todos": [],
        "exception_handlers": [],
    }
    java_files = [p for p in files if p.suffix.lower() == ".java"]
    mapper_files = [p for p in files if p.suffix.lower() == ".xml"]

    # MyBatis Mapper XML
    for p in mapper_files:
        txt = read_text(p)
        if "<mapper" not in txt:
            continue
        ns = re.search(r'<mapper[^>]*namespace\s*=\s*"([\w\.]+)"', txt)
        stmts = Counter(re.findall(r"<(select|insert|update|delete|sql)\s", txt))
        tables = set()
        head = txt[:20000]
        for m in re.finditer(r"(?:from|into|update|join)\s+[`\"]?([\w\.]{2,60})[`\"]?", head, re.I):
            t = m.group(1)
            if t.lower() in ("select", "values", "set", "where", "dual"):
                continue
            if "." in t and t.split(".")[-1]:
                t = t.split(".")[-1]
            if not re.match(r"^[a-zA-Z_]\w*$", t) or not t[0].isalpha():
                continue
            if t.lower() in SQL_NON_TABLE:
                continue
            tables.add(t)
        r["mapper_files"].append({
            "file": rel(p, root),
            "namespace": ns.group(1) if ns else "",
            "statements": dict(stmts),
            "tables": sorted(tables)[:20],
        })

    total = len(java_files)
    for idx, p in enumerate(java_files):
        txt = read_text(p)
        if not txt:
            continue
        lines = txt.splitlines()
        frel = rel(p, root)

        # TODO / FIXME
        for i, line in enumerate(lines, 1):
            if re.search(r"//\s*(TODO|FIXME|XXX|HACK)", line, re.I):
                r["todos"].append((frel, i, clean_comment(line)))

        cls_text = txt
        is_controller = bool(re.search(r"@RestController|@Controller\b", cls_text))
        cls_name = re.search(r"\b(?:public\s+)?(?:abstract\s+)?(?:final\s+)?(?:class|interface|enum)\s+(\w+)", cls_text)
        cls_name = cls_name.group(1) if cls_name else Path(p).stem

        # ---------- HTTP 接口 ----------
        if is_controller:
            class_path = ""
            for i, line in enumerate(lines):
                m = re.search(r"@RequestMapping\s*\((.*)", line)
                if m and _is_class_level(lines, i):
                    ann_body = m.group(1)
                    # 注解括号跨行时向下补齐
                    for extra in range(i + 1, min(i + 4, len(lines))):
                        if ann_body.count("(") <= ann_body.count(")"):
                            break
                        ann_body += " " + lines[extra]
                    class_path = _extract_path_from_ann(ann_body)
                    break

            for i, line in enumerate(lines):
                m = re.match(r"\s*@(Get|Post|Put|Delete|Patch)Mapping\s*(\((.*)\))?\s*$", line)
                if not m:
                    continue
                method_sig, mi = _find_method_signature(lines, i)
                if not method_sig:
                    continue
                sub = _extract_path_from_ann(m.group(3) or "")
                http_method = m.group(1).upper()
                full = _join_path(class_path, sub)
                r["endpoints"].append({
                    "method": http_method,
                    "path": full,
                    "handler": f"{cls_name}.{method_sig}()",
                    "file": frel,
                    "doc": _collect_doc(lines, i) or _collect_doc(lines, mi),
                })

            # 方法级 @RequestMapping(method = RequestMethod.X)
            for i, line in enumerate(lines):
                rm = re.match(r"\s*@RequestMapping\s*\((.*)\)\s*$", line)
                if not rm:
                    continue
                if _is_class_level(lines, i):
                    continue  # 类级注解已在上方提取，不重复计入
                ms, mi = _find_method_signature(lines, i)
                if not ms:
                    continue
                hm = _extract_http_method_from_rm(rm.group(1))
                sub = _extract_path_from_ann(rm.group(1))
                full = _join_path(class_path, sub)
                r["endpoints"].append({
                    "method": hm, "path": full,
                    "handler": f"{cls_name}.{ms}()",
                    "file": frel,
                    "doc": _collect_doc(lines, i) or _collect_doc(lines, mi),
                })

        # ---------- 数据实体 ----------
        if re.search(r"@Entity\b|@TableName\b|@Table\s*\(|@Document\b", cls_text):
            t = re.search(r'@TableName\s*\(\s*(?:value\s*=)?\s*"(\w+)"', cls_text)
            if not t:
                t = re.search(r'@Table\s*\(\s*name\s*=\s*"(\w+)"', cls_text)
            fields = re.findall(
                r"@(?:TableField|Column)\s*\((?:[^)]*?(?:value|column)\s*=\s*)?\"(\w+)\"", cls_text)
            plain_fields = re.findall(
                r"^\s*private\s+(?:static\s+)?final\s+[\w<>,\[\]\.]+?\s+(\w+)\s*(?:=|;)", cls_text, re.M)
            flds = list(dict.fromkeys((fields or []) + (plain_fields or [])))[:40]
            r["entities"].append({
                "class": cls_name,
                "table": t.group(1) if t else "(由类名推断/未显式指定)",
                "fields": flds,
                "file": frel,
                "doc": clean_comment(re.search(r"@ApiModel\s*\(\s*(?:value\s*=)?\s*\"([^\"]*)\"", cls_text).group(1)) if re.search(r"@ApiModel\s*\(\s*(?:value\s*=)?\s*\"([^\"]*)\"", cls_text) else "",
            })

        # ---------- 定时任务 ----------
        for i, line in enumerate(lines):
            sm = re.search(r'@Scheduled\s*\((.*?)\)\s*$', line, re.S)
            if sm:
                body = sm.group(1)
                if body.count("(") > body.count(")"):
                    body += " " + " ".join(lines[i + 1:i + 3])
                cron = re.search(r'cron\s*=\s*"([^"]+)"', body)
                rate = re.search(r'fixedRate\w*\s*=\s*([\w\.]+)', body)
                delay = re.search(r'fixedDelay\w*\s*=\s*([\w\.]+)', body)
                ms, mi = _find_method_signature(lines, i)
                r["jobs"].append({
                    "type": "Spring @Scheduled",
                    "expr": cron.group(1) if cron else (f"fixedRate={rate.group(1)}" if rate else (f"fixedDelay={delay.group(1)}" if delay else "未解析")),
                    "task": f"{cls_name}.{ms}()",
                    "file": frel,
                    "doc": _collect_doc(lines, i),
                })
            xm = re.search(r'@XxlJob\s*\(\s*"([^"]+)"', line)
            if xm:
                ms, mi = _find_method_signature(lines, i)
                r["jobs"].append({
                    "type": "XXL-JOB",
                    "expr": f"JobHandler={xm.group(1)}",
                    "task": f"{cls_name}.{ms}()",
                    "file": frel,
                    "doc": _collect_doc(lines, i),
                })

        # ---------- MQ ----------
        for i, line in enumerate(lines):
            kl = re.search(r'@KafkaListener\s*\((.*)",?\s*$', line) or re.search(r'@KafkaListener\s*\((.*)\)', line)
            if kl:
                body = kl.group(1)
                topics = re.findall(r'topics\s*=\s*(?:\{)?\s*"([^"]+)"|topics\s*=\s*"([^"]+)"', body)
                tp = ",".join([x or y for x, y in topics])
                ms, mi = _find_method_signature(lines, i)
                r["mq"].append({"kind": "Kafka Listener", "target": tp or "(未解析)",
                                "ref": f"{cls_name}.{ms}()", "file": frel,
                                "doc": _collect_doc(lines, i)})
            rl = re.search(r'@RabbitListener\s*\((.*)",?\s*$', line) or re.search(r'@RabbitListener\s*\((.*)\)', line)
            if rl:
                body = rl.group(1)
                q = re.search(r'queues\s*=\s*(?:\{)?\s*"([^"]+)"', body)
                ms, mi = _find_method_signature(lines, i)
                r["mq"].append({"kind": "RabbitMQ Listener",
                                "target": q.group(1) if q else "(未解析)",
                                "ref": f"{cls_name}.{ms}()", "file": frel,
                                "doc": _collect_doc(lines, i)})
            rm = re.search(r'@RocketMQMessageListener\s*\((.*)",?\s*$', line)
            if rm:
                body = rm.group(1)
                t = re.search(r'topic\s*=\s*"([^"]+)"', body)
                sel = re.search(r'selectorExpression\s*=\s*"([^"]+)"', body)
                ms, mi = _find_method_signature(lines, i)
                r["mq"].append({"kind": "RocketMQ Listener",
                                "target": f"{t.group(1) if t else '?'} / tag={sel.group(1) if sel else '*'}",
                                "ref": f"{cls_name}.{ms}()", "file": frel,
                                "doc": _collect_doc(lines, i)})
            prod = re.search(r'(KafkaTemplate|RabbitTemplate|RocketMQTemplate)<[^>]*>\s+(\w+)', line)
            if prod:
                r["mq"].append({"kind": f"{prod.group(1)} 生产者注入",
                                "target": "(见代码调用点)", "ref": prod.group(1),
                                "file": frel, "doc": ""})

        # ---------- Feign / Dubbo：下游依赖 ----------
        for m in re.finditer(r'@FeignClient\s*\(([^)]*)\)', cls_text, re.S):
            body = m.group(1)
            name_ = re.search(r'(?:name|value|contextId)\s*=\s*"([^"]+)"', body)
            url = re.search(r'url\s*=\s*"([^"$][^"]*)"', body)
            path = re.search(r'path\s*=\s*"([^"]+)"', body)
            r["feign"].append({
                "service": name_.group(1) if name_ else "(未解析)",
                "url": f'{url.group(1) if url else ""}{path.group(1) if path else ""}',
                "file": frel,
                "interface": cls_name,
                "methods": re.findall(r'\s*@(Get|Post|Put|Delete|Patch|Request)Mapping', cls_text),
            })
        if re.search(r'@DubboService|@Service\s*\(\s*version|@DubboReference', cls_text):
            sv = re.search(r'@DubboService\s*\(([^)]*)\)', cls_text, re.S)
            r["dubbo"].append({
                "role": "Provider" if "@DubboService" in cls_text else "Consumer",
                "detail": clean_comment(sv.group(1)) if sv else "",
                "class": cls_name, "file": frel,
            })

        # ---------- 配置类 & 安全 ----------
        if re.search(r'@Configuration\b|@ConfigurationProperties\s*\(', cls_text):
            cpm = re.search(r'@ConfigurationProperties\s*\(\s*prefix\s*=\s*"([^"]+)"', cls_text)
            r["configs"].append({"class": cls_name, "prefix": cpm.group(1) if cpm else "",
                                 "file": frel,
                                 "doc": _collect_doc_lines(lines, 0)})
        if re.search(r'WebSecurityConfigurerAdapter|SecurityFilterChain|@EnableWebSecurity|ShiroFilterFactoryBean|@RequiresPermissions', cls_text):
            r["rest_security"].append({
                "class": cls_name, "file": frel,
                "kind": "Spring Security" if "Security" in cls_text else "Shiro",
                "detail": _collect_doc_lines(lines, 0),
            })

        # ---------- main 入口 / 启动类 ----------
        if re.search(r'SpringApplication\.run\s*\(|public\s+static\s+void\s+main\s*\(', cls_text):
            app = re.search(r'@SpringBootApplication', cls_text)
            r["main_classes"].append({
                "class": cls_name, "file": frel,
                "is_boot_app": bool(app),
                "doc": _collect_doc_lines(lines, 0),
            })

        # ---------- 全局异常处理 ----------
        if re.search(r'@ControllerAdvice|@RestControllerAdvice', cls_text):
            handlers = re.findall(r'@ExceptionHandler\s*\(\s*(?:value\s*=)?\s*([\w\.]+)', cls_text)
            r["exception_handlers"].append({
                "class": cls_name, "file": frel, "handles": list(dict.fromkeys(handlers))[:12]})

    return r


def _class_declaration_idx(lines, start: int, max_scan=12):
    """从注解位置向下跳过后继注解，返回类/接口声明行号；找不到返回 None。

    必须跳过后继注解，例如：
        @RestController
        @RequestMapping("/api/order")   <- 我们要判断的是这一行
        @Api(tags = "订单管理")          <- 中间夹了别的注解
        public class XxxController {     <- 真正的声明
    """
    j = start + 1
    limit = min(start + max_scan, len(lines))
    while j < limit:
        s = lines[j].strip()
        if not s:
            j += 1
            continue
        if s.startswith("@"):
            j += 1
            continue
        if re.search(r"\b(class|interface|record|enum)\s", s):
            return j
        return None
    return None


def _is_class_level(lines, i):
    """判断位置 i 处的注解是类级还是方法级"""
    return _class_declaration_idx(lines, i) is not None


def _next_meaningful(lines, i):
    for j in range(i + 1, min(i + 4, len(lines))):
        if lines[j].strip():
            return j
    return None


def _peek(lines, i):
    return lines[i + 1] if i + 1 < len(lines) else ""


def _collect_doc_lines(lines, idx) -> str:
    """采集类上方注释"""
    parts = []
    j = idx - 1
    steps = 0
    while j >= 0 and steps < 16:
        s = lines[j].strip()
        if not s:
            if parts:
                break
            j -= 1
            steps += 1
            continue
        if s.startswith("/*") or s.startswith("*") or s.startswith("//"):
            if s.startswith("/*"):
                parts.append(clean_comment(s))
                break
            parts.append(clean_comment(s))
            j -= 1
            steps += 1
            continue
        break
    return clean_comment(" ".join(reversed(parts)))


# ---------------------------------------------------------------- 采集器：Python 源码

def scan_python_sources(root: Path, files: list) -> dict:
    r = {"endpoints": [], "jobs": [], "models": [], "celery": [], "main_modules": []}
    py_files = [p for p in files if p.suffix.lower() == ".py"]
    for p in py_files:
        txt = read_text(p)
        if not txt:
            continue
        lines = txt.splitlines()
        frel = rel(p, root)

        if re.search(r"if\s+__name__\s*==\s*['\"]__main__['\"]", txt):
            r["main_modules"].append({"file": frel, "doc": _collect_doc_lines(lines, 0)})

        # Flask / FastAPI / Django REST 路由
        for i, line in enumerate(lines):
            m = re.match(r"\s*@(\w+(?:\.\w+)*)\.(get|post|put|delete|patch|route|api_route)\s*\((.*)\)", line)
            if m:
                receiver, verb, body = m.group(1), m.group(2), m.group(3)
                strs = re.findall(r'["\']([^"\']+)["\']', body)
                path = next((s for s in strs if s.startswith("/")), "")
                if verb == "route" or verb == "api_route":
                    mm = re.search(r'methods\s*=\s*\[([^\]]+)\]', body)
                    verbs = re.findall(r'["\'](\w+)["\']', mm.group(1)) if mm else ["GET"]
                else:
                    verbs = [verb.upper()]
                fn = _find_py_func(lines, i)
                r["endpoints"].append({
                    "method": "/".join(verbs), "path": path,
                    "handler": f"{receiver}.{fn}()", "file": frel,
                    "doc": _py_func_doc(lines, i),
                })
            # Django url patterns
            du = re.match(r"\s*(?:path|re_path|url)\s*\(", line)
            if du:
                body = line
                j = i
                while body.count("(") > body.count(")") and j + 1 < len(lines):
                    j += 1
                    body += lines[j]
                path = re.search(r'["\']([^"\']+)["\']', body)
                r["endpoints"].append({
                    "method": "(Django URL)", "path": path.group(1) if path else "(正则)",
                    "handler": body[:80], "file": frel, "doc": "",
                })

        # Celery 任务
        for i, line in enumerate(lines):
            if re.search(r"@(shared_task|app\.task|celery\.task| periodic_task)", line):
                fn = _find_py_func(lines, i)
                r["jobs"].append({"type": "Celery Task", "expr": "(见 beat_schedule / crontab)",
                                  "task": f"{fn}()", "file": frel,
                                  "doc": _py_func_doc(lines, i)})
        # APScheduler
        for i, line in enumerate(lines):
            sc = re.search(r'@scheduler?\.?scheduled_job\s*\((.*)\)', line) or re.search(r'add_job\s*\((.*)', line)
            if sc:
                body = sc.group(1)
                trig = re.search(r'trigger\s*=\s*["\']?([\w]+)', body)
                fn = _find_py_func(lines, i)
                r["jobs"].append({"type": "APScheduler", "expr": trig.group(1) if trig else "(未解析)",
                                  "task": fn, "file": frel, "doc": _py_func_doc(lines, i)})

        # SQLAlchemy / Django Model
        if re.search(r"class\s+\w+\((?:.*?)Model\)|__tablename__", txt):
            tn = re.search(r'__tablename__\s*=\s*["\'](\w+)["\']', txt)
            cls = re.search(r"class\s+(\w+)\(", txt)
            fields = re.findall(r'^\s{4}(\w+)\s*=\s*(?:Column|mapped_column)', txt, re.M)
            r["models"].append({"class": cls.group(1) if cls else Path(p).stem,
                                "table": tn.group(1) if tn else "(未显式指定)",
                                "fields": list(dict.fromkeys(fields))[:30],
                                "file": frel, "doc": _collect_doc_lines(lines, 0)})

    # celery beat 配置
    for p in files:
        if p.suffix.lower() == ".py" and "celery" in p.name.lower():
            txt = read_text(p)
            for m in re.finditer(r'(\w+)\s*:\s*\{[^}]*?[\'"]schedule[\'"]\s*:\s*([^,\n]+)', txt, re.S):
                r["celery"].append((m.group(1), m.group(2).strip(), rel(p, root)))
    return r


def _find_py_func(lines, i):
    for j in range(i + 1, min(i + 4, len(lines))):
        m = re.match(r"\s*(?:async\s+)?def\s+(\w+)", lines[j])
        if m:
            return m.group(1)
    return "(未解析)"


def _py_func_doc(lines, i):
    """取函数下方 docstring"""
    for j in range(i + 1, min(i + 6, len(lines))):
        m = re.match(r'\s*(?:async\s+)?def\s+\w+', lines[j])
        if m:
            for k in range(j + 1, min(j + 6, len(lines))):
                d = re.match(r'\s*(?:r?"""|\'\'\'|#\s*)(.*)', lines[k])
                if d:
                    # 去掉 docstring 尾部残留的引号
                    return clean_comment(re.sub(r'("""|\'\'\')$', '', d.group(1).strip()))
            break
    return ""


# ---------------------------------------------------------------- 采集器：Node 源码

def scan_node_sources(root: Path, files: list) -> dict:
    r = {"endpoints": [], "jobs": [], "main_modules": [], "mounts": []}
    exts = (".js", ".ts", ".jsx", ".tsx")
    node_source = []

    # 第一遍：收集路由挂载点 app.use('/prefix', require('./routes/xxx'))
    for p in files:
        if p.suffix.lower() not in exts:
            continue
        txt = read_text(p)
        if not txt:
            continue
        lines = txt.splitlines()
        node_source.append((p, lines, txt))
        for line in lines:
            mu = re.search(
                r"(?:app|server|router|api)\.use\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*"
                r"([^\s,)]+(?:\s*\(\s*['\"][^'\"]+['\"]\s*\))?)", line)
            if mu:
                handler_arg = mu.group(2)
                # require('./routes/order') -> order
                rq = re.search(r"['\"]([^'\"]+)['\"]", handler_arg)
                target = rq.group(1).rsplit("/", 1)[-1] if rq else handler_arg
                r["mounts"].append({"prefix": mu.group(1), "target": target,
                                    "file": rel(p, root)})

    mount_map = {}
    for mo in r["mounts"]:
        key = mo["target"].rsplit(".", 1)[0]
        mount_map.setdefault(key, []).append(mo["prefix"])

    for p, lines, txt in node_source:
        frel = rel(p, root)
        stem = Path(p).stem

        if re.search(r"app\.listen\s*\(|createServer\s*\(", txt):
            r["main_modules"].append({"file": frel, "doc": _collect_doc_lines(lines, 0)})

        # Nest 控制器
        ctrl = re.search(r'@Controller\s*\(\s*["\']([^"\']*)', txt)
        base = ctrl.group(1) if ctrl else ""
        if ctrl:
            for i, line in enumerate(lines):
                m = re.match(r"\s*@(Get|Post|Put|Delete|Patch|Head|Options)\s*\(\s*[\"']?([^\"')]*)", line)
                if m:
                    fn = _find_py_func(lines, i)
                    sub = m.group(2)
                    full = (base.rstrip("/") + "/" + sub.lstrip("/")) if sub else base
                    r["endpoints"].append({
                        "method": m.group(1).upper(), "path": full.replace("//", "/") or "/",
                        "handler": f"{fn}()", "file": frel, "doc": _py_func_doc(lines, i)})

        # Express / Koa
        # Express / Koa —— 排除 use/all，避免与下方挂载识别重复
        for i, line in enumerate(lines):
            m = re.search(r'(?:app|router|route)\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']', line)
            if m:
                path = m.group(2)
                # 若本文件是被挂载的子路由模块，拼上挂载前缀
                prefixes = mount_map.get(stem, [])
                full = _join_path(prefixes[0], path) if prefixes else path
                r["endpoints"].append({
                    "method": m.group(1).upper(), "path": full,
                    "handler": "(内联回调/中间件)", "file": frel,
                    "doc": _collect_doc_lines(lines, max(0, i - 3))})

        # 定时任务
        for i, line in enumerate(lines):
            nc = re.search(r'cron\.schedule\s*\(\s*["\']([^"\']+)["\']', line)
            if nc:
                r["jobs"].append({"type": "node-cron", "expr": nc.group(1),
                                  "task": "(见回调)", "file": frel, "doc": ""})
            ns = re.search(r'@Cron\s*\(\s*["\']([^"\']+)["\']', line)
            if ns:
                fn = _find_py_func(lines, i)
                r["jobs"].append({"type": "Nest @Cron", "expr": ns.group(1),
                                  "task": f"{fn}()", "file": frel, "doc": _py_func_doc(lines, i)})
            bs = re.search(r'\.repeatEvery\s*\(\s*["\']([^"\']+)["\']', line)
            if bs:
                r["jobs"].append({"type": "agenda repeatEvery", "expr": bs.group(1),
                                  "task": "", "file": frel, "doc": ""})
    return r


# ---------------------------------------------------------------- 配置扁平化

def flatten_config_items(txt: str, is_yaml: bool) -> list:
    """把配置文本展平为 [(dotted_key, value)]。

    Spring Boot 的 application.yml 是缩进嵌套结构，
    直接按 "spring.profiles.active" 这种扁平 key 匹配必然漏采，
    因此需先把 YAML 层级展平。同时兼容 .properties 的 key=value 形式。
    """
    flat = []
    stack = []  # [(indent, key)]

    for raw in txt.splitlines():
        s = raw.strip()
        if not s or s.startswith("#") or s.startswith("//"):
            continue
        if s.startswith("-"):
            continue  # 列表项不参与展平
        if is_yaml:
            if ":" not in s and "=" in s:      # yml 中偶见的 key=value
                k, _, v = s.partition("=")
                flat.append((k.strip().strip('"\''), v.strip()))
                continue
            if ":" not in s:
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            # 剔除注释部分（如 key: value # 说明）
            s_nc = re.split(r"\s+#", s)[0]
            k, _, v = s_nc.partition(":")
            k = k.strip().strip('"\'')
            v = v.strip()
            if not k:
                continue
            while stack and stack[-1][0] >= indent:
                stack.pop()
            stack.append((indent, k))
            full = ".".join(kk for _, kk in stack)
            if v:
                flat.append((full, v))
        else:
            if "=" in s:
                k, _, v = s.partition("=")
                flat.append((k.strip(), v.strip()))
            elif ":" in s:
                k, _, v = s.partition(":")
                flat.append((k.strip(), v.strip()))
    return flat


# SQL 语境中易被误识别为表名的高频词（静态扫描的去噪黑名单）
SQL_NON_TABLE = {
    "id", "values", "set", "where", "select", "on", "null", "true", "false",
    "and", "or", "not", "case", "when", "then", "else", "end", "as", "count",
    "sum", "avg", "max", "min", "now", "dual", "value", "result", "order",
    "limit", "offset", "group", "having", "union", "all", "distinct", "join",
    "left", "right", "inner", "outer", "if", "exists", "insert", "update",
    "delete", "from", "into", "table",
}


# ---------------------------------------------------------------- 采集器：配置与部署

def scan_configs(root: Path, files: list) -> dict:
    r = {"config_files": [], "profiles": set(), "endpoints_from_cfg": [],
         "ports": [], "db_urls": []}
    cfg_names = ("application.yml", "application.yaml", "application.properties",
                 "bootstrap.yml", "bootstrap.yaml", "application-.yml")
    for p in files:
        name = p.name.lower()
        is_cfg = (name.startswith("application") or name.startswith("bootstrap")) and \
                 p.suffix.lower() in (".yml", ".yaml", ".properties")
        is_cfg = is_cfg or name.startswith(".env") or name in ("docker-compose.yml", "docker-compose.yaml")
        is_cfg = is_cfg or (p.suffix.lower() in (".yml", ".yaml") and
                            any(seg in rel(p, root).lower() for seg in ("config", "conf", "resources")))
        is_cfg = is_cfg or (p.suffix.lower() == ".conf" and "nginx" not in rel(p, root).lower())
        if not is_cfg:
            continue
        txt = read_text(p)
        if not txt:
            continue
        frel = rel(p, root)
        is_yaml = p.suffix.lower() in (".yml", ".yaml")
        flat = flatten_config_items(txt, is_yaml)
        if not flat:
            # 兼容非典型格式：退回逐行切分
            flat = [(l.split(":")[0].split("=")[0].strip(),
                     (l.split(":", 1)[1] if ":" in l else l.split("=", 1)[-1]).strip())
                    for l in txt.splitlines()
                    if l.strip() and not l.strip().startswith("#")
                    and (":" in l or "=" in l)]

        keys = []
        hidden = []
        for key, val in flat:
            if not key or len(key) > 90:
                continue
            if SENSITIVE_KEY_PAT.search(key):
                hidden.append(key)
                val = "***（敏感项，已脱敏）***"
            keys.append((key, val[:120]))
            compact = key.replace(" ", "")
            # profile
            if re.search(r"spring\.?profiles\.?active$", compact, re.I):
                for v in re.split(r"[,\s]+", val):
                    if v.strip():
                        r["profiles"].add(v.strip())
            # 端口
            if re.match(r"^server\.port$|^PORT$", compact, re.I):
                mv = re.match(r"(\d+)", val)
                if mv:
                    r["ports"].append((mv.group(1), frel))
            # 数据源地址（脱敏）
            if re.search(r"datasource.*(url|jdbc-url)$|DATABASE_URL$|^spring\.datasource\.url$",
                         compact, re.I) and "://" in val:
                safe = re.sub(r"//([^:/@]+):([^@]+)@", "//<user>:<pwd>@", val)
                safe = re.sub(r"(?i)[?&](password|pwd|user)=[^&]*", r"\1=***", safe)
                r["db_urls"].append((safe, frel))
            # 对外依赖地址
            if re.match(r"^(?:https?|ws|grpc|dubbo|thrift)://", val):
                r["endpoints_from_cfg"].append((key, val[:160], frel))
        r["config_files"].append({"file": frel, "keys": keys[:400],
                                  "sensitive_keys": list(dict.fromkeys(hidden))[:30]})
    r["profiles"] = sorted(r["profiles"])
    return r


def _extract_ci_stages(txt: str) -> list:
    """提取 CI 流水线的阶段名，兼容三种主流语法"""
    stages = []
    # Jenkins Groovy：stage('Build') {
    stages += re.findall(r"stage\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", txt)
    # GitLab CI / Actions：stage: deploy / name: Run tests
    stages += re.findall(r"^\s*(?:stage|name)\s*:\s*['\"]?([^\n'\"#]{2,50}?)['\"]?\s*$",
                         txt, re.M)
    # GitHub Actions：jobs 下的顶层 job key（两空格缩进）
    stages += re.findall(r"^  ([a-zA-Z][\w\-]{1,30}):\s*$", txt, re.M)
    # GitLab CI stages 列表项
    stages += re.findall(r"^\s*-\s+([a-zA-Z][\w\-]{1,30})\s*$", txt, re.M)
    return [s.strip() for s in stages if s.strip()]


def scan_infra(root: Path, files: list) -> dict:
    r = {"docker": [], "compose": [], "k8s": [], "ci": [], "nginx": [],
         "scripts": [], "sql_files": []}
    for p in files:
        name = p.name.lower()
        frel = rel(p, root)
        if name.startswith("dockerfile"):
            txt = read_text(p)
            stages = re.findall(r"FROM\s+([^\s]+)", txt)
            exposed = re.findall(r"EXPOSE\s+(\d+)", txt)
            entry = re.findall(r"(ENTRYPOINT|CMD)\s+\[?([^\]\n]+)", txt)
            r["docker"].append({"file": frel, "images": stages, "expose": exposed,
                                "entry": [ (a, b[:120]) for a, b in entry ]})
        elif name in ("docker-compose.yml", "docker-compose.yaml"):
            txt = read_text(p)
            svcs = re.findall(r"^\s{2}([a-zA-Z0-9_\-]+):\s*$", txt, re.M)
            images = re.findall(r"image:\s*([^\s]+)", txt)
            ports = re.findall(r"['\"]?(\d{2,5}):(\d{2,5})['\"]?", txt)
            r["compose"].append({"file": frel, "services": svcs, "images": images,
                                 "ports": [f"{a}->{b}" for a, b in ports]})
        elif p.suffix.lower() in (".yml", ".yaml") and ("kubernetes" in frel.lower()
                                                        or "k8s" in frel.lower()
                                                        or re.search(r"kind:\s*(Deployment|Service|Ingress|ConfigMap|StatefulSet|CronJob)", read_text(p) or "")):
            txt = read_text(p)
            kinds = re.findall(r"kind:\s*(\w+)", txt)
            names = re.findall(r"name:\s*([\w\-]+)", txt)
            r["k8s"].append({"file": frel, "kinds": list(dict.fromkeys(kinds)),
                             "resources": list(dict.fromkeys(names))[:15]})
        elif name in ("jenkinsfile", ".gitlab-ci.yml", "azure-pipelines.yml") or \
                (".github" in frel and p.suffix.lower() in (".yml", ".yaml")) or \
                name in ("bitbucket-pipelines.yml", ".drone.yml"):
            txt = read_text(p) or ""
            r["ci"].append({"file": frel,
                            "steps": list(dict.fromkeys(_extract_ci_stages(txt)))[:25]})
        elif p.name.lower().endswith(".conf") and "nginx" in frel.lower():
            txt = read_text(p)
            ups = re.findall(r"upstream\s+(\w+)", txt)
            loc = re.findall(r"location\s+([^\s{]+)", txt)
            r["nginx"].append({"file": frel, "upstreams": ups, "locations": loc[:20]})
        elif p.suffix.lower() in (".sh", ".bat", ".ps1") and "node_modules" not in frel:
            txt = read_text(p)
            head = [clean_comment(l) for l in txt.splitlines()[:6] if l.strip()]
            r["scripts"].append({"file": frel, "desc": " / ".join(head)[:150]})

    for p in files:
        if p.suffix.lower() == ".sql":
            txt = read_text(p)
            tables = re.findall(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"]?([\w\.]+)[`\"]?", txt, re.I)
            views = re.findall(r"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+[`\"]?([\w\.]+)", txt, re.I)
            procs = re.findall(r"CREATE\s+PROCEDURE\s+[`\"]?([\w\.]+)", txt, re.I)
            trigs = re.findall(r"CREATE\s+TRIGGER\s+[`\"]?([\w\.]+)", txt, re.I)
            if tables or views or procs or trigs:
                r["sql_files"].append({
                    "file": rel(p, root),
                    "tables": list(dict.fromkeys(tables))[:60],
                    "views": list(dict.fromkeys(views))[:20],
                    "procedures": list(dict.fromkeys(procs))[:20],
                    "triggers": list(dict.fromkeys(trigs))[:10],
                })
    return r


def scan_docs(root: Path, files: list) -> list:
    """列出仓库内的文档资源 —— 交接文档候选"""
    docs = []
    for p in files:
        if p.suffix.lower() in (".md", ".txt", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".drawio", ".ppt", ".pptx"):
            if p.stat().st_size == 0:
                continue
            if p.suffix.lower() in (".md", ".markdown", ".txt"):
                txt = read_text(p)
                h1 = re.search(r"^#\s+(.+)$", txt, re.M)
                docs.append({"file": rel(p, root),
                             "title": clean_comment(h1.group(1)) if h1 else
                                      (clean_comment(txt.splitlines()[0]) if txt else ""),
                             "lines": txt.count("\n") + 1})
            else:
                docs.append({"file": rel(p, root), "title": "(二进制文档)", "lines": 0})
    return docs


# ---------------------------------------------------------------- 报告渲染

def write_reports(out: Path, data: dict, root: Path):
    out.mkdir(parents=True, exist_ok=True)

    def w(name, content):
        (out / name).write_text(content, encoding="utf-8")

    ov = data["overview"]
    git = data["git"]
    mv = data["maven"]
    py = data["python"]
    nd = data["node"]
    jv = data["java"]
    cf = data["config"]
    inf = data["infra"]
    pys = data["py_src"]
    nds = data["node_src"]

    # ---------- 00 系统画像摘要 ----------
    all_deps = []
    all_deps += [d["ga"] for d in mv["dependencies"]]
    for pk in nd["packages"]:
        all_deps += pk["deps"]
    all_deps += [x[0] for x in py["requirements"]]
    mws = infer_middleware(all_deps)

    endpoints = jv["endpoints"] + pys["endpoints"] + nds["endpoints"]
    jobs = jv["jobs"] + pys["jobs"] + nds["jobs"]
    entities = jv["entities"] + pys["models"]
    tables = set()
    for mf in jv["mapper_files"]:
        tables |= set(mf["tables"])
    for e in entities:
        if e["table"] and not e["table"].startswith("("):
            tables.add(e["table"])
    for sf in inf["sql_files"]:
        tables |= set(sf["tables"])

    con = []
    con.append("# 00 · 系统画像速览\n")
    con.append(f"> 由 scan_repo.py v{VERSION} 静态生成 · 生成时间 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    con.append(f"> 仓库路径：`{root}`\n")
    con.append("**重要说明**：本目录所有内容均为**静态启发式扫描**结果，仅代表代码中客观存在的事实线索，")
    con.append("可能存在遗漏或误判。编写正式文档时必须核实，不得直接照抄。\n")

    con.append("## 一、规模概览\n")
    con.append(md_table(["指标", "数值"], [
        ["文件总数", ov["total_files"]],
        ["仓库体积(MB)", ov["total_size_mb"]],
        ["代码行数(主要语言)", ", ".join(f"{k}≈{v:,}" for k, v in list(ov["line_count_code"].items())[:6]) or "—"],
        ["文件数 TOP 语言", ", ".join(f"{k}:{v}" for k, v in list(ov["file_count_by_lang"].items())[:6]) or "—"],
    ]))

    con.append("\n## 二、技术栈识别\n")
    stack_rows = []
    if mv["root_pom"]:
        stack_rows.append(["构建方式", f"Maven（根 {mv['root_pom']}）"])
        if mv.get("parent"):
            stack_rows.append(["父依赖/POM", mv["parent"]])
    if mv["modules"]:
        stack_rows.append(["Maven 子模块", ", ".join(m for mm in mv["modules"] for m in mm["modules"])])
    if nd["packages"]:
        stack_rows.append(["Node 包", ", ".join(pk["name"] or pk["file"] for pk in nd["packages"])])
    if py["files"]:
        stack_rows.append(["Python 依赖文件", ", ".join(py["files"])])
    for k, v in dict(mv["props"]).items():
        stack_rows.append([f"POM 属性 {k}", v])
    con.append(md_table(["维度", "识别结果"], stack_rows))

    con.append("\n**中间件 / 技术组件（由依赖推断）**：\n")
    con.append(", ".join(f"`{m}`" for m in mws) if mws else "未识别\n")

    con.append("\n## 三、对外提供的接口数量\n")
    con.append(md_table(["类别", "数量"], [
        ["HTTP 接口", len(endpoints)],
        ["其中 Java 接口", len(jv["endpoints"])],
        ["其中 Python 接口", len(pys["endpoints"])],
        ["其中 Node 接口", len(nds["endpoints"])],
        ["定时任务", len(jobs)],
        ["MQ 收发点", len(jv["mq"])],
        ["Feign 下游依赖", len(jv["feign"])],
        ["数据实体/表", len(tables)],
        ["MyBatis Mapper 文件", len(jv["mapper_files"])],
    ]))

    con.append("\n## 四、部署线索\n")
    dep_rows = []
    if inf["docker"]:
        dep_rows.append(["Docker 镜像构建", ", ".join(d["file"] for d in inf["docker"])])
    if inf["compose"]:
        dep_rows.append(["Compose 服务", ", ".join(s for c in inf["compose"] for s in c["services"])])
    if inf["k8s"]:
        dep_rows.append(["K8s 编排", ", ".join(k["file"] for k in inf["k8s"])])
    if inf["ci"]:
        dep_rows.append(["CI/CD", ", ".join(c["file"] for c in inf["ci"])])
    if cf["ports"]:
        dep_rows.append(["监听端口", ", ".join(dict.fromkeys(p[0] for p in cf["ports"]))])
    if cf["profiles"]:
        dep_rows.append(["Spring Profile", ", ".join(cf["profiles"])])
    con.append(md_table(["维度", "内容"], dep_rows))

    con.append("\n## 五、人（Git 协作线索）\n")
    if git.get("available"):
        if git.get("recent_commits"):
            con.append("**最近提交：**\n")
            con.append("```\n" + "\n".join(git["recent_commits"][:8]) + "\n```\n")
        if git.get("active_authors"):
            con.append("**近半年活跃提交人（按提交数排序）** —— 这是文档中\"该找谁问\"的直接依据：\n")
            con.append(md_table(["姓名/账号", "提交次数"], git["active_authors"]))
        if git.get("hot_files"):
            con.append("\n**近半年改动热点文件** —— 反映系统当前活跃/风险区域：\n")
            con.append(md_table(["文件", "改动次数"], git["hot_files"][:12]))
    else:
        con.append("_非 Git 仓库或未安装 Git，跳过协作线索采集_\n")

    con.append("\n## 六、仓库内既有文档\n")
    con.append(md_table(["文档路径", "标题/说明", "行数"],
                        [[d["file"], d["title"], d["lines"]] for d in data["docs"]][:40]))

    con.append("\n## 七、接手风险提示\n")
    risk = []
    if jv["todos"]:
        risk.append(f"仓库内存在 {len(jv['todos'])} 处 TODO/FIXME 标记（见 08 章）")
    if ov["large_files"]:
        risk.append(f"存在 {len(ov['large_files'])} 个超过 200KB 的大文件（可能为上帝类，见 01 章）")
    nocomment = 0
    # 粗略统计无注释的 Controller 方法
    for ep in jv["endpoints"]:
        if not ep["doc"]:
            nocomment += 1
    if jv["endpoints"]:
        rate = nocomment / len(jv["endpoints"])
        if rate > 0.5:
            risk.append(f"约 {rate:.0%} 的 Java 接口缺少注释/Swagger 描述，业务语义需靠人工确认")
    hidden = [h for c in cf["config_files"] for h in c["sensitive_keys"]]
    if hidden:
        risk.append(f"扫描到 {len(set(hidden))} 类敏感配置项（已在报告中脱敏，文档中严禁写入真实密钥）")
    if not inf["docker"] and not inf["compose"] and not inf["k8s"]:
        risk.append("未发现容器化/编排文件，部署方式需向原团队口头确认")
    con.append("\n".join(f"- {r}" for r in risk) if risk else "- 未发现明显风险信号\n")

    con.append("\n## 八、文件索引\n")
    con.append("""| 文件 | 内容 | 编写文档时的主要用途 |
|---|---|---|
| `01_structure.md` | 模块结构、大文件、入口 | 画部署/开发架构图 |
| `02_dependencies.md` | 依赖与组件 | 写技术架构、组件清单 |
| `03_endpoints.md` | HTTP 接口全集 | 写对外接口、集成关系 |
| `04_data.md` | 实体、Mapper、DDL | 写数据模型、核心数据表 |
| `05_jobs_and_mq.md` | 定时任务、消息 | 写运维日程、异步链路 |
| `06_config.md` | 配置项、敏感项 | 写配置说明、环境差异 |
| `07_deploy.md` | Docker/K8s/CI/Nginx | 写部署架构、发布流程 |
| `08_quality.md` | TODO、热点、风险 | 写遗留问题、风险清单 |
""")
    w("00_SUMMARY.md", "\n".join(con))

    # ---------- 01 结构 ----------
    c = ["# 01 · 工程结构\n"]
    c.append("## 模块 / 子工程\n")
    mod_rows = []
    for mm in mv["modules"]:
        mod_rows.append([mm["pom"], ", ".join(mm["modules"])])
    for pk in nd["packages"]:
        mod_rows.append([pk["file"], f'包 {pk["name"]} v{pk["version"]}，scripts: ' + ", ".join(list(pk["scripts"])[:8])])
    for wsf, wsl in nd["workspaces"]:
        mod_rows.append([wsf, "workspace: " + str(wsl)])
    c.append(md_table(["Manifest 位置", "子模块/说明"], mod_rows))

    c.append("\n## 应用入口 / 启动类\n")
    c.append(md_table(["入口类", "文件", "是否 SpringBoot 应用", "说明"],
                      [[m["class"], m["file"], "是" if m["is_boot_app"] else "否", m["doc"]]
                       for m in jv["main_classes"]]))
    c.append("\n**Python 可运行入口：**\n")
    c.append(md_table(["文件", "说明"], [[m["file"], m["doc"]] for m in pys["main_modules"]]))
    c.append("\n**Node 服务入口：**\n")
    c.append(md_table(["文件", "说明"], [[m["file"], m["doc"]] for m in nds["main_modules"]]))

    c.append("\n## 大文件（可能为上帝类，接手难点）\n")
    c.append(md_table(["大小(KB)", "文件"],
                      [[round(s / 1024, 1), f] for s, f in ov["large_files"]]))

    c.append("\n## 仓库内既有文档\n")
    c.append(md_table(["文档路径", "标题", "行数"],
                      [[d["file"], d["title"], d["lines"]] for d in data["docs"]]))
    w("01_structure.md", "\n".join(c))

    # ---------- 02 依赖 ----------
    c = ["# 02 · 依赖与技术组件\n"]
    c.append("## 推断出的中间件 / 能力\n")
    c.append(md_table(["组件/能力", "来源线索"],
                      [[m, "依赖库名命中"] for m in mws]))
    c.append("\n## Maven 依赖\n")
    c.append(md_table(["groupId:artifactId", "版本", "scope", "来自 POM"],
                      [[d["ga"], d["version"], d["scope"], d["from"]]
                       for d in mv["dependencies"]], max_rows=300))
    c.append("\n> 仅列出前 300 条，完整数据见 `scan_data.json`\n")

    if nd["packages"]:
        c.append("\n## Node 依赖\n")
        for pk in nd["packages"]:
            c.append(f"\n### {pk['file']}（{pk['name']} v{pk['version']}）\n")
            c.append("**npm scripts：** " + (", ".join(f"{k} → {v}" for k, v in list(pk["scripts"].items())[:12]) or "无") + "\n")
            c.append("**生产依赖：** " + (", ".join(pk["deps"]) or "无") + "\n")
    if py["requirements"]:
        c.append("\n## Python 依赖\n")
        c.append(md_table(["依赖声明", "文件"], py["requirements"], max_rows=300))
    if py["pyproject"]:
        c.append("\n**pyproject 变量：**\n")
        c.append(md_table(["变量", "值", "文件"], py["pyproject"], max_rows=60))
    w("02_dependencies.md", "\n".join(c))

    # ---------- 03 接口 ----------
    c = ["# 03 · HTTP 接口全集\n"]
    c.append(f"共扫描到 **{len(endpoints)}** 个 HTTP 接口点。\n")
    for title, eps in [("Java / SpringMVC 接口", jv["endpoints"]),
                       ("Python 接口", pys["endpoints"]),
                       ("Node 接口", nds["endpoints"])]:
        if not eps:
            continue
        c.append(f"\n## {title}（{len(eps)} 个）\n")
        c.append(md_table(["方法", "路径", "处理函数", "注释/说明", "源文件"],
                          [[e["method"], e["path"], e["handler"], e["doc"], e["file"]]
                           for e in eps], max_rows=500))
        if len(eps) > 500:
            c.append(f"\n> 仅列出前 500 条，共 {len(eps)} 条，完整数据见 `scan_data.json`\n")

    c.append("\n## Feign 下游依赖（本系统主动调用的其他服务）\n")
    c.append(md_table(["目标服务名", "地址/路径", "接口", "源文件"],
                      [[f["service"], f["url"], f["interface"], f["file"]]
                       for f in jv["feign"]], max_rows=200))
    if jv["dubbo"]:
        c.append("\n## Dubbo 服务\n")
        c.append(md_table(["角色", "服务类", "细节", "文件"],
                          [[d["role"], d["class"], d["detail"], d["file"]] for d in jv["dubbo"]]))
    w("03_endpoints.md", "\n".join(c))

    # ---------- 04 数据 ----------
    c = ["# 04 · 数据模型\n"]
    c.append("## 数据实体（ORM 映射）\n")
    c.append(md_table(["类名", "表名", "主要字段", "说明", "源文件"],
                      [[e["class"], e["table"], ", ".join(e["fields"][:25]), e["doc"], e["file"]]
                       for e in entities], max_rows=200))
    c.append("\n## MyBatis Mapper\n")
    c.append(md_table(["Mapper XML", "namespace", "SQL 语句分布", "涉及表"],
                      [[m["file"], m["namespace"],
                        ", ".join(f"{k}:{v}" for k, v in m["statements"].items()),
                        ", ".join(m["tables"][:12])] for m in jv["mapper_files"]], max_rows=200))
    if inf["sql_files"]:
        c.append("\n## SQL / DDL 脚本\n")
        for sf in inf["sql_files"]:
            c.append(f"\n### `{sf['file']}`\n")
            if sf["tables"]:
                c.append(f"- **表**（{len(sf['tables'])}）：" + ", ".join(sf["tables"][:40]) + "\n")
            if sf["views"]:
                c.append(f"- **视图**：" + ", ".join(sf["views"]) + "\n")
            if sf["procedures"]:
                c.append(f"- **存储过程**：" + ", ".join(sf["procedures"]) + "\n")
            if sf["triggers"]:
                c.append(f"- **触发器**：" + ", ".join(sf["triggers"]) + "\n")
    c.append("\n## 数据源连接（已脱敏）\n")
    c.append(md_table(["连接串（脱敏后）", "配置文件"], cf["db_urls"]))
    w("04_data.md", "\n".join(c))

    # ---------- 05 任务与消息 ----------
    c = ["# 05 · 定时任务与异步消息\n"]
    c.append("## 定时任务\n")
    c.append(md_table(["类型", "调度表达式/配置", "任务方法", "说明", "源文件"],
                      [[j["type"], j["expr"], j["task"], j["doc"], j["file"]]
                       for j in jobs], max_rows=300))
    if pys["celery"]:
        c.append("\n**Celery beat 调度表：**\n")
        c.append(md_table(["任务", "调度", "文件"], pys["celery"]))
    c.append("\n## 消息中间件收发点\n")
    c.append(md_table(["类型", "Topic/Queue", "处理位置", "说明", "源文件"],
                      [[m["kind"], m["target"], m["ref"], m["doc"], m["file"]]
                       for m in jv["mq"]], max_rows=200))
    w("05_jobs_and_mq.md", "\n".join(c))

    # ---------- 06 配置 ----------
    c = ["# 06 · 配置项\n"]
    c.append("> 敏感键值已统一替换为 `***（敏感项，已脱敏）***`，"
             "正式文档中禁止出现真实口令。\n")
    c.append("\n## Spring Profile\n")
    c.append(", ".join(cf["profiles"]) or "_未识别_\n")
    c.append("\n## 端口\n")
    c.append(md_table(["端口", "来源文件"], cf["ports"]))
    c.append("\n## 对外依赖地址（配置中的 URL）\n")
    c.append(md_table(["配置项", "URL", "来源文件"], cf["endpoints_from_cfg"], max_rows=80))
    c.append("\n## 各配置文件键值\n")
    for cfg in cf["config_files"]:
        c.append(f"\n### `{cfg['file']}`\n")
        if cfg["sensitive_keys"]:
            c.append(f"**敏感项({len(cfg['sensitive_keys'])})**："
                     + ", ".join(cfg["sensitive_keys"]) + "\n")
        c.append(md_table(["配置项", "值"], cfg["keys"], max_rows=250))
    w("06_config.md", "\n".join(c))

    # ---------- 07 部署 ----------
    c = ["# 07 · 部署与基础设施\n"]
    if inf["docker"]:
        c.append("## Docker 构建\n")
        c.append(md_table(["Dockerfile", "基础镜像", "暴露端口", "启动命令"],
                          [[d["file"], " → ".join(d["images"]), ", ".join(d["expose"]),
                            " ".join(b for a, b in d["entry"])] for d in inf["docker"]]))
    if inf["compose"]:
        c.append("\n## Compose 编排\n")
        for cp in inf["compose"]:
            c.append(f"\n### `{cp['file']}`\n")
            c.append(f"- **服务**：" + ", ".join(cp["services"]) + "\n")
            c.append(f"- **镜像**：" + ", ".join(cp["images"]) + "\n")
            c.append(f"- **端口映射**：" + ", ".join(cp["ports"]) + "\n")
    if inf["k8s"]:
        c.append("\n## Kubernetes 编排\n")
        c.append(md_table(["yaml", "资源类型", "资源名"],
                          [[k["file"], ", ".join(k["kinds"]), ", ".join(k["resources"][:8])]
                           for k in inf["k8s"]]))
    if inf["ci"]:
        c.append("\n## CI/CD 流水线\n")
        c.append(md_table(["流水线文件", "步骤/阶段"],
                          [[ci["file"], ", ".join(ci["steps"])] for ci in inf["ci"]]))
    if inf["nginx"]:
        c.append("\n## Nginx 配置\n")
        c.append(md_table(["配置文件", "upstream", "location"],
                          [[n["file"], ", ".join(n["upstreams"]), ", ".join(n["locations"][:15])]
                           for n in inf["nginx"]]))
    if inf["scripts"]:
        c.append("\n## 构建/运维脚本\n")
        c.append(md_table(["脚本", "头部说明"],
                          [[s["file"], s["desc"]] for s in inf["scripts"]], max_rows=60))
    w("07_deploy.md", "\n".join(c))

    # ---------- 08 质量 ----------
    c = ["# 08 · 代码质量与遗留问题\n"]
    c.append("## TODO / FIXME 标记\n")
    c.append(md_table(["文件", "行号", "内容"], jv["todos"], max_rows=200))
    c.append("\n## 全局异常处理\n")
    c.append(md_table(["处理器类", "处理的异常", "文件"],
                      [[e["class"], ", ".join(e["handles"]) or "（未解析）", e["file"]]
                       for e in jv["exception_handlers"]]))
    c.append("\n## 配置类 / 安全配置\n")
    c.append(md_table(["类名", "类型", "说明", "文件"],
                      [[s["class"], s["kind"], s["detail"], s["file"]] for s in jv["rest_security"]]))
    c.append("\n**自定义配置类（@Configuration / @ConfigurationProperties）：**\n")
    c.append(md_table(["类名", "前缀", "说明", "文件"],
                      [[cg["class"], cg["prefix"], cg["doc"], cg["file"]]
                       for cg in jv["configs"]], max_rows=100))
    c.append("\n## 最近改动热点文件\n")
    if git.get("hot_files"):
        c.append(md_table(["文件", "近半年改动次数"], git["hot_files"][:20]))
    else:
        c.append("_无 Git 数据_\n")
    w("08_quality.md", "\n".join(c))

    # ---------- JSON 全量数据 ----------
    serializable = {
        "meta": {"tool": "scan_repo.py", "version": VERSION,
                 "generated_at": datetime.now().isoformat(), "root": str(root)},
        "overview": ov,
        "git": git,
        "maven": mv,
        "python_deps": py,
        "node_deps": nd,
        "middleware": mws,
        "java": jv,
        "python_src": pys,
        "node_src": nds,
        "config": {k: (v if not isinstance(v, set) else sorted(v)) for k, v in cf.items()},
        "infra": inf,
        "docs": data["docs"],
    }
    (out / "scan_data.json").write_text(
        json.dumps(serializable, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser(
        description="扫描应用源码，生成 AI 编写《应用交接文档》用的事实快照",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n  python scan_repo.py D:/repos/order-service\n"
               "  python scan_repo.py D:/repos/order-service -o D:/work/scan\n")
    ap.add_argument("repo", help="应用源码根目录")
    ap.add_argument("-o", "--output", default=None,
                    help="输出目录，默认 <repo>/_handover_scan")
    ap.add_argument("--no-git", action="store_true", help="跳过 git 信息采集")
    ap.add_argument("--json-only", action="store_true", help="只输出 JSON，不生成 markdown")
    args = ap.parse_args()

    root = Path(args.repo).expanduser().resolve()
    if not root.exists():
        print(f"[错误] 路径不存在：{root}", file=sys.stderr)
        return 2
    if not root.is_dir():
        print(f"[错误] 不是目录：{root}", file=sys.stderr)
        return 2

    out = Path(args.output).expanduser().resolve() if args.output else root / "_handover_scan"

    print(f"[1/8] 遍历文件：{root}")
    files = list(iter_files(root))
    print(f"      收集到 {len(files)} 个文件")

    print("[2/8] 仓库概览")
    overview = scan_overview(root, files)

    print("[3/8] Git 协作线索")
    git = {} if args.no_git else scan_git(root)

    print("[4/8] 构建与依赖")
    maven = scan_maven(root, files)
    python = scan_python_deps(root, files)
    node = scan_node_deps(root, files)

    print("[5/8] 源码语义扫描（Java / Python / Node）")
    java = scan_java_sources(root, files)
    py_src = scan_python_sources(root, files)
    node_src = scan_node_sources(root, files)

    print("[6/8] 配置项")
    config = scan_configs(root, files)

    print("[7/8] 部署与基础设施")
    infra = scan_infra(root, files)
    docs = scan_docs(root, files)

    print("[8/8] 生成报告")
    data = {
        "overview": overview, "git": git, "maven": maven, "python": python,
        "node": node, "java": java, "py_src": py_src, "node_src": node_src,
        "config": config, "infra": infra, "docs": docs,
    }
    write_reports(out, data, root)

    def cnt(x):
        return len(x) if x else 0
    print("\n" + "=" * 64)
    print("扫描完成")
    print("=" * 64)
    if not args.json_only:
        print(f"报告目录：{out}")
        print("  ├── 00_SUMMARY.md        系统画像速览（先读这个）")
        print("  ├── 01_structure.md      工程结构 / 入口 / 大文件")
        print("  ├── 02_dependencies.md   依赖与技术组件")
        print("  ├── 03_endpoints.md      HTTP 接口全集 + 下游依赖")
        print("  ├── 04_data.md           数据模型 / Mapper / DDL")
        print("  ├── 05_jobs_and_mq.md    定时任务 / 消息队列")
        print("  ├── 06_config.md         配置项（敏感项已脱敏）")
        print("  ├── 07_deploy.md         Docker / K8s / CI / Nginx")
        print("  ├── 08_quality.md        TODO / 异常处理 / 热点改动")
        print("  └── scan_data.json       全量结构化数据（AI 可精读）")
    print(f"\n关键统计：")
    print(f"  HTTP 接口      {len(java['endpoints']) + len(py_src['endpoints']) + len(node_src['endpoints'])} 个")
    print(f"  定时任务       {len(java['jobs']) + len(py_src['jobs']) + len(node_src['jobs'])} 个")
    print(f"  MQ 收发点      {len(java['mq'])} 个")
    print(f"  Feign 下游     {len(java['feign'])} 个")
    print(f"  数据实体       {len(java['entities']) + len(py_src['models'])} 个")
    print(f"  DDL 建表       {sum(len(s['tables']) for s in infra['sql_files'])} 张")
    print(f"  配置文件       {len(config['config_files'])} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main())
