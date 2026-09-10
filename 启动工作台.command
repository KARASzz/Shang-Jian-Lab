#!/usr/bin/env bash
# ============================================================
# 熵减进化室 · 内容工坊 — macOS / Linux 启动脚本（C：数字工作台）
#
# 入口：python3 -m 工作台.菜单.app
# 编码：UTF-8 (en_US.UTF-8)；中文与空格路径必须 UTF-8。
#
# 注意：
# - 不要写死绝对路径或用户目录；保持脚本可移植。
# - 不要在这里执行任何密钥写入或网络调用。
# ============================================================

set -e

# 把当前工作目录切到脚本所在位置（即仓库根），便于 ``python -m``
# 在 Finder 双击与终端两种入口下都能解析到正确包。
cd "$(dirname "$0")"

# 强制 UTF-8，避免 macOS 默认 zh_CN.UTF-8 / Linux 无 locale 下中文乱码。
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

# 透传所有参数；菜单当前未读取，但保留扩展空间。
exec python3 -m 工作台.菜单.app "$@"