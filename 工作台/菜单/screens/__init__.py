"""数字菜单屏。

每个子模块实现 PLAN.md §2 中的一个菜单项（编号 1-9）。所有屏
仅负责 I/O 与交互编排；遇到需要调模型 / 检索 / 流水线业务
的地方，统一向 ``工作台.流水线.orchestrator`` 接口发起（缺
口由 B 提供，目前抛 ``NotImplementedError`` 占位）。
"""

from . import (
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

__all__ = [
    "new_issue",
    "resume",
    "view",
    "rerun",
    "import_final",
    "archive",
    "history",
    "config_screen",
    "diagnose",
]