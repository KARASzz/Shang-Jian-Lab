"""Brave MCP HTTP 客户端的真实握手、工具调用和结果归一化。"""

from __future__ import annotations

import json
import os
import urllib.error
import unittest
from unittest.mock import MagicMock

from 工作台.接入.config import MCPHttpConfig
from 工作台.接入.search.brave_mcp import BraveMCPClient


class _Response:
    def __init__(self, body: object, headers: dict[str, str] | None = None) -> None:
        self._body = json.dumps(body).encode("utf-8")
        self.headers = headers or {}
        self.status = 200

    def read(self) -> bytes:
        return self._body

    def close(self) -> None:
        return None


class BraveMCPTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["TEST_BRAVE_KEY"] = "brave-secret"

    def tearDown(self) -> None:
        os.environ.pop("TEST_BRAVE_KEY", None)

    def test_handshake_discover_and_search_use_bearer_without_logging_key(self) -> None:
        opener = MagicMock()
        opener.open.side_effect = [
            _Response(
                {"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "brave"}}},
                {"Mcp-Session-Id": "session-1"},
            ),
            _Response({}, {"Mcp-Session-Id": "session-1"}),
            _Response(
                {"jsonrpc": "2.0", "id": 2, "result": {"tools": [{"name": "brave_web_search"}]}},
                {"Mcp-Session-Id": "session-1"},
            ),
            _Response(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps({
                            "web": {"results": [{
                                "title": "评测结果",
                                "url": "https://example.test/result",
                                "description": "一条可核验结果",
                            }]}
                        }, ensure_ascii=False)}]
                    },
                },
                {"Mcp-Session-Id": "session-1"},
            ),
        ]
        client = BraveMCPClient(
            MCPHttpConfig("http", "http://localhost:8080/mcp", "TEST_BRAVE_KEY"),
            http_opener=lambda: opener,
        )

        self.assertEqual(client.handshake()["status"], "ok")
        self.assertEqual(client.discover_tools(), ["brave_web_search"])
        results = client.search("benchmark", round_idx=0)

        self.assertEqual(results[0].status, "ok")
        self.assertEqual(results[0].url, "https://example.test/result")
        self.assertEqual(opener.open.call_count, 4)
        for call in opener.open.call_args_list:
            request = call.args[0]
            self.assertEqual(request.get_header("Authorization"), "Bearer brave-secret")
            self.assertNotIn("brave-secret", request.data.decode("utf-8"))

    def test_mcp_error_is_explicit_and_does_not_return_fake_source(self) -> None:
        opener = MagicMock()
        opener.open.return_value = _Response({
            "jsonrpc": "2.0", "id": 1,
            "error": {"code": -32000, "message": "unauthorized"},
        })
        client = BraveMCPClient(
            MCPHttpConfig("http", "http://localhost:8080/mcp", "TEST_BRAVE_KEY"),
            http_opener=lambda: opener,
            enable_direct_fallback=False,
        )
        with self.assertRaisesRegex(RuntimeError, "unauthorized"):
            client.search("benchmark")

    def test_unavailable_mcp_uses_direct_brave_api(self) -> None:
        opener = MagicMock()
        direct = _Response({"web": {"results": [{
            "title": "直连结果", "url": "https://example.test/direct", "description": "正文"
        }]}})
        opener.open.side_effect = [urllib.error.URLError("connection refused"), direct]
        client = BraveMCPClient(
            MCPHttpConfig("http", "http://localhost:8080/mcp", "TEST_BRAVE_KEY"),
            http_opener=lambda: opener,
        )
        results = client.search("benchmark")
        self.assertEqual(results[0].url, "https://example.test/direct")
        request = opener.open.call_args_list[1].args[0]
        self.assertEqual(request.get_header("X-subscription-token"), "brave-secret")


if __name__ == "__main__":
    unittest.main()
