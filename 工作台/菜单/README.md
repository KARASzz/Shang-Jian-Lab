# 工作台 · 菜单（C：数字工作台）

数字菜单、配置、任务浏览、定稿 / 归档入口。本包**只做调度外壳**：

- 调起 A（接入：`工作台.接入`）的模型与搜索；
- 调起 B（流水线：`工作台.流水线`）的策划 → 三稿 → 审稿 → 返修；
- 自己**不调用模型**，**不发起搜索**。

## 入口

| 平台 | 命令 |
| --- | --- |
| Windows | 双击 `启动工作台.bat` 或在仓库根执行 `启动工作台.bat` |
| macOS / Linux | 双击 `启动工作台.command`（Finder 会要求「打开方式 → 终端」），或在仓库根执行 `./启动工作台.command` |
| 通用 | `python -m 工作台.菜单` 或 `python -m 工作台.菜单.app` |

启动脚本的约束：

- `启动工作台.bat`：先 `chcp 65001 > nul`，再 `set PYTHONIOENCODING=utf-8`，再 `python -m 工作台.菜单.app %*`。不写死绝对路径。
- `启动工作台.command`：`#!/usr/bin/env bash`，`LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 exec python3 -m 工作台.菜单.app "$@"`。`chmod +x` 后双击生效。

## 主菜单

严格按 PLAN.md §2 的字面量与编号：

```
1 新建一期      2 继续任务      3 查看稿件      4 重跑步骤
5 导入手改稿/定稿                6 归档          7 历史存档
8 配置          9 诊断          0 退出
```

## 模块

```
工作台/菜单/
├── __init__.py
├── app.py                   # 启动脚本调用的真正入口
├── menu.py                  # 主菜单循环
├── paths.py                 # 中文/空格路径处理 + SHA-256
├── prompt.py                # getpass 隐藏输入 + 日志脱敏
├── screens/
│   ├── new_issue.py         # 1
│   ├── resume.py            # 2
│   ├── view.py              # 3
│   ├── rerun.py             # 4
│   ├── import_final.py      # 5
│   ├── archive.py           # 6
│   ├── history.py           # 7
│   ├── config_screen.py     # 8
│   └── diagnose.py          # 9
└── tests/                   # unittest 套件
```

## 约束

- 所有目录操作走 `pathlib.Path`，编码显式 UTF-8。
- 不允许 `os.system("cd " + path)` 这种字符串拼接。
- 5 号菜单禁止自动覆盖已存在的带书名号定稿。
- 5 号菜单检测到期内推荐稿 / 手改稿时，先显示自动命名与归档步骤；按 Y 后按正文标题生成定稿文件并直接归档，按 N 不修改文件。
- 6 号菜单不带走 `.env`、`.workbuddy/`、`配置/`、`运行日志.ndjson`。
- 8 号菜单把 `默认.toml` 复制为 `本地.toml`，**不直接覆盖**。
- 9 号菜单对凭据做 `prompt.redact` 脱敏后再打印。

## 验证

```bash
python -m unittest discover -s 工作台/菜单/tests -v
```

测试覆盖：

- 主菜单循环（输入 `1\n0\n` 走到新建一期再退出）；
- 中文与空格路径下的 Path 行为；
- 6 号归档前后文件清单与 SHA-256 一致；
- 5 号导入定稿不覆盖既有定稿（除非显式确认）；
- `getpass` 不回显、日志脱敏。
