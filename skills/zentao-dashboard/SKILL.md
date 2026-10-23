---
name: zentao-dashboard
description: 禅道数据看板生成器。拉取所有"进行中"项目 → 迭代 → 任务，生成多维 xlsx 看板。Use when user says "禅道看板"、"生成禅道数据"、"拉取禅道任务"、"zentao dashboard"或提及需汇总禅道多项目任务数据。
---

# 禅道数据看板生成器

## 能力

遍历禅道所有"进行中"项目，对每个项目拉取状态不为"已关闭"的迭代，对每个迭代拉取全部任务，输出一份包含 **项目总览** 和 **任务明细** 两个 sheet 的 xlsx 看板。

## 前置条件

1. 需要有效的禅道 Cookie（从浏览器 DevTools > Network 复制请求头中的 Cookie 字符串）
2. 需要 Python + openpyxl：
   ```
   pip install openpyxl
   ```

## 使用步骤

### 1. 获取信息

打开禅道并登录，从浏览器 DevTools > Network 复制任意请求的 `Cookie` 请求头，并确认禅道服务器地址（host:port）。

### 2. 运行脚本

```powershell
python <skill_dir>\scripts\zentao_dashboard.py <host> <port> "<cookie>" [输出路径.xlsx]
```

示例：

```powershell
python "<skill_dir>\scripts\zentao_dashboard.py" 127.0.0.1 10086 "lang=zh-cn; za=admin; zentaosid=xxx..." "C:\Users\<用户名>\Desktop\禅道数据看板.xlsx"
```

不指定输出路径则自动生成到当前项目的 `outputs/` 目录下，文件名格式为 `禅道数据看板_yyyyMMdd_HHmm.xlsx`。

### 3. 输出文件结构

**项目总览 sheet：**
| 项目编号 | 项目名称 | 迭代数 | 所属迭代 | 迭代ID | 迭代状态 | 计划开始 | 计划完成 | 是否延期 | 任务数 | 总预计(h) | 总消耗(h) | 总剩余(h) |

**任务明细 sheet：**
| 任务ID | 所属迭代 | 任务名称 | 优先级 | 当前指派 | 状态 | 预计(h) | 消耗(h) | 剩余(h) | 进度(%) | 指派给 | 来源Bug |

> 工时列均为纯数字（单位 h），便于 Excel 圈选求和。进度列为 0-100 整数。

状态色标：黄色=未开始 / 绿色=进行中 / 蓝色=已完成 / 红色=已取消

### 4. 完整工作流（AI 自动执行）

当用户说"生成禅道数据看板"时，AI 应：

1. **获取信息**：询问用户禅道服务器地址（host:port）和 Cookie（从浏览器 DevTools 复制）
2. **执行脚本**：用用户提供的信息运行 `zentao_dashboard.py <host> <port> <cookie>`
3. **打开看板**：用 `idea_open_file_in_editor` 打开生成的 xlsx 文件
4. **反馈结果**：告知用户项目数、迭代数、任务数

## URL 参考

| 用途 | URL |
|------|------|
| 进行中项目列表 | `http://{host}:{port}/zentao/project-browse-0-doing.html` |
| 某项目的迭代（非已关闭） | `http://{host}:{port}/zentao/project-execution-all-{projectId}.html` |
| 某迭代的全部任务 | `http://{host}:{port}/zentao/execution-task-{executionId}-all-0--27-1000-1.html` |
| 某项目的团队成员 | `http://{host}:{port}/zentao/project-team-{projectId}.html` |

## 局限性

- 需要手动提供并定期更新 Cookie（有时效性）
