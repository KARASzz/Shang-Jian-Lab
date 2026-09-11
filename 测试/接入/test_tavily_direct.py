"""Tavily 必须真实调用 HTTP API，不得返回假来源。"""

from __future__ import annotations

import json
import os
import unittest
import urllib.error
from unittest.mock import MagicMock

from 工作台.接入.config import MCPStdioConfig
from 工作台.接入.search.tavily_mcp import TavilyMCPClient


class _Response:
    headers: dict[str, str] = {}

    def __init__(self, body: object) -> None:
        self.body = json.dumps(body).encode("utf-8")

    def read(self) -> bytes:
        return self.body

    def close(self) -> None:
        return None


class TavilyDirectTests(unittest.TestCase):
    def test_search_uses_configured_key_and_returns_real_results(self) -> None:
        os.environ["TEST_TAVILY_KEY"] = "tavily-secret"
        opener = MagicMock()
        opener.open.return_value = _Response({
            "results": [{"title": "结果", "url": "https://example.test", "content": "正文"}]
        })
        client = TavilyMCPClient(
            MCPStdioConfig("stdio", "unused", (), {"TAVILY_API_KEY": "TEST_TAVILY_KEY"}),
            http_opener=lambda: opener,
        )
        results = client.search("benchmark")
        self.assertEqual(results[0].status, "ok")
        request = opener.open.call_args.args[0]
        self.assertNotIn("tavily-secret", request.headers.get("Content-Type", ""))
        self.assertEqual(json.loads(request.data)["api_key"], "tavily-secret")
        self.assertEqual(request.full_url, "https://api.tavily.com/search")
        os.environ.pop("TEST_TAVILY_KEY", None)

    def test_quota_error_disables_tavily_for_later_rounds(self) -> None:
        os.environ["TEST_TAVILY_KEY"] = "tavily-secret"
        opener = MagicMock()
        opener.open.side_effect = urllib.error.HTTPError(
            "https://api.tavily.com/search", 432, "Quota", {}, None
        )
        client = TavilyMCPClient(
            MCPStdioConfig("stdio", "unused", (), {"TAVILY_API_KEY": "TEST_TAVILY_KEY"}),
            http_opener=lambda: opener,
        )
        self.assertEqual(client.search("one"), [])
        self.assertEqual(client.search("two"), [])
        self.assertEqual(opener.open.call_count, 1)
        os.environ.pop("TEST_TAVILY_KEY", None)


if __name__ == "__main__":
    unittest.main()
