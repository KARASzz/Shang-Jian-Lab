"""菜单 3：查看稿件。

- 列出当前 stage 在 ``进行中/<issue>/`` 下的产物文件。
- 标注每个文件的角色（初稿/审稿/返修/推荐稿/定稿）。
- ``熵减进化室-公众号成稿-《…》.md`` 单独标记为「用户定稿（最高优先级）」。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .. import paths

# 角色标签映射（按目录相对位置匹配）。
_ROLE_BY_DIR: dict[str, str] = {
    "选题": "选题",
    "资料": "资料",
    "策划": "策划",
    "三篇初稿": "初稿",
    "审稿与返修": "审稿/返修",
    "待定稿": "待定稿",
    "运行记录": "运行记录",
}

_FINAL_NAME_HINT = "熵减进化室-公众号成稿-《"


def _classify(rel_path: Path) -> str:
    """根据文件相对位置返回角色标签。"""

    top = rel_path.parts[0] if rel_path.parts else ""
    role = _ROLE_BY_DIR.get(top, "其他")
    if _FINAL_NAME_HINT in rel_path.name:
        role = "用户定稿"
    return role


def list_issue_files(issue_root: Path) -> list[tuple[Path, str]]:
    """列出当期所有产物文件及其角色标签。

    跳过 ``.workbuddy``、``.tmp_*``、``__pycache__`` 等非交付物。
    返回 ``[(绝对路径, 角色)]``，按目录顺序排列，便于对齐打印。
    """

    if not issue_root.exists():
        return []
    out: list[tuple[Path, str]] = []
    for entry in sorted(issue_root.rglob("*")):
        if not entry.is_file():
            continue
        rel = entry.relative_to(issue_root)
        if any(part.startswith(".") or part == "__pycache__" for part in rel.parts):
            continue
        if entry.name.startswith(".tmp_"):
            continue
        out.append((entry, _classify(rel)))
    return out


def _read_checkpoint_stage(issue_root: Path) -> str:
    ck = issue_root / "运行记录" / "checkpoint.json"
    if not ck.exists():
        return "未初始化"
    state = json.loads(paths.read_text(ck))
    return state.get("stage", "未知")


def view_latest() -> Path | None:
    """定位最新一期并返回其路径；无期返回 ``None``。"""

    candidates = paths.list_issue_dirs(paths.in_progress_dir())
    return candidates[0] if candidates else None


def run(io) -> None:
    """交互入口。"""

    io.println("【3 查看稿件】")
    issue_root = view_latest()
    if issue_root is None:
        io.println("当前没有进行中任务。")
        return
    stage = _read_checkpoint_stage(issue_root)
    io.println(f"本期：{issue_root.name}（当前阶段：{stage}）")
    files = list_issue_files(issue_root)
    if not files:
        io.println("（暂无产物文件）")
        return
    for path, role in files:
        rel = path.relative_to(issue_root)
        io.println(f"  [{role}] {rel.as_posix()}")


__all__ = ["list_issue_files", "view_latest", "run"]