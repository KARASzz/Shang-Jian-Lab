"""三角度策划（PLAN §3 步骤 3）。"""

from __future__ import annotations

from pathlib import Path

from 工作台.接口 import ModelClient, ModelRequest
from 工作台.流水线.checkpoint import (
    atomic_write_checkpoint,
    record_version,
)


class PlanningStage:
    """调 planner 出三角度策划.md。"""

    def __init__(self, *, planner: ModelClient, snapshot_id: str) -> None:
        self.planner = planner
        self.snapshot_id = snapshot_id

    def build_request(self, *, topic: str, evidence_summary: str) -> ModelRequest:
        return ModelRequest(
            role="planner",
            messages=[
                {"role": "system", "content": "planner-system"},
                {
                    "role": "user",
                    "content": (
                        f"选题：{topic}\n证据摘要：\n{evidence_summary}\n"
                        "请给出三个不同角度，每个含中心判断、结构和证据指针。"
                    ),
                },
            ],
            temperature=0.4,
            request_model="MiniMax-M3",
            snapshot_id=self.snapshot_id,
        )

    def render_markdown(self, topic: str, plan_text: str) -> str:
        # 骨架只描述字段；真实拆分留给 reviewer/orchestrator 解析。
        return (
            f"# 三角度策划 · {topic}\n\n"
            f"```text\n{plan_text}\n```\n"
        )

    def run(self, state, *, issue_dir: str, topic: str, evidence_summary: str):
        req = self.build_request(topic=topic, evidence_summary=evidence_summary)
        resp = self.planner.chat(req)
        md = self.render_markdown(topic, resp.text)

        planning_dir = Path(issue_dir) / "策划"
        planning_dir.mkdir(parents=True, exist_ok=True)
        (planning_dir / "三角度策划.md").write_text(md, encoding="utf-8")

        state = record_version(state, "planning", md)
        state = atomic_write_checkpoint(state, Path(issue_dir) / "运行记录")
        from 工作台.流水线.state import advance
        return advance(state), md


__all__ = ["PlanningStage"]
