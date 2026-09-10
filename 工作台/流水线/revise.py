"""返修（PLAN §3 步骤 6；接口规范 §4）。

- qwen 返修 + GLM 复审；
- 最多 ``[pipeline].revision_rounds_max``（默认 2）轮；
- 超限直接 ``awaiting_human``，**不再调用模型**。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from 工作台.接口 import (
    ModelClient,
    ModelRequest,
    ReviewVerdict,
)
from 工作台.流水线.checkpoint import (
    atomic_write_checkpoint,
    record_version,
)
from 工作台.流水线.review import ReviewStage, has_blocking_issue


class MaxRevisionsExceeded(RuntimeError):
    """返修超过 ``revision_rounds_max``，必须进入 awaiting_human。"""


class ReviseStage:
    """封装返修 + 复审循环。"""

    def __init__(
        self,
        *,
        writer: ModelClient,
        reviewer: ModelClient,
        snapshot_id: str,
        revision_rounds_max: int = 2,
    ) -> None:
        if revision_rounds_max < 0:
            raise ValueError("revision_rounds_max 不能为负")
        self.writer = writer
        self.reviewer = reviewer
        self.snapshot_id = snapshot_id
        self.revision_rounds_max = revision_rounds_max
        self._review = ReviewStage(
            reviewer=reviewer,
            snapshot_id=snapshot_id,
        )

    def build_revise_request(
        self,
        *,
        draft_text: str,
        verdict: ReviewVerdict,
        round_idx: int,
    ) -> ModelRequest:
        return ModelRequest(
            role="writer",
            messages=[
                {"role": "system", "content": "writer-system"},
                {
                    "role": "user",
                    "content": (
                        f"返修轮次：{round_idx}\n"
                        f"上一轮问题：\n{verdict.__dict__}\n"
                        f"原稿：\n{draft_text}"
                    ),
                },
            ],
            temperature=0.7,
            request_model="qwen3.7-plus",
            snapshot_id=self.snapshot_id,
        )

    def _revise_once(
        self,
        *,
        issue_dir: Path,
        draft_text: str,
        verdict: ReviewVerdict,
        round_idx: int,
    ) -> tuple[str, ReviewVerdict]:
        """单次返修 + 复审。返回 ``(new_draft_text, new_verdict)``。"""
        req = self.build_revise_request(
            draft_text=draft_text, verdict=verdict, round_idx=round_idx
        )
        resp = self.writer.chat(req)
        if resp.raw_error:
            raise RuntimeError(f"writer 返修失败：{resp.raw_error}")
        new_text = resp.text

        # 复审
        new_verdicts = self._review.review_drafts(
            [(f"revise_{round_idx}", new_text)],
            previous_verdict=verdict,
        )
        new_verdict = new_verdicts[0]

        # 落盘
        review_dir = issue_dir / "审稿与返修"
        review_dir.mkdir(parents=True, exist_ok=True)
        (review_dir / f"返修-{round_idx}.md").write_text(new_text, encoding="utf-8")
        return new_text, new_verdict

    def run(
        self,
        state,
        *,
        issue_dir: str,
        draft_text: str,
        verdict: ReviewVerdict,
        draft_version: str,
    ):
        """执行返修循环；超限抛 ``MaxRevisionsExceeded``。

        调用方负责捕获异常并把 ``state.stage`` 切到 ``awaiting_human``。
        """
        issue_path = Path(issue_dir)
        rounds = self.revision_rounds_max
        current_text = draft_text
        current_verdict = verdict

        if rounds == 0:
            # 配置禁止返修：直接判定为超限
            raise MaxRevisionsExceeded("revision_rounds_max=0，跳过返修")

        for round_idx in range(1, rounds + 1):
            current_text, current_verdict = self._revise_once(
                issue_dir=issue_path,
                draft_text=current_text,
                verdict=current_verdict,
                round_idx=round_idx,
            )
            state = record_version(state, f"revise_{round_idx}", current_text)
            state = atomic_write_checkpoint(state, issue_path / "运行记录")
            from 工作台.流水线.state import advance
            state = advance(state)
            if not has_blocking_issue(current_verdict):
                return state, current_text, current_verdict

        # 第 rounds 轮跑完仍未通过 → 超限
        raise MaxRevisionsExceeded(
            f"已用完 {rounds} 轮返修，仍存在阻断项；进入 awaiting_human"
        )


__all__ = ["MaxRevisionsExceeded", "ReviseStage"]
