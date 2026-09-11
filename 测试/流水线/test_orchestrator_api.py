"""编排器模块级 resume / rerun 必须存在，且返修稿进入待定稿。"""

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

    def test_revised_draft_becomes_pending(self) -> None:
        planner_text = "\n".join(f"{i}. 候选 {i}" for i in range(1, 6))
        block = json.dumps({
            "score": 40,
            "recommendation": "draft_1",
            "pass_": False,
            "issues": [{
                "severity": "block",
                "category": "unsupported_key_fact",
                "location": "§1",
                "description": "缺证据",
            }],
        })
        passed = json.dumps({
            "score": 90,
            "recommendation": "draft_1",
            "pass_": True,
            "issues": [],
        })
        reviewer = StubModel()
        reviewer.reviewer_text = block
        # 初轮阻断，复审通过：StubModel 固定同一 reviewer_text，需按调用次数切换
        calls = {"n": 0}

        def chat(req):
            from 工作台.接口 import ModelResponse
            if req.role == "planner":
                text = planner_text
                if "三个不同角度" in req.messages[-1]["content"]:
                    text = "## 角度甲\nA\n## 角度乙\nB\n## 角度丙\nC"
            elif req.role == "writer":
                text = "修订后的推荐稿" if "返修" in req.messages[-1]["content"] else "初稿正文" * 20
            else:
                calls["n"] += 1
                text = block if calls["n"] <= 3 else passed
            return ModelResponse(text=text, request_model=req.request_model, served_model=req.request_model)

        planner = StubModel(planner_text=planner_text)
        writer = StubModel(writer_text="初稿正文" * 20)
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
                revision_rounds_max=2,
            )
            state = orch.run_issue()
            pending = Path(issue_dir) / "待定稿" / "推荐稿.md"
            self.assertTrue(pending.exists())
            self.assertIn("修订后的推荐稿", pending.read_text(encoding="utf-8"))
            self.assertEqual(state.stage, "finalizing")
