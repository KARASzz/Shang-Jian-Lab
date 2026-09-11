"""菜单 2 在人工处理 / 已结束阶段的提示。"""

from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch

from 工作台.菜单.screens import resume
from 工作台.菜单.tests._harness import TempRepo


class _StubIO:
    def __init__(self) -> None:
        self.out = io.StringIO()

    def println(self, text: str = "") -> None:
        self.out.write(text + "\n")

    def print(self, text: str) -> None:
        self.out.write(text)

    def read_line(self) -> str:
        return ""


class ResumeScreenTests(unittest.TestCase):
    def _write_checkpoint(self, repo: TempRepo, stage: str) -> None:
        issue_root = repo.in_progress() / "2026-09-11-10-19-04-大模型二三事"
        checkpoint = issue_root / "运行记录" / "checkpoint.json"
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_text(
            json.dumps(
                {
                    "issue_id": issue_root.name,
                    "stage": stage,
                    "snapshot_id": "snapshot",
                    "last_checkpoint_at": "2026-09-11T07:37:12+00:00",
                    "rerun_invalidated": ["draft_1"],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def test_awaiting_human_does_not_claim_to_resume(self) -> None:
        with TempRepo() as repo:
            self._write_checkpoint(repo, "awaiting_human")
            output = _StubIO()
            with patch.object(resume, "_notify_orchestrator_resume") as notify:
                resume.run(output)

        notify.assert_not_called()
        text = output.out.getvalue()
        self.assertIn("当前阶段需要人工处理", text)
        self.assertIn("不会继续调用模型", text)
        self.assertNotIn("已续跑本期流水线", text)

    def test_finished_stage_does_not_claim_to_resume(self) -> None:
        for stage in ("finalizing", "archived"):
            with self.subTest(stage=stage), TempRepo() as repo:
                self._write_checkpoint(repo, stage)
                output = _StubIO()
                with patch.object(resume, "_notify_orchestrator_resume") as notify:
                    resume.run(output)

                notify.assert_not_called()
                self.assertIn("当前阶段已结束", output.out.getvalue())


if __name__ == "__main__":
    unittest.main()
