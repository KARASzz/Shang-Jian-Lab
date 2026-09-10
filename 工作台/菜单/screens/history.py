"""菜单 7：历史存档。

- 列出 ``存档/`` 下所有时间戳目录；
- 对每个目录显示：期名、含文件数、含图片张数、含外部参考标记；
- 不打印文件正文，不读取敏感内容。
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from .. import paths


@dataclasses.dataclass(frozen=True)
class HistoryEntry:
    """历史存档条目。"""

    issue_id: str
    root: Path
    file_count: int
    image_count: int
    has_external_reference: bool
    has_final_draft: bool


# 配图文件后缀：与 ``AGENTS.md` 仓库结构中的图片命名约定一致。
_IMAGE_SUFFIXES: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp", ".gif")


def _classify(entry: Path) -> HistoryEntry:
    files = [p for p in entry.rglob("*") if p.is_file()]
    images = sum(1 for p in files if p.suffix.lower() in _IMAGE_SUFFIXES)
    has_ext = any("外部开源-灵感来源" in p.name for p in files)
    has_final = any(p.name.startswith("熵减进化室-公众号成稿-《") for p in files)
    return HistoryEntry(
        issue_id=entry.name,
        root=entry.resolve(),
        file_count=len(files),
        image_count=images,
        has_external_reference=has_ext,
        has_final_draft=has_final,
    )


def list_history(parent: Path | None = None) -> list[HistoryEntry]:
    """列出 ``存档/`` 下所有期，按目录名倒序。"""

    base = parent or paths.archive_dir()
    out: list[HistoryEntry] = []
    for entry in paths.list_issue_dirs(base):
        out.append(_classify(entry))
    return out


def run(io) -> None:
    """交互入口。"""

    io.println("【7 历史存档】")
    entries = list_history()
    if not entries:
        io.println("（暂无存档）")
        return
    for entry in entries:
        flags = []
        if entry.has_external_reference:
            flags.append("外部参考")
        if entry.has_final_draft:
            flags.append("含定稿")
        flag_str = " / ".join(flags) if flags else "-"
        io.println(
            f"  {entry.issue_id}  "
            f"文件 {entry.file_count}  配图 {entry.image_count}  标记 {flag_str}"
        )


__all__ = ["HistoryEntry", "list_history", "run"]