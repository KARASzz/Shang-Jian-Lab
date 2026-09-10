"""任务状态机（接口规范 §4）。

阶段流转必须与 ``工作台/接口规范.md`` 第 4 节的字面量完全一致；
阶段推进与重跑/恢复用纯函数实现，便于测试。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Iterable

from 工作台.接口 import Stage, TaskState


# 接口规范 §4 的字面顺序；finalizing / archived 不在自动流水线里推进。
STAGE_ORDER: tuple[Stage, ...] = (
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
)


# 上游重跑时被标记为过期的下游映射：键 = 被重跑的阶段，值 = 当前及之后所有阶段。
# 与 PLAN §4「重跑上游生成新版本并将下游标为过期」一致。
RERUN_DOWNSTREAM: dict[Stage, tuple[Stage, ...]] = {
    "topic_selection": (
        "topic_selection", "evidence_collection", "planning",
        "draft_1", "draft_2", "draft_3",
        "review_1", "revise_1", "review_2", "revise_2",
    ),
    "evidence_collection": (
        "evidence_collection", "planning",
        "draft_1", "draft_2", "draft_3",
        "review_1", "revise_1", "review_2", "revise_2",
    ),
    "planning": (
        "planning", "draft_1", "draft_2", "draft_3",
        "review_1", "revise_1", "review_2", "revise_2",
    ),
    "draft_1": ("draft_1", "draft_2", "draft_3",
                "review_1", "revise_1", "review_2", "revise_2"),
    "draft_2": ("draft_2", "draft_3",
                "review_1", "revise_1", "review_2", "revise_2"),
    "draft_3": ("draft_3", "review_1", "revise_1", "review_2", "revise_2"),
    "review_1": ("review_1", "revise_1", "review_2", "revise_2"),
    "revise_1": ("revise_1", "review_2", "revise_2"),
    "review_2": ("review_2", "revise_2"),
    "revise_2": ("revise_2",),
}


# 返修轮数上限之后进入 awaiting_human；最终定稿需由用户触发（5/6 号菜单）。
AWAIT_HUMAN: Stage = "awaiting_human"
FINALIZING: Stage = "finalizing"
ARCHIVED: Stage = "archived"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _index(stage: Stage) -> int:
    if stage in (AWAIT_HUMAN, FINALIZING, ARCHIVED):
        return -1
    return STAGE_ORDER.index(stage)


def advance(state: TaskState, event: str = "ok") -> TaskState:
    """推进到下一阶段。

    event：
        - ``"ok"``：正常推进。
        - ``"await_human"``：转入 awaiting_human（用于返修超限等）。
        - ``"finalizing"``：转入 finalizing（仅在 review 通过且 ≤ 2 轮返修时）。
        - ``"archived"``：由用户触发；自动流水线一般不调用。
    """
    if event == "await_human":
        return replace(state, stage=AWAIT_HUMAN,
                       last_checkpoint_at=_now_iso())
    if event == "finalizing":
        return replace(state, stage=FINALIZING,
                       last_checkpoint_at=_now_iso())
    if event == "archived":
        return replace(state, stage=ARCHIVED,
                       last_checkpoint_at=_now_iso())

    idx = _index(state.stage)
    if idx < 0:
        # 已在终态
        return state
    if idx + 1 >= len(STAGE_ORDER):
        # 已到 revise_2 后，正常流水线会切换到 finalizing/await_human
        return state
    next_stage = STAGE_ORDER[idx + 1]
    return replace(state, stage=next_stage, last_checkpoint_at=_now_iso())


def is_terminal(state: TaskState) -> bool:
    return state.stage in (AWAIT_HUMAN, FINALIZING, ARCHIVED)


def rerun(state: TaskState, target: Stage) -> TaskState:
    """把目标阶段标为重跑起点，并把当前及之后所有阶段记入 ``rerun_invalidated``。

    行为对齐 PLAN §4「重跑上游生成新版本并将下游标为过期」。
    """
    if target not in STAGE_ORDER:
        raise ValueError(f"无法重跑非流水线阶段：{target}")
    invalid = list(RERUN_DOWNSTREAM[target])
    return replace(
        state,
        stage=target,
        rerun_invalidated=invalid,
        last_checkpoint_at=_now_iso(),
    )


def resume_after_rerun(
    state: TaskState,
    current_versions: dict[str, str],
) -> TaskState:
    """恢复时校验**未过期**阶段的产物哈希；不一致 → ``VersionMixingError``。

    ``rerun_invalidated`` 中的阶段允许被新产物替换，不视为混用。
    """
    from 工作台.流水线.checkpoint import VersionMixingError

    invalid = set(state.rerun_invalidated)
    bad: list[str] = []
    for stage, digest in current_versions.items():
        if stage in invalid:
            continue
        expected = state.versions.get(stage)
        if expected is None:
            continue
        if expected != digest:
            bad.append(stage)
    if bad:
        raise VersionMixingError(f"版本不一致，禁止恢复：{', '.join(bad)}")
    return replace(state, rerun_invalidated=list(state.rerun_invalidated))


__all__ = [
    "STAGE_ORDER",
    "RERUN_DOWNSTREAM",
    "AWAIT_HUMAN",
    "FINALIZING",
    "ARCHIVED",
    "advance",
    "is_terminal",
    "rerun",
    "resume_after_rerun",
]
