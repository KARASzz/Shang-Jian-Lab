"""去 AI 味润色单测：保留标题+证据编号+你语气，温度 0.85，一次性完成。"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from 工作台.接口 import ModelRequest, ModelResponse, TaskState
from 工作台.流水线.deai import DeaiStage
from 测试.流水线._stubs import StubModel


_ORIG_DRAFT = (
    "# AI 风险治理与审计：从标准走向落地\n\n"
    "在当前这个时代，AI 治理已经成为 [S1] 各方关注的核心议题。"
    "值得注意的是，[S2] 我们需要系统性的方法论。"
    "综上所述，企业应当建立完整的风险管理体系。"
    "你如果想深入理解，可以参考 ISO/IEC 42001 的要求 [S3]。"
)


class DeaiStageTests(unittest.TestCase):
    def test_writes_recommendation_md_and_advances_to_finalizing(self):
        writer = StubModel(writer_text=_ORIG_DRAFT)
        stage = DeaiStage(writer=writer, snapshot_id="snap")
        with tempfile.TemporaryDirectory() as td:
            state = TaskState(issue_id="x", stage="deai", snapshot_id="snap")
            state, text = stage.run(
                state, issue_dir=td, draft_text=_ORIG_DRAFT,
            )
            pending = Path(td) / "待定稿" / "推荐稿.md"
            self.assertTrue(pending.exists())
            self.assertEqual(pending.read_text(encoding="utf-8"), text)
            # deai 内部 commit_stage(event="finalizing")
            self.assertEqual(state.stage, "finalizing")

    def test_preserves_title_verbatim(self):
        writer = StubModel(writer_text=_ORIG_DRAFT)
        stage = DeaiStage(writer=writer, snapshot_id="snap")
        with tempfile.TemporaryDirectory() as td:
            state = TaskState(issue_id="x", stage="deai", snapshot_id="snap")
            state, text = stage.run(
                state, issue_dir=td, draft_text=_ORIG_DRAFT,
            )
            first_line = text.splitlines()[0]
            orig_title = _ORIG_DRAFT.splitlines()[0]
            self.assertEqual(first_line, orig_title)

    def test_preserves_evidence_ids_count_and_order(self):
        writer = StubModel(writer_text=_ORIG_DRAFT)
        stage = DeaiStage(writer=writer, snapshot_id="snap")
        with tempfile.TemporaryDirectory() as td:
            state = TaskState(issue_id="x", stage="deai", snapshot_id="snap")
            state, text = stage.run(
                state, issue_dir=td, draft_text=_ORIG_DRAFT,
            )
            ids = re.findall(r"\[S\d+\]", text)
            self.assertEqual(ids, ["[S1]", "[S2]", "[S3]"])

    def test_preserves_you_voice(self):
        writer = StubModel(writer_text=_ORIG_DRAFT)
        stage = DeaiStage(writer=writer, snapshot_id="snap")
        with tempfile.TemporaryDirectory() as td:
            state = TaskState(issue_id="x", stage="deai", snapshot_id="snap")
            state, text = stage.run(
                state, issue_dir=td, draft_text=_ORIG_DRAFT,
            )
            self.assertIn("你", text)

    def test_temperature_propagated_to_model_request(self):
        captured: dict = {}
        writer = StubModel(writer_text=_ORIG_DRAFT)
        orig_chat = writer.chat

        def chat_capture(req: ModelRequest) -> ModelResponse:
            captured["temperature"] = req.temperature
            return orig_chat(req)

        writer.chat = chat_capture  # type: ignore[method-assign]
        stage = DeaiStage(writer=writer, snapshot_id="snap", temperature=0.85)
        with tempfile.TemporaryDirectory() as td:
            state = TaskState(issue_id="x", stage="deai", snapshot_id="snap")
            stage.run(state, issue_dir=td, draft_text=_ORIG_DRAFT)
        self.assertEqual(captured.get("temperature"), 0.85)

    def test_invalid_temperature_rejected(self):
        with self.assertRaises(ValueError):
            DeaiStage(writer=StubModel(), snapshot_id="snap", temperature=2.5)

    def test_writer_failure_raises(self):
        class _FailingModel:
            config = None

            def chat(self, req: ModelRequest) -> ModelResponse:
                return ModelResponse(
                    text="", request_model="qwen3.7-plus",
                    served_model="qwen3.7-plus",
                    raw_error="deai 上游 503",
                )

        stage = DeaiStage(writer=_FailingModel(), snapshot_id="snap")
        with tempfile.TemporaryDirectory() as td:
            state = TaskState(issue_id="x", stage="deai", snapshot_id="snap")
            with self.assertRaisesRegex(RuntimeError, "deai 改写失败"):
                stage.run(state, issue_dir=td, draft_text=_ORIG_DRAFT)


if __name__ == "__main__":
    unittest.main()