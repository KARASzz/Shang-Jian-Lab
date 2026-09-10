"""``启动工作台.bat`` / ``启动工作台.command`` 的真正入口。

入口对外只暴露 :func:`main`：

- :func:`main` 调用 :func:`工作台.菜单.menu.run_loop`，按用户选择退出码 ``0``；
- 提供 :func:`main_exit_code` 让双平台启动脚本在异常时拿到非零退出码；
- 不直接读取 stdin/stdout，由 ``menu.StdioIO`` 内部处理，便于测试桩替换。
"""

from __future__ import annotations

import sys

from .menu import run_loop


def main(argv: list[str] | None = None) -> int:
    """运行主菜单循环。``argv`` 仅用于将来追加命令行参数，当前忽略。"""

    # 仅消费 argv 防止静态检查提示，不向菜单传参。
    _ = argv if argv is not None else sys.argv[1:]
    return run_loop()


def main_exit_code() -> int:
    """``python -m 工作台.菜单`` 使用的退出码入口。"""

    try:
        return main()
    except KeyboardInterrupt:
        return 130  # 与 POSIX 习惯保持一致


if __name__ == "__main__":
    raise SystemExit(main_exit_code())


__all__ = ["main", "main_exit_code"]