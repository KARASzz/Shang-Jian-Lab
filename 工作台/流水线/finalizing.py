"""待定稿产物（PLAN §3 步骤 7）。

``finalizing.py`` 只产出推荐稿 + 备选标题 + 摘要 + 资料口径；
带书名号的定稿由用户在 5 号菜单导入，**不**在本流水线职责内。
"""

from __future__ import annotations

from pathlib import Path

from 工作台.接口 import ModelClient, ModelRequest, ReviewVerdict
from 工作台.流水线.checkpoint import (
    atomic_write_checkpoint,
    record_version,
)


class FinalizingStage:
    """把推荐稿 + 备选标题 + 摘要 + 资料口径写到 ``待定稿/``。"""

    def __init__(self, *, writer: ModelClient, snapshot_id: str) -> None:
        self.writer = writer
        self.snapshot_id = snapshot_id

    def build_titles_request(self, *, draft_text: str) -> ModelRequest:
        return ModelRequest(
            role="writer",
            messages=[
                {"role": "system", "content": "writer-system"},
                {
                    "role": "user",
                    "content": (
                        "基于以下正文给出 5 个备选标题（≤ 22 字、不带书名号）：\n"
                        + draft_text
                    ),
                },
            ],
            temperature=0.7,
            request_model="qwen3.7-plus",
            snapshot_id=self.snapshot_id,
        )

    def build_summary_request(self, *, draft_text: str) -> ModelRequest:
        return ModelRequest(
            role="writer",
            messages=[
                {"role": "system", "content": "writer-system"},
                {
                    "role": "user",
                    "content": (
                        "基于以下正文给出 200 字内摘要与资料口径：\n"
                        + draft_text
                    ),
                },
            ],
            temperature=0.7,
            request_model="qwen3.7-plus",
            snapshot_id=self.snapshot_id,
        )

    def _wrap(self, title: str, body: str) -> str:
        return f"# {title}\n\n{body}\n"

    def run(
        self,
        state,
        *,
        issue_dir: str,
        draft_text: str,
        verdict: ReviewVerdict,
        source_titles: list[str],
        evidence_citations: list[str],
    ):
        if not verdict.pass_:
            raise RuntimeError("推荐稿未通过审稿，禁止进入 finalizing")

        titles_resp = self.writer.chat(self.build_titles_request(draft_text=draft_text))
        summary_resp = self.writer.chat(self.build_summary_request(draft_text=draft_text))

        pending_dir = Path(issue_dir) / "待定稿"
        pending_dir.mkdir(parents=True, exist_ok=True)

        (pending_dir / "推荐稿.md").write_text(draft_text, encoding="utf-8")
        titles_md = self._wrap("备选标题", titles_resp.text)
        (pending_dir / "备选标题.md").write_text(titles_md, encoding="utf-8")

        summary_md = self._wrap(
            "摘要与资料口径",
            summary_resp.text + "\n\n## 资料口径\n\n"
            + "\n".join(f"- {t}" for t in source_titles)
            + "\n\n## 关键事实证据编号\n\n"
            + "\n".join(f"- {c}" for c in evidence_citations),
        )
        (pending_dir / "摘要与资料口径.md").write_text(summary_md, encoding="utf-8")

        state = record_version(state, "finalizing", draft_text)
        state = atomic_write_checkpoint(state, Path(issue_dir) / "运行记录")
        from 工作台.流水线.state import advance
        return advance(state, event="finalizing"), {
            "推荐稿": pending_dir / "推荐稿.md",
            "备选标题": pending_dir / "备选标题.md",
            "摘要与资料口径": pending_dir / "摘要与资料口径.md",
        }


__all__ = ["FinalizingStage"]
