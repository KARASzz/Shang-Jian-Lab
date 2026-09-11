"""没有有效检索来源时，证据阶段必须停住。"""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
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


class _Search:
    def search(self, query: str, *, round_idx: int) -> list[SearchSource]:
        return [SearchSource(
            id=f"source-{round_idx}", url=f"https://example.test/{round_idx}",
            title="来源", publisher="example", published_at=None,
            accessed_at="2026-09-11", excerpt="搜索摘要", locator=None,
            body_path=None, status="ok", channel="brave",
        )]

    def fetch(self, source: SearchSource) -> SearchSource:
        return source


class _Crawler:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str]] = []

    def crawl(self, sources: list[SearchSource], *, output_dir: str) -> list[SearchSource]:
        self.calls.append(([source.id for source in sources], output_dir))
        body_dir = Path(output_dir) / "正文"
        body_dir.mkdir(parents=True, exist_ok=True)
        out = []
        for source in sources:
            body = body_dir / f"{source.id}.txt"
            body.write_text("正文证据", encoding="utf-8")
            out.append(replace(source, excerpt="正文证据", body_path=str(body)))
        return out


class EvidenceGateTests(unittest.TestCase):
    def test_all_failed_searches_stop_before_checkpoint(self) -> None:
        stage = EvidenceCollectionStage(search=_FailedSearch(), rounds_max=2)
        state = TaskState(issue_id="x", stage="evidence_collection", snapshot_id="s")
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(RuntimeError, "有效资料"):
                stage.run(state, issue_dir=td, topic="benchmark", anchor_reports=[])
            self.assertFalse((Path(td) / "运行记录" / "checkpoint.json").exists())

    def test_crawler_is_required_and_body_is_recorded(self) -> None:
        crawler = _Crawler()
        stage = EvidenceCollectionStage(
            search=_Search(), crawler=crawler, require_crawl=True, rounds_max=2,
        )
        state = TaskState(issue_id="x", stage="evidence_collection", snapshot_id="s")
        with tempfile.TemporaryDirectory() as td:
            new_state, sources = stage.run(
                state, issue_dir=td, topic="benchmark", anchor_reports=[],
            )
            self.assertEqual(new_state.stage, "planning")
            self.assertEqual(len(crawler.calls), 1)
            self.assertEqual(len(sources), 2)
            payload = json.loads(
                (Path(td) / "资料" / "证据清单.json").read_text(encoding="utf-8")
            )
            self.assertTrue(all(item["body_path"] for item in payload["sources"]))


if __name__ == "__main__":
    unittest.main()
