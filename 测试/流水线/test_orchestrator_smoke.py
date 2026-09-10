"""注入全 stub，跑一遍 1→8 步骤，断言产物文件清单。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from 测试.流水线._stubs import (
    StubModel,
    StubSearch,
    StubUser,
    make_search_source,
)


class OrchestratorSmokeTests(unittest.TestCase):
    def test_full_pipeline_happy_path_produces_all_artifacts(self):
        from 工作台.流水线 import Orchestrator

        with tempfile.TemporaryDirectory() as issue_dir:
            # 1) planner 给 5 候选
            planner_text = "\n".join(f"候选 {i}" for i in range(1, 6))
            # 2) reviewer 给出通过 + 高分
            reviewer_pass_text = json.dumps({
                "score": 90, "recommendation": "draft_1", "pass_": True,
                "issues": [],
                "draft_version": "draft_1",
            })
            writer_text = "这是初稿正文。" * 50  # ~250 字即可，骨架不强制 3000

            planner = StubModel(planner_text=planner_text)
            writer = StubModel(writer_text=writer_text)
            reviewer = StubModel(reviewer_text=reviewer_pass_text)
            search = StubSearch(sources=[make_search_source(i) for i in range(1, 6)])
            user = StubUser(choice=1)

            orch = Orchestrator(
                issue_id="2026-09-10-00-00-00-大模型二三事",
                issue_dir=issue_dir,
                snapshot_id="snap-1",
                planner=planner, writer=writer, reviewer=reviewer,
                search=search, user=user,
                column="大模型二三事",
                recent_issues=["近 1", "近 2"],
                anchor_reports=["Microsoft Work Trend Index 2026"],
                revision_rounds_max=2,
            )

            state = orch.run_issue()

            issue = Path(issue_dir)
            # 阶段产物
            self.assertTrue((issue / "选题" / "选题-候选.md").exists())
            self.assertTrue((issue / "资料" / "锚点报告-版本核验.md").exists())
            self.assertTrue((issue / "资料" / "证据清单.json").exists())
            self.assertTrue((issue / "策划" / "三角度策划.md").exists())
            for i in (1, 2, 3):
                self.assertTrue((issue / "三篇初稿" / f"初稿-{i}.md").exists())
            self.assertTrue((issue / "审稿与返修" / "审稿-初轮.json").exists())
            self.assertTrue((issue / "运行记录" / "checkpoint.json").exists())
            # 终态：finalizing（内存与磁盘一致）
            self.assertEqual(state.stage, "finalizing")
            ck = json.loads((issue / "运行记录" / "checkpoint.json").read_text(encoding="utf-8"))
            self.assertEqual(ck["stage"], "finalizing")
            chosen = json.loads((issue / "选题" / "选定.json").read_text(encoding="utf-8"))
            self.assertEqual(chosen["topic"], "候选 1")
            evidence = json.loads((issue / "资料" / "证据清单.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence["topic"], "候选 1")
            plan = (issue / "策划" / "三角度策划.md").read_text(encoding="utf-8")
            headings = [ln for ln in plan.splitlines() if ln.startswith("## ")]
            self.assertGreaterEqual(len(headings), 3)
            for i in (1, 2, 3):
                body = (issue / "三篇初稿" / f"初稿-{i}.md").read_text(encoding="utf-8")
                self.assertNotIn("占位角度", body)
            # finalizing 产物
            self.assertTrue((issue / "待定稿" / "推荐稿.md").exists())
            self.assertTrue((issue / "待定稿" / "备选标题.md").exists())
            self.assertTrue((issue / "待定稿" / "摘要与资料口径.md").exists())


if __name__ == "__main__":
    unittest.main()
