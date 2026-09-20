from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from 工作台.接口 import ModelResponse, TaskState
from 工作台.接入.models.errors import RateLimitError
from 工作台.流水线.drafts import DraftsStage


class FakeModel:
    def __init__(self, model: str, result):
        self.config = SimpleNamespace(request_model=model)
        self.result = result
        self.requests = []

    def chat(self, request):
        self.requests.append(request)
        if isinstance(self.result, Exception):
            raise self.result
        return ModelResponse(text=self.result, request_model=request.request_model)


class DraftFallbackTests(unittest.TestCase):
    def run_draft3(self, writer, fallbacks):
        with tempfile.TemporaryDirectory() as issue_dir:
            state = TaskState(issue_id="issue", stage="draft_3", snapshot_id="snap")
            stage = DraftsStage(writer=writer, writer_fallbacks=fallbacks, snapshot_id="snap")
            result, _ = stage.run(
                state,
                issue_dir=issue_dir,
                topic="topic",
                angles=["a1", "a2", "a3"],
                plan_text="plan",
                evidence_ids=["source-1"],
            )
            self.assertEqual(
                (Path(issue_dir) / "三篇初稿" / "初稿-3.md").read_text(encoding="utf-8"),
                "第三篇正文",
            )
            self.assertFalse((Path(issue_dir) / "三篇初稿" / "初稿-1.md").exists())
            self.assertEqual(result.stage, "review_1")

    def test_rate_limit_falls_back_to_glm_first_and_resumes_only_draft3(self):
        writer = FakeModel("qwen3.7-plus", RateLimitError("quota exceeded", status_code=429))
        glm = FakeModel("glm-5.1", "第三篇正文")
        minimax = FakeModel("MiniMax-M3", "不应调用")

        self.run_draft3(writer, [glm, minimax])

        self.assertEqual(glm.requests[0].request_model, "glm-5.1")
        self.assertEqual(glm.requests[0].role, "writer")
        self.assertEqual(minimax.requests, [])

    def test_glm_failure_falls_back_to_minimax(self):
        writer = FakeModel("qwen3.7-plus", RateLimitError("quota exceeded", status_code=429))
        glm = FakeModel("glm-5.1", RateLimitError("still throttled", status_code=429))
        minimax = FakeModel("MiniMax-M3", "第三篇正文")

        self.run_draft3(writer, [glm, minimax])

        self.assertEqual(glm.requests[0].request_model, "glm-5.1")
        self.assertEqual(minimax.requests[0].request_model, "MiniMax-M3")
        self.assertEqual(minimax.requests[0].role, "writer")

    def test_non_rate_limit_primary_error_does_not_switch_models(self):
        writer = FakeModel("qwen3.7-plus", RuntimeError("unexpected"))
        glm = FakeModel("glm-5.1", "不应调用")
        stage = DraftsStage(writer=writer, writer_fallbacks=[glm], snapshot_id="snap")
        with tempfile.TemporaryDirectory() as issue_dir:
            with self.assertRaisesRegex(RuntimeError, "unexpected"):
                stage.run(
                    TaskState(issue_id="issue", stage="draft_3", snapshot_id="snap"),
                    issue_dir=issue_dir,
                    topic="topic",
                    angles=["a1", "a2", "a3"],
                    plan_text="plan",
                    evidence_ids=[],
                )
        self.assertEqual(glm.requests, [])


if __name__ == "__main__":
    unittest.main()
