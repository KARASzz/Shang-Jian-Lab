"""没有有效检索来源时，证据阶段必须停住。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from 工作台.接口 import SearchSource, TaskState
from 工作台.流水线.evidence import EvidenceCollectionStage


class _FailedSearch:
    def search(self, query: str, *, round_idx: int) -> list[SearchSource]:
        return [SearchSource(
            id=f"failed-{round_idx}", url="", title="搜索失败", publisher=None,
            published_at=None, accessed_at="", excerpt=query, locator=None,
            body_path=None, status="fetch_failed", channel="brave",
        )]

    def fetch(self, source: SearchSource) -> SearchSource:
        return source


class EvidenceGateTests(unittest.TestCase):
    def test_all_failed_searches_stop_before_checkpoint(self) -> None:
        stage = EvidenceCollectionStage(search=_FailedSearch(), rounds_max=2)
        state = TaskState(issue_id="x", stage="evidence_collection", snapshot_id="s")
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(RuntimeError, "有效资料"):
                stage.run(state, issue_dir=td, topic="benchmark", anchor_reports=[])
            self.assertFalse((Path(td) / "运行记录" / "checkpoint.json").exists())


if __name__ == "__main__":
    unittest.main()
