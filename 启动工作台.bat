@echo off
rem ============================================================
rem 熵减进化室 · 内容工坊 — Windows 启动脚本（C：数字工作台）
rem
rem 入口：python -m 工作台.菜单.app
rem 编码：UTF-8 (65001)，中文与空格路径必须在 UTF-8 下运行。
rem
rem 注意：
rem - 不要写死绝对路径或用户目录；保持脚本可移植。
rem - 不要在这里执行任何密钥写入或网络调用。
rem ============================================================

rem 切换当前目录到 BAT 所在位置；这样 ``python -m 工作台.菜单.app``
rem 能在双击 / 命令行两种入口下都解析到仓库根。
cd /d "%~dp0"

rem Windows 默认代码页是 936 / 437，中文会乱码。先切到 UTF-8。
chcp 65001 > nul

rem 强制 Python I/O 使用 UTF-8；中文路径 / 中文菜单都需要。
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

rem 透传命令行参数；菜单当前未读取，但保留扩展空间。
python -m 工作台.菜单.app %*
set EXITCODE=%ERRORLEVEL%

rem 还原代码页，避免遗留会话受影响。
chcp 936 > nul

exit /b %EXITCODE%