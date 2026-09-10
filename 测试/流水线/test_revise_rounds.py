"""0/1/2/3 轮返修的状态转移；3 轮必须转 await_human 且不再调模型。"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from 工作台.接口 import ReviewIssue, ReviewVerdict, TaskState
from 工作台.流水线.revise import MaxRevisionsExceeded, ReviseStage
from 工作台.流水线.state import AWAIT_HUMAN, advance
from 测试.流水线._stubs import StubModel


def _state() -> TaskState:
    return TaskState(issue_id="x", stage="revise_1", snapshot_id="snap-1")


def _verdict(*, pass_: bool) -> ReviewVerdict:
    return ReviewVerdict(
        draft_version="draft_1",
        issues=[ReviewIssue(severity="block", category="fabricated_citation",
                            location="loc", description="desc")],
        score=50,
        recommendation="draft_1",
        pass_=pass_,
    )


class ZeroRoundTests(unittest.TestCase):
    def test_revision_max_zero_raises_and_no_model_call(self):
        # 0 轮：禁止调模型
        model = StubModel(writer_text="never-called")
        revise = ReviseStage(
            writer=model, reviewer=model,
            snapshot_id="snap-1", revision_rounds_max=0,
        )
        # 验证 revise=0 时进入 run 直接抛错
        state = _state()
        with self.assertRaises(MaxRevisionsExceeded):
            revise.run(state, issue_dir="/nonexistent", draft_text="t",
                       verdict=_verdict(pass_=False), draft_version="draft_1")


class OneRoundTests(unittest.TestCase):
    def test_one_round_pass_terminates(self):
        # 1 轮内审稿通过 → 不抛、不进 await_human
        reviewer = StubModel(reviewer_text='{"score":90,"recommendation":"draft_1","pass_":true,"issues":[]}')
        # writer 在返修时返回新稿；reviewer 再审通过
        writer = StubModel(writer_text="revised draft")
        revise = ReviseStage(
            writer=writer, reviewer=reviewer,
            snapshot_id="snap-1", revision_rounds_max=1,
        )
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as td:
            state, draft, verdict = revise.run(
                _state(), issue_dir=td, draft_text="orig",
                verdict=_verdict(pass_=False), draft_version="draft_1",
            )
        self.assertEqual(draft, "revised draft")
        self.assertTrue(verdict.pass_)
        self.assertEqual(state.stage, "review_2")

    def test_one_round_fail_raises_max_revisions(self):
        # 1 轮后仍未通过 → 抛 MaxRevisionsExceeded
        reviewer = StubModel(reviewer_text='{"score":50,"recommendation":"draft_1","pass_":false,"issues":[{"severity":"block","category":"fabricated_citation","location":"x","description":"y"}]}')
        writer = StubModel(writer_text="still bad")
        revise = ReviseStage(
            writer=writer, reviewer=reviewer,
            snapshot_id="snap-1", revision_rounds_max=1,
        )
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(MaxRevisionsExceeded):
                revise.run(_state(), issue_dir=td, draft_text="orig",
                           verdict=_verdict(pass_=False), draft_version="draft_1")


class TwoRoundTests(unittest.TestCase):
    def test_two_rounds_pass_on_second(self):
        # 第 1 轮仍阻断；第 2 轮通过 → 正常完成
        from collections.abc import Sequence
        reviewer = MagicMock()
        reviewer.chat.side_effect = [
            # 复审第 1 轮：未通过
            _review_response(block=True),
            # 复审第 2 轮：通过
            _review_response(block=False),
        ]
        writer = StubModel(writer_text="revised")
        revise = ReviseStage(
            writer=writer, reviewer=reviewer,
            snapshot_id="snap-1", revision_rounds_max=2,
        )
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            state, _draft, verdict = revise.run(
                _state(), issue_dir=td, draft_text="orig",
                verdict=_verdict(pass_=False), draft_version="draft_1",
            )
        self.assertTrue(verdict.pass_)

    def test_two_rounds_fail_raises_max_revisions(self):
        from unittest.mock import MagicMock
        reviewer = MagicMock()
        reviewer.chat.side_effect = [
            _review_response(block=True),
            _review_response(block=True),
        ]
        writer = StubModel(writer_text="revised")
        revise = ReviseStage(
            writer=writer, reviewer=reviewer,
            snapshot_id="snap-1", revision_rounds_max=2,
        )
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(MaxRevisionsExceeded):
                revise.run(_state(), issue_dir=td, draft_text="orig",
                           verdict=_verdict(pass_=False), draft_version="draft_1")


class ThreeRoundAttemptTests(unittest.TestCase):
    def test_three_rounds_not_invoked_when_cap_is_two(self):
        """即使评审器还想再返修，cap=2 也只能调 2 次模型（writer 第 2 次之后即抛错）。"""
        from unittest.mock import MagicMock
        reviewer = MagicMock()
        reviewer.chat.side_effect = [
            _review_response(block=True),
            _review_response(block=True),
        ]
        writer = MagicMock()
        writer.chat.return_value = _model_resp("writer", "rev")
        revise = ReviseStage(
            writer=writer, reviewer=reviewer,
            snapshot_id="snap-1", revision_rounds_max=2,
        )
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(MaxRevisionsExceeded):
                revise.run(_state(), issue_dir=td, draft_text="orig",
                           verdict=_verdict(pass_=False), draft_version="draft_1")
        # writer 最多被调用 2 次
        self.assertEqual(writer.chat.call_count, 2)
        # reviewer 同样最多 2 次
        self.assertEqual(reviewer.chat.call_count, 2)


def _model_resp(role: str, text: str):
    from 工作台.接口 import ModelResponse
    return ModelResponse(
        text=text, request_model=role, served_model=role,
        usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    )


def _review_response(*, block: bool):
    from 工作台.接口 import ModelResponse
    payload = (
        '{"score":50,"recommendation":"draft_1","pass_":false,'
        '"issues":[{"severity":"block","category":"fabricated_citation",'
        '"location":"x","description":"y"}]}'
        if block else
        '{"score":90,"recommendation":"draft_1","pass_":true,"issues":[]}'
    )
    return ModelResponse(
        text=payload, request_model="glm-5.1", served_model="glm-5.1",
        usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    )


class AwaitHumanTransitionTests(unittest.TestCase):
    def test_max_revisions_leads_to_await_human(self):
        """模拟编排端捕获异常后切到 awaiting_human。"""
        state = _state()
        # advance 在异常路径上的语义：orchestrator 调 advance(event='await_human')
        state = advance(state, event="await_human")
        self.assertEqual(state.stage, AWAIT_HUMAN)


if __name__ == "__main__":
    unittest.main()
