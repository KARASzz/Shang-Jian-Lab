"""菜单 4：重跑步骤。

按 PLAN.md §4「任务状态」：

- 重跑上游 → 当前阶段及之后全部 ``rerun_invalidated``；
- 恢复时禁止混用版本。

菜单 4 仅做交互调度：将上游 / 当前阶段 / 选项写入重跑请求，调
用 ``工作台.流水线.orchestrator.rerun``。B 未到位时
``NotImplementedError`` 占位。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .. import paths, prompt
from ..paths import list_issue_dirs

# 阶段顺序，按 :mod:`工作台/接口规范.md` 第 4 节。
STAGE_ORDER: tuple[str, ...] = (
    "topic_selection",
    "evidence_collection",
    "planning",
    "draft_1",
    "draft_2",
    "draft_3",
    "review_1",
    "revise_1",
    "review_2",
    "revise_2",
    "awaiting_human",
    "finalizing",
    "archived",
)


@dataclass(frozen=True)
class RerunPlan:
    """重跑计划，便于测试断言。"""

    issue_id: str
    upstream: str
    current: str
    will_invalidate: tuple[str, ...]


def parse_stage(raw: str) -> str:
    """校验并返回合法阶段名。"""

    raw = raw.strip()
    if raw not in STAGE_ORDER:
        raise ValueError(f"未知阶段 {raw!r}；合法阶段：{STAGE_ORDER}")
    return raw


def compute_invalidation(upstream: str, current: str) -> tuple[str, ...]:
    """计算上游重跑后必须标为过期的阶段集合。

    返回从 ``upstream`` 之后到 ``current``（含）的所有阶段，按
    出现顺序排列，便于诊断屏打印。
    """

    if upstream not in STAGE_ORDER or current not in STAGE_ORDER:
        raise ValueError("upstream/current 必须是合法阶段名")
    up_idx = STAGE_ORDER.index(upstream)
    cur_idx = STAGE_ORDER.index(current)
    if up_idx > cur_idx:
        raise ValueError("upstream 不能晚于 current")
    return STAGE_ORDER[up_idx + 1 : cur_idx + 1]


def _locate_target_issue() -> Path | None:
    candidates = list_issue_dirs(paths.in_progress_dir())
    return candidates[0] if candidates else None


def _persist_invalidation(issue_root: Path, upstream: str, invalidate: tuple[str, ...]) -> None:
    """把待过期的下游阶段写入 checkpoint。"""

    ck = issue_root / "运行记录" / "checkpoint.json"
    state = json.loads(paths.read_text(ck))
    flagged = set(state.get("rerun_invalidated", []))
    flagged.update(invalidate)
    state["rerun_invalidated"] = sorted(flagged)
    tmp = ck.with_suffix(".json.tmp")
    paths.write_text(tmp, json.dumps(state, ensure_ascii=False, indent=2))
    tmp.replace(ck)


def build_rerun_plan(issue_root: Path, upstream: str) -> RerunPlan:
    """根据当前 checkpoint 计算重跑计划。"""

    ck = issue_root / "运行记录" / "checkpoint.json"
    state = json.loads(paths.read_text(ck))
    current = state.get("stage", "")
    parse_stage(current)
    upstream = parse_stage(upstream)
    invalidate = compute_invalidation(upstream, current)
    return RerunPlan(
        issue_id=state.get("issue_id", issue_root.name),
        upstream=upstream,
        current=current,
        will_invalidate=invalidate,
    )


def _notify_orchestrator_rerun(plan: RerunPlan) -> None:
    try:
        from 工作台.流水线 import orchestrator  # type: ignore[import-not-found]
    except ImportError:
        raise NotImplementedError(
            "工作台.流水线.orchestrator 尚未由 B 子智能体实现；菜单仅做调度。"
        ) from None
    if not hasattr(orchestrator, "rerun"):
        raise NotImplementedError("orchestrator.rerun 接口缺失，请联系 B 子智能体补齐。")
    orchestrator.rerun(issue_id=plan.issue_id, upstream=plan.upstream, invalidate=plan.will_invalidate)


def run(io) -> None:
    """交互入口。"""

    io.println("【4 重跑步骤】")
    issue_root = _locate_target_issue()
    if issue_root is None:
        io.println("当前没有进行中任务。")
        return
    try:
        current_stage = json.loads(paths.read_text(issue_root / "运行记录" / "checkpoint.json")).get("stage", "")
    except FileNotFoundError:
        io.println("本期尚未初始化检查点，请用 1 号菜单先建期。")
        return
    io.println(f"当前阶段：{current_stage}")
    io.print("上游阶段（重跑起点）：")
    upstream = io.read_line()
    try:
        plan = build_rerun_plan(issue_root, upstream)
    except ValueError as exc:
        io.println(f"输入有误：{exc}")
        return
    io.println(f"将标记过期：{', '.join(plan.will_invalidate) or '无'}")
    if not prompt.confirm("确认重跑？", default_no=True):
        io.println("已取消。")
        return
    _persist_invalidation(issue_root, plan.upstream, plan.will_invalidate)
    try:
        _notify_orchestrator_rerun(plan)
    except NotImplementedError as exc:
        io.println(f"流水线尚未就绪（{exc}），仅记录过期阶段。")


__all__ = ["STAGE_ORDER", "RerunPlan", "build_rerun_plan", "compute_invalidation", "parse_stage", "run"]