"""主菜单循环。

按 PLAN.md §2 固定菜单字面量：

    1 新建一期      2 继续任务      3 查看稿件      4 重跑步骤
    5 导入手改稿/定稿                6 归档          7 历史存档
    8 配置          9 诊断          0 退出

约束：

- 仅接受 0-9 数字输入；其它字符原样打印一行错误并不退出；
- 输入支持中文与空格路径（直接走 ``input`` 即可，菜单不构造 shell 字符串）；
- 主循环对外暴露 :class:`MenuRunner` 协议，便于测试注入 ``io``。
"""

from __future__ import annotations

import dataclasses
import sys
from typing import Callable, Protocol

from . import paths
from .screens import (
    archive,
    config_screen,
    diagnose,
    history,
    import_final,
    new_issue,
    rerun,
    resume,
    view,
)

MENU_BANNER = """\
=========================
 熵减进化室 · 内容工坊
=========================
 1 新建一期
 2 继续任务
 3 查看稿件
 4 重跑步骤
 5 导入手改稿/定稿
 6 归档
 7 历史存档
 8 配置
 9 诊断
 0 退出
-------------------------
"""

# 编号 → 处理函数；保持与 PLAN.md §2 字面量严格一致。
_HANDLERS: dict[str, Callable] = {
    "1": new_issue.run,
    "2": resume.run,
    "3": view.run,
    "4": rerun.run,
    "5": import_final.run,
    "6": archive.run,
    "7": history.run,
    "8": config_screen.run,
    "9": diagnose.run,
}


class MenuIO(Protocol):
    """菜单与外界的协议：标准输入输出。"""

    def println(self, text: str = "") -> None: ...
    def print(self, text: str) -> None: ...
    def read_line(self) -> str: ...


@dataclasses.dataclass
class StdioIO:
    """默认控制台 I/O；按 Ctrl-C / EOF 优雅返回。"""

    out=None
    inp=None

    def __post_init__(self) -> None:
        import sys
        self.out = self.out or sys.stdout
        self.inp = self.inp or sys.stdin

    def println(self, text: str = "") -> None:
        self.out.write(text + "\n")
        self.out.flush()

    def print(self, text: str) -> None:
        self.out.write(text)
        self.out.flush()

    def read_line(self) -> str:
        try:
            return self.inp.readline()
        except (KeyboardInterrupt, EOFError):
            return ""

        if line is None:
            return ""
        return line.rstrip("\n")


def _ask(io: MenuIO) -> str:
    """读取一行菜单选择；过滤前后空白。"""

    io.print("\n请选择（0-9）：")
    return io.read_line().strip()


def run_loop(io: MenuIO | None = None) -> int:
    """主循环；返回退出码（``0`` = 正常退出）。"""

    io = io or StdioIO()
    io.println(MENU_BANNER)
    while True:
        choice = _ask(io)
        if choice == "0":
            io.println("已退出。")
            return 0
        handler = _HANDLERS.get(choice)
        if handler is None:
            io.println(f"未识别的选项：{choice!r}（请输入 0-9 之间的数字）")
            continue
        try:
            handler(io)
        except Exception as exc:  # 屏幕级兜底，避免一个屏崩整个循环
            io.println(f"该菜单项执行出错：{type(exc).__name__}: {exc}")
            continue
        finally:
            io.println("")


__all__ = ["MENU_BANNER", "MenuIO", "StdioIO", "run_loop"]