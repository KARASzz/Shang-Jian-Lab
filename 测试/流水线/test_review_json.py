"""审稿落盘必须能序列化非空 issues。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from 工作台.接口 import TaskState
from 工作台.流水线.review import ReviewStage
from 测试.流水线._stubs import StubModel


class ReviewJsonDumpTests(unittest.TestCase):
    def test_run_writes_json_when_issues_present(self) -> None:
        payload = json.dumps({
            "score": 10,
            "recommendation": "draft_1",
            "pass_": False,
            "issues": [{
                "severity": "block",
                "category": "fabricated_citation",
                "location": "§1",
                "description": "假引用",
                "evidence_source_ids": ["src-1"],
            }],
        })
        reviewer = StubModel(reviewer_text=payload)
        stage = ReviewStage(reviewer=reviewer, snapshot_id="snap-1")
        state = TaskState(issue_id="x", stage="review_1", snapshot_id="snap-1")
        with tempfile.TemporaryDirectory() as td:
            _, verdicts, rec = stage.run(
                state,
                issue_dir=td,
                drafts=[("draft_1", "正文")],
                review_round=1,
            )
            path = Path(td) / "审稿与返修" / "审稿-初轮.json"
            self.assertTrue(path.exists())
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["recommendation"]["issues"][0]["category"], "fabricated_citation")
            self.assertFalse(rec.pass_)
            self.assertFalse(verdicts[0].pass_)
