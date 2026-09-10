"""三角度策划（PLAN §3 步骤 3）。"""

from __future__ import annotations

from pathlib import Path

from 工作台.接口 import ModelClient, ModelRequest
from 工作台.流水线.checkpoint import commit_stage
from 工作台.流水线.prompts import request_model_of, system_prompt


class PlanningStage:
    """调 planner 出三角度策划.md。"""

    def __init__(self, *, planner: ModelClient, snapshot_id: str) -> None:
        self.planner = planner
        self.snapshot_id = snapshot_id

    def build_request(self, *, topic: str, evidence_summary: str) -> ModelRequest:
        return ModelRequest(
            role="planner",
            messages=[
                {"role": "system", "content": system_prompt("planner")},
                {
                    "role": "user",
                    "content": (
                        f"选题：{topic}\n证据摘要：\n{evidence_summary}\n"
                        "请给出三个不同角度，每个含中心判断、结构和证据指针。"
                    ),
                },
            ],
            temperature=0.4,
            request_model=request_model_of(self.planner, "MiniMax-M3"),
            snapshot_id=self.snapshot_id,
        )

    def render_markdown(self, topic: str, plan_text: str) -> str:
        titles = extract_angles(plan_text)
        return f"# 三角度策划 · {topic}\n\n{plan_text.strip()}\n\n<!-- angles: {', '.join(titles)} -->\n"

    def run(self, state, *, issue_dir: str, topic: str, evidence_summary: str):
        req = self.build_request(topic=topic, evidence_summary=evidence_summary)
        resp = self.planner.chat(req)
        if resp.raw_error:
            raise RuntimeError(f"planner 策划失败：{resp.raw_error}")
        md = self.render_markdown(topic, resp.text)

        planning_dir = Path(issue_dir) / "策划"
        planning_dir.mkdir(parents=True, exist_ok=True)
        (planning_dir / "三角度策划.md").write_text(md, encoding="utf-8")

        state = commit_stage(
            state,
            Path(issue_dir) / "运行记录",
            version_key="planning",
            text=md,
        )
        return state, md


def extract_angles(plan_text: str) -> list[str]:
    """从策划正文抽出至少 3 个 ``##`` 角度标题；不足则失败，禁止占位。"""
    titles = [
        line[2:].strip()
        for line in plan_text.splitlines()
        if line.startswith("## ") and line[2:].strip()
    ]
    if len(titles) < 3:
        raise ValueError(f"策划未给出 3 个角度（解析到 {len(titles)} 个）")
    return titles[:3]


__all__ = ["PlanningStage", "extract_angles"]
