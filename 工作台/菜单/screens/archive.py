"""菜单 6：归档。

按 :mod:`存档/README.md`：

- 把 ``进行中/<issue>/`` 整体迁入 ``存档/<issue>/``；
- 配置文件、密钥、``.workbuddy/memory``、运行日志 **不随期迁移**；
- 归档前用户已在 5 号菜单导入定稿；
- 迁移前后所有文件 SHA-256 一致。

实现要点：

- 使用 ``shutil.move`` 把每个子项迁过去；对需要排除的目录单独跳过；
- 期目录内的 ``.workbuddy`` 隐藏目录也不迁；
- ``运行记录/运行日志.ndjson`` 视情况可迁也可不迁，按 PLAN.md
  「仅保留当期可复现产物」排除；
- 删除空目录前先确保迁移完成；
- 整体完成后调用 :func:`paths.sha256_file` 复核归档前后的清单与哈希。
"""

from __future__ import annotations

import dataclasses
import json
import shutil
from pathlib import Path
from typing import Iterable

from .. import paths, prompt

# 随期迁移的白名单：列出的目录与文件才进入 ``存档/``。
CARRY_SUBDIRS: tuple[str, ...] = (
    "选题",
    "资料",
    "策划",
    "三篇初稿",
    "审稿与返修",
    "待定稿",
)

# 顶层保留：运行记录 / .workbuddy / 隐藏目录 / 配置文件 / 日志 均排除。
EXCLUDE_TOP_NAMES: tuple[str, ...] = (
    "运行记录",
    ".workbuddy",
    ".env",
    ".env.local",
    "本地.toml",
    "本期.toml",
    "checkpoint.json",
    "运行日志.ndjson",
)


@dataclasses.dataclass(frozen=True)
class ArchiveResult:
    """归档结果，便于测试断言。"""

    issue_id: str
    src: Path
    dst: Path
    carried_files: tuple[Path, ...]
    excluded: tuple[str, ...]


def _should_carry(name: str) -> bool:
    """顶层 ``name`` 是否随期迁移。"""

    if name in CARRY_SUBDIRS:
        return True
    if name.startswith("."):
        return False
    return False


def _verify_sha(snapshot: dict[str, tuple[Path, str]], dst_root: Path) -> list[str]:
    """对快照中每一项校验 SHA-256；返回差异路径列表（空 = 通过）。

    快照以 ``{相对路径: (源绝对路径, 源 SHA-256)}`` 形式传入，避免
    搬迁后再去读源路径导致 ``FileNotFoundError``。
    """

    diff: list[str] = []
    for rel, (src_path, src_hash) in snapshot.items():
        top = rel.split("/", 1)[0]
        if top in EXCLUDE_TOP_NAMES:
            continue
        dst_path = dst_root / rel
        if not dst_path.exists():
            diff.append(f"缺失：{rel}")
            continue
        dst_hash = paths.sha256_file(dst_path)
        if src_hash != dst_hash:
            diff.append(f"哈希不一致：{rel} {src_hash[:8]} vs {dst_hash[:8]}")
    return diff


def _stage_snapshot(issue_root: Path) -> dict[str, tuple[Path, str]]:
    """归档前快照：``{相对路径: (源绝对路径, SHA-256)}``。

    提前计算哈希，避免 ``shutil.move`` 之后再回去读源文件失败。
    """

    snap: dict[str, tuple[Path, str]] = {}
    for entry in sorted(issue_root.rglob("*")):
        if not entry.is_file():
            continue
        rel = entry.relative_to(issue_root)
        snap[rel.as_posix()] = (entry.resolve(), paths.sha256_file(entry))
    return snap


def _carry(issue_root: Path, dest_root: Path) -> list[Path]:
    """把允许随期的目录 / 文件迁到 ``dest_root``。

    使用 ``shutil.move`` 整体搬迁子目录；返回迁走的顶层文件路径列表。
    """

    carried: list[Path] = []
    paths.ensure_dir(dest_root)
    for entry in sorted(issue_root.iterdir(), key=lambda p: p.name):
        name = entry.name
        if not _should_carry(name):
            continue
        target = dest_root / name
        shutil.move(str(entry), str(target))
        carried.append(target.resolve())
    return carried


def archive_issue(issue_id: str, *, confirm_callback=prompt.confirm) -> ArchiveResult:
    """归档指定期。

    流程：

    1. 校验源存在；
    2. 二次确认（``auto`` / 测试可注入 ``confirm_callback=lambda *a, **k: True``）；
    3. 快照源文件清单；
    4. 迁入 ``存档/``；
    5. 哈希校验；
    6. 删除残留空目录；
    7. 返回 :class:`ArchiveResult`。
    """

    src = paths.issue_dir(issue_id)
    if not src.exists():
        raise FileNotFoundError(f"进行中不存在：{src}")
    if not paths.is_within(src, paths.in_progress_dir()):
        raise ValueError(f"非进行中目录：{src}")
    dst = paths.archived_issue_dir(issue_id)
    if dst.exists():
        raise FileExistsError(f"存档已存在：{dst}")
    snapshot = _stage_snapshot(src)
    if not confirm_callback(
        f"将归档 {issue_id} 到 存档/，继续？", default_no=True
    ):
        raise PermissionError("用户取消归档")
    carried = _carry(src, dst)
    diff = _verify_sha(snapshot, dst)
    if diff:
        # 校验失败：把文件迁回去以保持幂等。
        for top in dst.iterdir():
            shutil.move(str(top), str(src / top.name))
        raise RuntimeError(f"归档后哈希校验失败：{diff}")
    # 清扫残留空目录 / 隐藏目录
    for entry in list(src.iterdir()):
        if entry.is_dir():
            try:
                entry.rmdir()  # 只删空目录
            except OSError:
                # 非空目录（含隐藏）交由人工处理；保持来源不被破坏。
                continue
        else:
            entry.unlink()
    return ArchiveResult(
        issue_id=issue_id,
        src=src.resolve(),
        dst=dst.resolve(),
        carried_files=tuple(carried),
        excluded=EXCLUDE_TOP_NAMES,
    )


def _locate_target_issue() -> Path | None:
    candidates = paths.list_issue_dirs(paths.in_progress_dir())
    return candidates[0] if candidates else None


def run(io) -> None:
    """交互入口。"""

    io.println("【6 归档】")
    issue_root = _locate_target_issue()
    if issue_root is None:
        io.println("当前没有进行中任务。")
        return
    io.print(f"将归档：{issue_root.name}（回车确认 / 输入其它期名）：")
    answer = io.read_line().strip()
    target = Path(answer) if answer else issue_root
    issue_id = target.name if target.is_absolute() else answer or issue_root.name
    try:
        result = archive_issue(issue_id)
    except (FileNotFoundError, FileExistsError, PermissionError, RuntimeError, ValueError) as exc:
        io.println(f"归档失败：{exc}")
        return
    io.println(f"已迁入：{result.dst}")
    io.println(f"迁走 {len(result.carried_files)} 项 / 排除 {len(result.excluded)} 类（运行记录 / 隐藏 / 配置）。")


__all__ = [
    "ARCHIVE_VERSION",
    "CARRY_SUBDIRS",
    "EXCLUDE_TOP_NAMES",
    "ArchiveResult",
    "archive_issue",
    "run",
]

# 版本号：本期规范 v1.0 对齐。
ARCHIVE_VERSION = "1.0"