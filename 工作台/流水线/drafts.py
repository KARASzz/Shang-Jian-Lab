"""三篇独立初稿（PLAN §3 步骤 4）。"""

from __future__ import annotations

from pathlib import Path

from 工作台.接口 import ModelClient, ModelRequest
from 工作台.流水线.checkpoint import (
    atomic_write_checkpoint,
    commit_stage,
    record_version,
)
from 工作台.流水线.prompts import request_model_of, system_prompt
from 工作台.流水线.state import advance


class DraftsStage:
    """调 writer 依次生成 3 篇独立初稿。"""

    def __init__(
        self,
        *,
        writer: ModelClient,
        snapshot_id: str,
        target_words: int = 3000,
    ) -> None:
        self.writer = writer
        self.snapshot_id = snapshot_id
        self.target_words = target_words

    def build_request(
        self,
        *,
        angle: str,
        topic: str,
        plan_text: str,
        evidence_ids: list[str],
    ) -> ModelRequest:
        messages = [
            {"role": "system", "content": system_prompt("writer")},
            {
                "role": "user",
                "content": (
                    f"选题：{topic}\n角度：{angle}\n策划：\n{plan_text}\n"
                    f"可用证据编号：{', '.join(evidence_ids) or '（无）'}\n"
                    f"目标字数：约 {self.target_words} 字；用「你」；DeAI 风格。"
                ),
            },
        ]
        return ModelRequest(
            role="writer",
            messages=messages,
            temperature=0.7,
            request_model=request_model_of(self.writer, "qwen3.7-plus"),
            snapshot_id=self.snapshot_id,
        )

    def run(
        self,
        state,
        *,
        issue_dir: str,
        topic: str,
        angles: list[str],
        plan_text: str,
        evidence_ids: list[str],
    ):
        if len(angles) != 3:
            raise ValueError("DraftsStage 需要恰好 3 个角度")

        drafts_dir = Path(issue_dir) / "三篇初稿"
        drafts_dir.mkdir(parents=True, exist_ok=True)

        start = {"draft_1": 1, "draft_2": 2, "draft_3": 3}.get(state.stage, 1)
        for i, angle in enumerate(angles, 1):
            if i < start:
                continue
            req = self.build_request(
                angle=angle,
                topic=topic,
                plan_text=plan_text,
                evidence_ids=evidence_ids,
            )
            resp = self.writer.chat(req)
            if resp.raw_error:
                raise RuntimeError(f"writer 第 {i} 次失败：{resp.raw_error}")
            md = resp.text
            (drafts_dir / f"初稿-{i}.md").write_text(md, encoding="utf-8")
            state = record_version(state, f"draft_{i}", md)
            if i < 3:
                state = advance(state)
                atomic_write_checkpoint(state, Path(issue_dir) / "运行记录")
        state = commit_stage(
            state,
            Path(issue_dir) / "运行记录",
            version_key="draft_3",
            text=(drafts_dir / "初稿-3.md").read_text(encoding="utf-8"),
        )
        return state, [drafts_dir / f"初稿-{i}.md" for i in (1, 2, 3)]


__all__ = ["DraftsStage"]
