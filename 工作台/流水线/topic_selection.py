"""选题（PLAN §3 步骤 1）。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from 工作台.接口 import ModelClient, ModelRequest, UserInput
from 工作台.流水线.checkpoint import (
    atomic_write_checkpoint,
    record_version,
)


class TopicSelectionStage:
    """调 planner 拿 5 候选 → 用户选/自选。"""

    def __init__(
        self,
        *,
        planner: ModelClient,
        user: UserInput,
        snapshot_id: str,
    ) -> None:
        self.planner = planner
        self.user = user
        self.snapshot_id = snapshot_id

    def build_request(self, *, column: str, recent_issues: list[str]) -> ModelRequest:
        messages = [
            {"role": "system", "content": "planner-system"},  # 占位：真实系统提示词见 提示词/
            {
                "role": "user",
                "content": (
                    f"专栏：{column}\n"
                    f"近期选题：{', '.join(recent_issues) or '（无）'}\n"
                    "请给出 5 个候选选题，每个含 1 句立意。"
                ),
            },
        ]
        return ModelRequest(
            role="planner",
            messages=messages,
            temperature=0.4,
            request_model="MiniMax-M3",
            snapshot_id=self.snapshot_id,
        )

    def parse_candidates(self, text: str) -> list[str]:
        """按行解析 5 候选；少于 5 抛错。"""
        lines = [ln.strip("-* \t").strip() for ln in text.splitlines()]
        candidates = [ln for ln in lines if ln]
        if len(candidates) < 5:
            raise ValueError("planner 未给出 5 个候选选题")
        return candidates[:5]

    def render_markdown(self, column: str, candidates: list[str], choice: str) -> str:
        body = [f"# {column} · 选题候选", ""]
        for i, c in enumerate(candidates, 1):
            body.append(f"{i}. {c}")
        body += ["", f"用户最终选择：{choice}"]
        return "\n".join(body) + "\n"

    def run(
        self,
        state,
        *,
        issue_dir: str,
        column: str,
        recent_issues: list[str],
    ):
        """返回 ``(new_state, markdown)``。"""
        req = self.build_request(column=column, recent_issues=recent_issues)
        resp = self.planner.chat(req)
        candidates = self.parse_candidates(resp.text)
        choice_raw = self.user.choose_topic(candidates)
        if isinstance(choice_raw, int):
            if not (1 <= choice_raw <= len(candidates)):
                raise ValueError("用户选择超出候选范围")
            choice = candidates[choice_raw - 1]
        else:
            choice = str(choice_raw).strip()
        md = self.render_markdown(column, candidates, choice)

        topic_dir = Path(issue_dir) / "选题"
        topic_dir.mkdir(parents=True, exist_ok=True)
        (topic_dir / "选题-候选.md").write_text(md, encoding="utf-8")

        state = record_version(state, "topic_selection", md)
        atomic_write_checkpoint(state, Path(issue_dir) / "运行记录")
        from 工作台.流水线.state import advance
        return advance(state), md


__all__ = ["TopicSelectionStage"]
