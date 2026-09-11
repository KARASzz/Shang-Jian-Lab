"""选题候选必须建立在两轮三渠道研究和正文抓取之上。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from 工作台.接口 import TaskState
from 工作台.流水线.research import TopicResearchStage
from 工作台.流水线.topic_selection import TopicSelectionStage
from 测试.流水线._stubs import StubCrawler, StubModel, StubSearch, StubUser, make_search_source


class TopicResearchTests(unittest.TestCase):
    def test_two_rounds_call_search_twice_and_write_research_package(self) -> None:
        sources = [
            make_search_source(1, "tavily"),
            make_search_source(2, "brave"),
            make_search_source(3, "bing"),
        ]
        search = StubSearch(sources=sources)
        crawler = StubCrawler()
        stage = TopicResearchStage(search=search, crawler=crawler)

        with tempfile.TemporaryDirectory() as td:
            state, summary = stage.run(
                TaskState(issue_id="x", stage="topic_research", snapshot_id="s"),
                issue_dir=td,
                column="大模型二三事",
                recent_issues=[],
            )
            self.assertEqual(state.stage, "topic_selection")
            self.assertEqual(len(crawler.calls), 1)
            self.assertIn("## 第 1 轮", summary)
            self.assertIn("## 第 2 轮", summary)
            self.assertTrue((Path(td) / "选题" / "研究" / "第1轮-搜索.json").exists())
            self.assertTrue((Path(td) / "选题" / "研究" / "第2轮-搜索.json").exists())
            self.assertEqual(len(json.loads(
                (Path(td) / "选题" / "研究" / "第1轮-搜索.json").read_text()
            )["sources"]), 3)

    def test_missing_channel_stops_before_crawl(self) -> None:
        search = StubSearch(sources=[make_search_source(1, "brave")])
        crawler = StubCrawler()
        stage = TopicResearchStage(search=search, crawler=crawler)
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(RuntimeError, "未完成三渠道调用"):
                stage.run(
                    TaskState(issue_id="x", stage="topic_research", snapshot_id="s"),
                    issue_dir=td,
                    column="大模型二三事",
                    recent_issues=[],
                )
            self.assertEqual(crawler.calls, [])

    def test_topic_selection_requires_research_and_verified_source_ids(self) -> None:
        planner_text = "\n".join(
            f"{i}. 候选 {i}\n   立意：立意 {i}\n   证据：brave-0-0"
            for i in range(1, 6)
        )
        planner = StubModel(planner_text=planner_text)
        stage = TopicSelectionStage(
            planner=planner,
            user=StubUser(choice=1),
            snapshot_id="s",
            require_research=True,
        )
        with tempfile.TemporaryDirectory() as td:
            research_dir = Path(td) / "选题" / "研究"
            research_dir.mkdir(parents=True)
            for round_no in (1, 2):
                (research_dir / f"第{round_no}轮-搜索.json").write_text(
                    json.dumps({"sources": [{
                        "id": "brave-0-0",
                        "url": "https://example.test/source",
                        "status": "ok",
                    }]}),
                    encoding="utf-8",
                )
            (research_dir / "研究摘要.md").write_text(
                "# 选题研究摘要\n## 第 1 轮\n## 第 2 轮\n",
                encoding="utf-8",
            )
            state, _ = stage.run(
                TaskState(issue_id="x", stage="topic_selection", snapshot_id="s"),
                issue_dir=td,
                column="栏目",
                recent_issues=[],
            )
            self.assertEqual(state.stage, "evidence_collection")
            selected = json.loads((Path(td) / "选题" / "选定.json").read_text(encoding="utf-8"))
            self.assertEqual(selected["topic"].splitlines()[0], "1. 候选 1")

    def test_topic_selection_stops_without_research(self) -> None:
        stage = TopicSelectionStage(
            planner=StubModel(planner_text="1. A\n2. B\n3. C\n4. D\n5. E"),
            user=StubUser(choice=1),
            snapshot_id="s",
            require_research=True,
        )
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(RuntimeError, "缺少两轮选题研究"):
                stage.run(
                    TaskState(issue_id="x", stage="topic_selection", snapshot_id="s"),
                    issue_dir=td,
                    column="栏目",
                    recent_issues=[],
                )


if __name__ == "__main__":
    unittest.main()
