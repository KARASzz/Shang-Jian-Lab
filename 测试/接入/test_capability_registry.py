"""受限 MCP 能力注册表的别名、冻结边界与失败缓存。"""
import unittest

from 工作台.接入.search.capability_registry import CapabilityRegistry
from 工作台.接入.search.local_mcp import LocalMCPError


class FakeClient:
    def __init__(self, servers=None, fail=()):
        self.servers = servers or {}
        self.fail = set(fail)
        self.calls = []

    def configured_servers(self):
        return self.servers

    def discover(self, server):
        self.calls.append(server)
        if server in self.fail:
            raise LocalMCPError("MCP 服务调用失败", category="network")
        return [{"name": f"{server}_search", "inputSchema": {"type": "object"}}]


class CapabilityRegistryTests(unittest.TestCase):
    def test_resolves_only_enabled_local_aliases_without_scanning_other_servers(self):
        client = FakeClient({
            "firecrawl-mcp": {"enabled": True, "transport": "stdio"},
            "tavily-search": {"enabled": True, "transport": "stdio"},
            "brave-search": {"enabled": True, "transport": "stdio"},
            "playwright-MCP": {"enabled": True, "transport": "stdio"},
            "context7": {"enabled": True, "transport": "stdio"},
            "unrelated": {"enabled": True, "transport": "stdio"},
            "node_repl": {"enabled": True, "transport": "stdio"},
        })
        registry = CapabilityRegistry(client)
        self.assertEqual(registry.server("firecrawl"), "firecrawl-mcp")
        self.assertEqual(registry.server("tavily"), "tavily-search")
        self.assertEqual(registry.server("brave"), "brave-search")
        self.assertEqual(registry.server("playwright"), "playwright-MCP")
        self.assertEqual(registry.server("context7"), "context7")
        self.assertEqual(client.calls, [])

    def test_omnisearch_is_frozen_even_if_locally_configured(self):
        client = FakeClient({"mcp-omnisearch": {"enabled": True, "transport": "stdio"}})
        registry = CapabilityRegistry(client)
        with self.assertRaises(LocalMCPError) as caught:
            registry.server("omnisearch")
        self.assertEqual(caught.exception.category, "configuration")
        self.assertEqual(client.calls, [])

    def test_disabled_alias_is_not_selected_and_failure_is_cached(self):
        client = FakeClient({
            "firecrawl-mcp": {"enabled": False, "transport": "stdio"},
            "firecrawl-stdio": {"enabled": True, "transport": "stdio"},
        }, fail={"firecrawl-stdio"})
        registry = CapabilityRegistry(client)
        with self.assertRaises(LocalMCPError):
            registry.tools("firecrawl")
        with self.assertRaises(LocalMCPError):
            registry.tools("firecrawl")
        self.assertEqual(client.calls, ["firecrawl-stdio"])

    def test_explicit_alias_override_wins_and_unknown_channels_are_rejected(self):
        client = FakeClient({
            "firecrawl-mcp": {"enabled": True, "transport": "stdio"},
            "custom-search": {"enabled": True, "transport": "http"},
        })
        registry = CapabilityRegistry(client, overrides={"firecrawl": "custom-search"})
        self.assertEqual(registry.server("firecrawl"), "custom-search")
        with self.assertRaises(LocalMCPError):
            CapabilityRegistry(client, overrides={"omnisearch": "mcp-omnisearch"})
        with self.assertRaises(LocalMCPError):
            registry.server("node_repl")

    def test_tools_are_discovered_once_and_cached(self):
        client = FakeClient({"firecrawl-mcp": {"enabled": True, "transport": "stdio"}})
        registry = CapabilityRegistry(client)
        self.assertEqual(registry.tools("firecrawl"), registry.tools("firecrawl"))
        self.assertEqual(client.calls, ["firecrawl-mcp"])


if __name__ == "__main__":
    unittest.main()
