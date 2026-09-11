"""discovery 测试 —— 成功初始化与失败路径。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from 工作台.接入.config import (
    MCPHttpConfig,
    MCPStdioConfig,
    PublicSearchConfig,
    WorkbenchConfig,
)
from 工作台.接入.discovery import discover_all


def _make_config(
    tavily: MCPStdioConfig | None = None,
    brave: MCPHttpConfig | None = None,
    bing: PublicSearchConfig | None = None,
) -> WorkbenchConfig:
    return WorkbenchConfig(
        meta={"schema_version": "1.0"},
        models={},
        tavily=tavily,
        brave=brave,
        bing=bing,
    )


class DiscoveryTests(unittest.TestCase):
    def test_all_channels_return_ok(self) -> None:
        cfg = _make_config(
            tavily=MCPStdioConfig(
                transport="stdio",
                command="npx",
                args=("-y", "@tavily/mcp-server"),
                env_keys={"TAVILY_API_KEY": "TAVILY_API_KEY"},
            ),
            brave=MCPHttpConfig(
                transport="http",
                url="http://localhost:8080/mcp",
                api_key_env="BRAVE_API_KEY",
            ),
            bing=PublicSearchConfig(
                endpoint="https://www.bing.com/search",
                user_agent="test-ua",
                rate_limit_per_minute=20,
            ),
        )
        with patch("工作台.接入.discovery.TavilyMCPClient") as TavilyCls, patch(
            "工作台.接入.discovery.BraveMCPClient"
        ) as BraveCls:
            TavilyCls.return_value.start.return_value = {"status": "ok"}
            TavilyCls.return_value.discover_tools.return_value = ["search"]
            BraveCls.return_value.handshake.return_value = {"status": "ok"}
            BraveCls.return_value.discover_tools.return_value = ["web_search"]
            results = discover_all(cfg)

        self.assertEqual(set(results.keys()), {"tavily", "brave", "bing"})
        for name, r in results.items():
            self.assertEqual(r.status, "ok", name)

    def test_tavily_failure_returns_failed_with_empty_tools(self) -> None:
        cfg = _make_config(
            tavily=MCPStdioConfig(
                transport="stdio",
                command="npx",
                args=("-y", "@tavily/mcp-server"),
                env_keys={},
            ),
        )
        with patch("工作台.接入.discovery.TavilyMCPClient") as TavilyCls:
            TavilyCls.return_value.start.side_effect = RuntimeError("boom")
            results = discover_all(cfg)

        self.assertIn("tavily", results)
        self.assertEqual(results["tavily"].status, "failed")
        self.assertEqual(results["tavily"].tools, [])
        self.assertIn("error", results["tavily"].detail)

    def test_brave_failure_returns_failed_with_empty_tools(self) -> None:
        cfg = _make_config(
            brave=MCPHttpConfig(
                transport="http",
                url="http://localhost:8080/mcp",
                api_key_env=None,
            ),
        )
        with patch("工作台.接入.discovery.BraveMCPClient") as BraveCls:
            BraveCls.return_value.handshake.side_effect = RuntimeError("net down")
            results = discover_all(cfg)

        self.assertEqual(results["brave"].status, "failed")
        self.assertEqual(results["brave"].tools, [])

    def test_missing_channels_are_skipped(self) -> None:
        cfg = _make_config()
        results = discover_all(cfg)
        self.assertEqual(results, {})


if __name__ == "__main__":
    unittest.main()
