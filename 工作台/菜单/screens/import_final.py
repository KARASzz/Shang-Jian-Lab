"""菜单 5：导入手改稿 / 定稿。

按 :mod:`AGENTS.md` 「停手等用户改」与 :mod:`进行中/README.md`：

- ``熵减进化室-公众号成稿-《…》.md`` 是定稿，**最高优先级**。
- 若目标位置已存在带书名号的定稿，必须显式二次确认才覆盖。
- 自动流程不得触发覆盖（``auto_overwrite=False``）。

实现要点：

- 使用 :func:`shutil.copy2` 保留 mtime，便于审稿追溯。
- 把定稿放到 ``进行中/<issue>/待定稿/`` 下；若文件名带书名号则
  视为定稿，否则只是手改稿提示文件。
- 不读 / 不写 ``带书名号`` 以外的同名已存在文件除非用户确认。
"""

from __future__ import annotations

import dataclasses
import re
import shutil
from pathlib import Path

from .. import paths, prompt

# 仅识别 ``熵减进化室-公众号成稿-《...》.md`` 形式的文件名；定稿
# 文件名前缀源自 AGENTS.md §「仓库结构」，必须保持一致。
FINAL_NAME_RE = re.compile(r"^熵减进化室-公众号成稿-《(.+?)》\.md$")

# 目标位置。
DEST_SUBDIR = "待定稿"


@dataclasses.dataclass(frozen=True)
class ImportResult:
    """导入结果，便于测试断言。"""

    source: Path
    dest: Path
    is_final: bool
    overwrote: bool


def is_final_filename(name: str) -> bool:
    """文件名是否符合定稿 ``《…》`` 命名。"""

    return bool(FINAL_NAME_RE.match(name))


def _dest_dir(issue_root: Path) -> Path:
    return paths.ensure_dir(issue_root / DEST_SUBDIR)


def _ensure_issue() -> Path | None:
    """返回最新进行中目录；不存在返回 ``None``。"""

    candidates = paths.list_issue_dirs(paths.in_progress_dir())
    return candidates[0] if candidates else None


def import_final(
    source: Path,
    issue_root: Path,
    *,
    confirm_callback=prompt.confirm,
) -> ImportResult:
    """把用户手改稿 / 定稿拷入 ``待定稿/``。

    约束：

    - 目标位置已存在时，**必须**通过 ``confirm_callback`` 取得用户
      显式确认；测试可通过注入回调跳过交互。
    - 自动流程（无回调授权）等价于 ``confirm_callback`` 返回
      ``False``，因此默认安全。
    """

    if not source.exists():
        raise FileNotFoundError(f"源文件不存在：{source}")
    if not source.is_file():
        raise ValueError(f"源路径不是文件：{source}")
    final = is_final_filename(source.name)
    target_dir = _dest_dir(issue_root)
    dest = target_dir / source.name
    overwrote = False
    if dest.exists():
        if not confirm_callback(f"目标已存在 {dest.name}，确认覆盖？", default_no=True):
            raise PermissionError(f"目标已存在且未获授权覆盖：{dest}")
        overwrote = True
    shutil.copy2(source, dest)
    return ImportResult(source=source.resolve(), dest=dest.resolve(), is_final=final, overwrote=overwrote)


def run(io) -> None:
    """交互入口。"""

    io.println("【5 导入手改稿 / 定稿】")
    issue_root = _ensure_issue()
    if issue_root is None:
        io.println("当前没有进行中任务，请先用 1 号菜单建期。")
        return
    io.print("请把手改稿 / 定稿绝对路径拖入（或粘贴）：")
    raw = io.read_line().strip()
    if not raw:
        io.println("未提供路径。")
        return
    # 处理用户用引号包裹路径或带尾部空格的情况
    source = Path(raw.strip().strip('"').strip("'"))
    try:
        result = import_final(source, issue_root)
    except FileNotFoundError as exc:
        io.println(f"导入失败：{exc}")
        return
    except PermissionError as exc:
        io.println(f"导入未执行：{exc}")
        return
    kind = "定稿" if result.is_final else "手改稿"
    io.println(f"已导入{kind}：{result.dest}")
    if result.overwrote:
        io.println("（已覆盖既有同名文件，请确认手改稿未被自动流程替换。）")


__all__ = [
    "DEST_SUBDIR",
    "FINAL_NAME_RE",
    "ImportResult",
    "import_final",
    "is_final_filename",
    "run",
]