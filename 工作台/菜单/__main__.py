"""``python -m 工作台.菜单`` 入口。

仅做薄壳，把控制权交给 :mod:`工作台.菜单.app`。
"""

from __future__ import annotations

import sys

from . import app


if __name__ == "__main__":
    sys.exit(app.main_exit_code())


__all__ = []