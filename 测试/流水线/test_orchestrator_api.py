"""编排器模块级 resume / rerun 必须存在，且优选稿经 deai 进入待定稿。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from 工作台.流水线 import orchestrator as orch_mod
from 工作台.流水线.orchestrator import Orchestrator
from 测试.流水线._stubs import StubModel, StubSearch, StubUser, make_search_source


class OrchestratorApiTests(unittest.TestCase):
    def test_module_exposes_resume_and_rerun(self) -> None:
        self.assertTrue(callable(getattr(orch_mod, "resume", None)))
        self.assertTrue(callable(getattr(orch_mod, "rerun", None)))

    def test_deai_chosen_draft_becomes_pending(self) -> None:
        """三稿 → review_1 推荐 draft_1 → deai 润色 → 待定稿/推荐稿.md。"""
        planner_text = "\n".join(f"{i}. 候选 {i}" for i in range(1, 6))
        # 初轮审稿：直接推荐 draft_1（无 block 即视为可走）
        reviewer_text = json.dumps({
            "score": 88,
            "recommendation": "draft_1",
            "pass_": True,
            "issues": [],
            "draft_version": "draft_1",
        })

        def chat(req):
            from 工作台.接口 import ModelResponse
            if req.role == "planner":
                if "三个不同角度" in req.messages[-1]["content"]:
                    text = "## 角度甲\nA\n## 角度乙\nB\n## 角度丙\nC"
                else:
                    text = planner_text
            elif req.role == "writer":
                # deai 阶段在 system 提示词里追加「去 AI 味」「硬约束」
                system_content = req.messages[0]["content"] if req.messages else ""
                if "去 AI 味" in system_content or "硬约束" in system_content:
                    text = "# 去 AI 味润色稿\n\n这是 deai 润色后的正文。"
                else:
                    text = "初稿正文" * 20
            else:
                text = reviewer_text
            return ModelResponse(
                text=text, request_model=req.request_model,
                served_model=req.request_model,
            )

        planner = StubModel(planner_text=planner_text)
        writer = StubModel(writer_text="初稿正文" * 20)
        reviewer = StubModel(reviewer_text=reviewer_text)
        planner.chat = chat  # type: ignore[method-assign]
        writer.chat = chat  # type: ignore[method-assign]
        reviewer.chat = chat  # type: ignore[method-assign]

        with tempfile.TemporaryDirectory() as issue_dir:
            orch = Orchestrator(
                issue_id="2026-09-10-00-00-00-大模型二三事",
                issue_dir=issue_dir,
                snapshot_id="snap-1",
                planner=planner, writer=writer, reviewer=reviewer,
                search=StubSearch(sources=[make_search_source(i) for i in range(1, 4)]),
                user=StubUser(choice=1),
                column="大模型二三事",
            )
            state = orch.run_issue()
            pending = Path(issue_dir) / "待定稿" / "推荐稿.md"
            self.assertTrue(pending.exists())
            self.assertIn("deai 润色后的正文", pending.read_text(encoding="utf-8"))
            # deai → finalizing 推进；finalizing 写完终态仍是 finalizing
            self.assertEqual(state.stage, "finalizing")