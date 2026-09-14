"""选题候选必须建立在两轮三渠道研究和正文抓取之上。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from 工作台.接口 import SearchSource, TaskState
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
            with self.assertRaisesRegex(RuntimeError, "未完成渠道调用"):
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



class _ChannelAwareStubSearch:
    """模拟 CompositeSearch：返回 ok 来源 + 缺失渠道的失败记录，让 _validate_attempts 通过。

    支持按轮次返回不同来源（``round_sources={0: [...], 1: [...]}``），
    或两轮共用 ``ok_sources``（向后兼容旧测试）。
    """

    def __init__(self, ok_sources=None, failed_channels=("tavily", "bing"), round_sources=None) -> None:
        self._failed = list(failed_channels)
        if round_sources is not None:
            self._by_round = {int(k): list(v) for k, v in round_sources.items()}
        else:
            self._by_round = {0: list(ok_sources or []), 1: list(ok_sources or [])}

    def search(self, query, *, round_idx):
        out = []
        for ch in self._failed:
            out.append(SearchSource(
                id=f"{ch}-failed-r{round_idx}", url="",
                title=f"{ch} 搜索未返回可用结果",
                publisher=None, published_at=None, accessed_at="",
                excerpt=query, locator=None, body_path=None,
                status="fetch_failed", channel=ch,
            ))
        out.extend(self._by_round.get(round_idx, []))
        return out

    def fetch(self, source):
        return source


class TopicResearchFloorTests(unittest.TestCase):
    """选题研究必须凑够去重来源下限；不足时整轮停止或自动重跑。"""

    def _write_round(self, issue_dir: Path, round_no: int, urls: list[str]) -> None:
        research_dir = issue_dir / "选题" / "研究"
        research_dir.mkdir(parents=True, exist_ok=True)
        sources = [
            {
                "id": f"brave-0-{i}",
                "url": url,
                "title": f"S{i}",
                "status": "ok",
                "channel": "brave",
            }
            for i, url in enumerate(urls)
        ]
        (research_dir / f"第{round_no}轮-搜索.json").write_text(
            json.dumps({"sources": sources, "round": round_no,
                        "query": "q", "channels_required": ["tavily", "brave", "bing"],
                        "channels_attempted": ["brave"]}),
            encoding="utf-8",
        )

    def test_floor_unmet_triggers_research_refresh_and_still_raises(self) -> None:
        search = _ChannelAwareStubSearch(ok_sources=[make_search_source(1, "brave")])
        crawler = StubCrawler()
        stage = TopicResearchStage(
            search=search, crawler=crawler, min_sources_total=40,
        )
        with tempfile.TemporaryDirectory() as td:
            self._write_round(Path(td), 1, [f"https://example.test/r1/{i}" for i in range(3)])
            self._write_round(Path(td), 2, [f"https://example.test/r2/{i}" for i in range(3)])
            with self.assertRaisesRegex(RuntimeError, "低于要求的 40 个"):
                stage.run(
                    TaskState(issue_id="x", stage="topic_research", snapshot_id="s"),
                    issue_dir=td, column="栏目", recent_issues=[],
                )
            # 来源不足时不会启动抓取；摘要里写明失败原因。
            self.assertEqual(crawler.calls, [])
            summary_text = (Path(td) / "选题" / "研究" / "研究摘要.md").read_text(encoding="utf-8")
            self.assertIn("低于下限 40", summary_text)

    def test_floor_met_lets_stage_pass(self) -> None:
        round1 = [make_search_source(i, "brave") for i in range(1, 3)]
        round2 = [make_search_source(i, "brave") for i in range(3, 5)]
        stage = TopicResearchStage(
            search=_ChannelAwareStubSearch(round_sources={0: round1, 1: round2}),
            crawler=StubCrawler(),
            min_sources_total=4,
        )
        with tempfile.TemporaryDirectory() as td:
            state, summary = stage.run(
                TaskState(issue_id="x", stage="topic_research", snapshot_id="s"),
                issue_dir=td, column="栏目", recent_issues=[],
            )
            self.assertEqual(state.stage, "topic_selection")
            self.assertIn("## 第 1 轮", summary)

    def test_meets_source_floor_counts_unique_urls_only(self) -> None:
        stage = TopicResearchStage(
            search=StubSearch(), crawler=StubCrawler(), min_sources_total=3,
        )
        with tempfile.TemporaryDirectory() as td:
            self._write_round(Path(td), 1, [
                "https://a.test/x", "https://a.test/x", "https://b.test/y",
            ])
            self._write_round(Path(td), 2, ["https://c.test/z"])
            self.assertEqual(stage.count_retrieved_sources(td), 3)
            self.assertTrue(stage.meets_source_floor(td))


class ResearchSummaryRedactionTests(unittest.TestCase):
    """研究摘要不得向 planner 暴露抓取失败来源的编号。"""

    def test_failed_sources_have_no_citable_id_in_summary(self) -> None:
        payloads = [{
            "round": 1,
            "query": "q",
            "sources": [
                {"id": "brave-0-0", "channel": "brave", "status": "ok",
                 "title": "好来源", "url": "https://a.test/1", "excerpt": "正文"},
                {"id": "brave-0-9", "channel": "brave", "status": "fetch_failed",
                 "title": "坏来源", "url": "https://a.test/2", "excerpt": ""},
            ],
        }]
        summary = TopicResearchStage._summary(payloads)
        self.assertIn("brave-0-0", summary)
        self.assertNotIn("brave-0-9", summary)
        self.assertIn("不可引用", summary)


class TopicSelectionRetryTests(unittest.TestCase):
    """planner 引用未验证的证据 ID 时，阶段应自动纠错重试而非直接崩溃。"""

    def test_bad_then_good_candidates_succeed_via_retry(self) -> None:
        from 工作台.接口 import ModelRequest, ModelResponse

        good = "\n".join(
            f"{i}. 候选 {i}\n   立意：立意 {i}\n   证据：brave-0-0"
            for i in range(1, 6)
        )
        bad = "\n".join(
            f"{i}. 候选 {i}\n   立意：立意 {i}\n   证据：brave-0-999"
            for i in range(1, 6)
        )

        class TwoShotStub:
            def __init__(self, texts: list[str]) -> None:
                self._texts = list(texts)
                self.calls = 0

            def chat(self, req: ModelRequest) -> ModelResponse:
                text = self._texts.pop(0) if self._texts else good
                self.calls += 1
                return ModelResponse(
                    text=text, request_model=req.request_model,
                    served_model=req.request_model,
                    usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                )

        stage = TopicSelectionStage(
            planner=TwoShotStub([bad, good]),
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
                        "id": "brave-0-0", "url": "https://example.test/a", "status": "ok",
                    }]}),
                    encoding="utf-8",
                )
            (research_dir / "研究摘要.md").write_text(
                "# 选题研究摘要\n## 第 1 轮\n## 第 2 轮\n", encoding="utf-8",
            )
            state, _ = stage.run(
                TaskState(issue_id="x", stage="topic_selection", snapshot_id="s"),
                issue_dir=td, column="栏目", recent_issues=[],
            )
            self.assertEqual(state.stage, "evidence_collection")
            self.assertEqual(stage.planner.calls, 2)

    def test_persistent_invalid_citations_raise_after_retries_exhausted(self) -> None:
        bad = "\n".join(
            f"{i}. 候选 {i}\n   立意：立意 {i}\n   证据：brave-0-999"
            for i in range(1, 6)
        )
        from 工作台.接口 import ModelRequest, ModelResponse

        class AlwaysBadStub:
            def __init__(self, text: str) -> None:
                self._text = text
                self.calls = 0

            def chat(self, req: ModelRequest) -> ModelResponse:
                self.calls += 1
                return ModelResponse(
                    text=self._text, request_model=req.request_model,
                    served_model=req.request_model,
                    usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                )

        stage = TopicSelectionStage(
            planner=AlwaysBadStub(bad),
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
                        "id": "brave-0-0", "url": "https://example.test/a", "status": "ok",
                    }]}),
                    encoding="utf-8",
                )
            (research_dir / "研究摘要.md").write_text(
                "# 选题研究摘要\n## 第 1 轮\n## 第 2 轮\n", encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "未验证的证据 ID"):
                stage.run(
                    TaskState(issue_id="x", stage="topic_selection", snapshot_id="s"),
                    issue_dir=td, column="栏目", recent_issues=[],
                )
            self.assertEqual(stage.planner.calls, 3)
