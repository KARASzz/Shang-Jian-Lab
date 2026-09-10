"""阶段推进、上游重跑下游失效、混用版本拒绝。"""

from __future__ import annotations

import unittest

from 工作台.接口 import TaskState
from 工作台.流水线.checkpoint import (
    VersionMixingError,
    verify_versions,
    record_version,
)
from 工作台.流水线.state import (
    AWAIT_HUMAN,
    FINALIZING,
    RERUN_DOWNSTREAM,
    STAGE_ORDER,
    advance,
    rerun,
)


def _ts() -> TaskState:
    return TaskState(issue_id="2026-09-10-00-00-00-大模型二三事",
                     stage="topic_selection",
                     snapshot_id="snap-1")


class StageAdvanceTests(unittest.TestCase):
    def test_advance_normal_sequence(self):
        s = _ts()
        for expected in STAGE_ORDER[1:]:
            s = advance(s)
            self.assertEqual(s.stage, expected)
        self.assertEqual(s.stage, STAGE_ORDER[-1])

    def test_advance_event_await_human(self):
        s = _ts()
        s = advance(s, event="await_human")
        self.assertEqual(s.stage, AWAIT_HUMAN)

    def test_advance_event_finalizing(self):
        s = _ts()
        s = advance(s, event="finalizing")
        self.assertEqual(s.stage, FINALIZING)

    def test_advance_keeps_terminal(self):
        s = _ts()
        s = advance(s, event="finalizing")
        s2 = advance(s)
        self.assertEqual(s2.stage, FINALIZING)


class RerunTests(unittest.TestCase):
    def test_rerun_topic_marks_all_downstream(self):
        s = _ts()
        s = rerun(s, "topic_selection")
        self.assertEqual(s.stage, "topic_selection")
        self.assertEqual(
            set(s.rerun_invalidated),
            set(RERUN_DOWNSTREAM["topic_selection"]),
        )

    def test_rerun_review_1_only_invalidates_review_revise(self):
        s = _ts()
        s = rerun(s, "review_1")
        self.assertEqual(
            set(s.rerun_invalidated),
            {"review_1", "revise_1", "review_2", "revise_2"},
        )

    def test_rerun_invalid_target_raises(self):
        s = _ts()
        with self.assertRaises(ValueError):
            rerun(s, "archived")


class VersionMixingTests(unittest.TestCase):
    def test_verify_versions_match_passes(self):
        s = _ts()
        s = record_version(s, "draft_1", "hello")
        # 内容不变 → 不抛
        verify_versions(s, {"draft_1": "hello"})

    def test_verify_versions_mismatch_raises(self):
        s = _ts()
        s = record_version(s, "draft_1", "hello")
        with self.assertRaises(VersionMixingError):
            verify_versions(s, {"draft_1": "world"})

    def test_verify_versions_missing_ok(self):
        s = _ts()
        s = record_version(s, "draft_1", "hello")
        # 缺失视为未变更
        verify_versions(s, {})


if __name__ == "__main__":
    unittest.main()
