"""搜索客户端必须实现 SearchClient Protocol：round_idx / fetch / 失败显式 status。"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from 工作台.接入.config import PublicSearchConfig
from 工作台.接入.search.bing_public import BingPublicSearch
from 工作台.接口 import SearchSource


def _bing() -> BingPublicSearch:
    response = MagicMock()
    response.read.return_value = b'<li class="b_algo"><h2><a href="https://example.test">Example</a></h2><p>Excerpt</p></li>'
    response.close.return_value = None
    opener = MagicMock()
    opener.open.return_value = response
    return BingPublicSearch(
        PublicSearchConfig(
            endpoint="https://www.bing.com/search",
            user_agent="test-ua",
            rate_limit_per_minute=20,
        ),
        sleeper=lambda _s: None,
        clock=lambda: 0.0,
        http_opener=lambda: opener,
    )


class BingProtocolTests(unittest.TestCase):
    def test_search_accepts_round_idx(self) -> None:
        results = _bing().search("判断力", round_idx=0)
        self.assertIsInstance(results, list)

    def test_real_search_returns_ok_source(self) -> None:
        results = _bing().search("判断力", round_idx=1)
        self.assertGreaterEqual(len(results), 1)
        self.assertTrue(all(s.status == "ok" for s in results))

    def test_fetch_returns_source(self) -> None:
        src = SearchSource(
            id="bing-1",
            url="https://example.com",
            title="t",
            publisher=None,
            published_at=None,
            accessed_at="2026-09-10",
            excerpt="",
            locator=None,
            body_path=None,
            status="ok",
            channel="bing",
        )
        out = _bing().fetch(src)
        self.assertEqual(out.id, src.id)
        self.assertEqual(out.url, src.url)
