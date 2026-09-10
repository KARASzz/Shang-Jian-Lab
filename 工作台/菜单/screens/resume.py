"""菜单 2：继续任务。

- 定位 ``进行中/`` 下最新一期（按目录名倒序）。
- 读取 ``运行记录/checkpoint.json``，打印当前 ``stage`` 与最近阶段。
- 通过 ``工作台.流水线.orchestrator.resume`` 通知 B 续跑；B 未到位则
  :func:`NotImplementedError` 占位。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import paths
from ..paths import list_issue_dirs


def load_checkpoint(issue_root: Path) -> dict[str, Any]:
    """读取 ``运行记录/checkpoint.json``；不存在抛 :class:`FileNotFoundError`。"""

    ck = issue_root / "运行记录" / "checkpoint.json"
    return json.loads(paths.read_text(ck))


def locate_latest_issue() -> Path | None:
    """``进行中/`` 下最新一期目录；不存在返回 ``None``。"""

    candidates = list_issue_dirs(paths.in_progress_dir())
    return candidates[0] if candidates else None


def resume_latest() -> Path | None:
    """定位最新期并尝试通知流水线续跑。

    返回期目录路径；无进行中则返回 ``None``。调用方负责打印。
    """

    issue_root = locate_latest_issue()
    if issue_root is None:
        return None
    state = load_checkpoint(issue_root)
    _notify_orchestrator_resume(issue_root, state)
    return issue_root


def _notify_orchestrator_resume(issue_root: Path, state: dict[str, Any]) -> None:
    """调用流水线 ``resume`` 从 checkpoint 续跑。"""

    from 工作台.流水线.orchestrator import resume as orch_resume

    orch_resume(issue_root=issue_root, stage=state.get("stage"))


def run(io) -> None:
    """交互入口。"""

    io.println("【2 继续任务】")
    issue_root = locate_latest_issue()
    if issue_root is None:
        io.println("当前没有进行中任务。")
        return
    state = load_checkpoint(issue_root)
    io.println(f"本期：{state.get('issue_id', issue_root.name)}")
    io.println(f"当前阶段：{state.get('stage', '未知')}")
    io.println(f"快照：{state.get('snapshot_id', '未冻结')}")
    io.println(f"最后检查点：{state.get('last_checkpoint_at', '未知')}")
    io.println(f"已标过期：{', '.join(state.get('rerun_invalidated', [])) or '无'}")
    try:
        _notify_orchestrator_resume(issue_root, state)
        io.println("已续跑本期流水线。")
    except Exception as exc:  # noqa: BLE001 — 菜单兜底，展示原因
        io.println(f"续跑失败：{type(exc).__name__}: {exc}")


__all__ = ["load_checkpoint", "locate_latest_issue", "resume_latest", "run"]