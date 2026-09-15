"""五 MCP 调度：路由、真实失败、正文落盘及来源追溯。"""
import json
import tempfile
import unittest
from pathlib import Path

from 工作台.接口 import SearchSource
from 工作台.接入.search.research_agent import ResearchDispatchAgent, SERVERS, body_text, unpack


class FakeMCP:
    def __init__(self, fail=()):
        self.calls = []
        self.fail = set(fail)

    def discover(self, server):
        names = {
            "brave-search": ["brave_web_search"],
            "tavily": ["tavily_search", "tavily_extract"],
            "mcp-omnisearch": ["web_search", "web_extract"],
            "firecrawl-stdio": ["firecrawl_search", "firecrawl_scrape"],
            "playwright": ["browser_navigate"],
        }[server]
        return [{"name": n} for n in names]

    def call(self, server, tool, args):
        self.calls.append((server, tool, args))
        if server in self.fail:
            raise RuntimeError("SECRET_TOKEN_MUST_NOT_LEAK")
        if "search" in tool:
            return {"structuredContent": {"results": [
                {"title": "Report", "url": f"https://example.org/{server}", "content": "search snippet"}
            ]}}
        if tool == "browser_navigate":
            return {"content": [{"type": "text", "text": "### Snapshot\n- article:\n  - paragraph: Browser evidence"}]}
        return {"structuredContent": {"data": {"markdown": "Extracted evidence with context."}}}


class ResearchAgentTests(unittest.TestCase):
    def test_search_and_crawl_use_all_five_and_preserve_provenance(self):
        client = FakeMCP()
        agent = ResearchDispatchAgent(client=client)
        with tempfile.TemporaryDirectory() as td:
            agent.set_output_dir(td)
            sources = agent.search("AI reports", round_idx=0)
            results = agent.crawl(sources, output_dir=td)
            self.assertEqual({x.channel for x in sources}, agent.expected_channels())
            self.assertEqual({x[0] for x in client.calls}, set(SERVERS.values()))
            self.assertTrue(all(x.status == "ok" and Path(x.body_path).is_file() for x in results))
            self.assertEqual([x.channel for x in results], [x.channel for x in sources])
            self.assertTrue(all(x.locator.startswith("MCP:") for x in results))
            self.assertNotIn("node_repl", str(client.calls))
            self.assertTrue((Path(td) / "MCP调度记录.jsonl").is_file())

    def test_channel_failure_is_retained_and_redacted(self):
        client = FakeMCP(fail={"brave-search"})
        agent = ResearchDispatchAgent(client=client)
        with tempfile.TemporaryDirectory() as td:
            agent.set_output_dir(td)
            results = agent.search("test", round_idx=1)
            self.assertEqual(next(x for x in results if x.channel == "brave").status, "fetch_failed")
            self.assertEqual(len(results), 4)
            self.assertNotIn("SECRET", (Path(td) / "MCP调度记录.jsonl").read_text(encoding="utf-8"))

    def test_crawl_failure_never_promotes_snippet_to_body(self):
        agent = ResearchDispatchAgent(client=FakeMCP(fail=set(SERVERS.values())))
        with tempfile.TemporaryDirectory() as td:
            source = SearchSource(id="s", url="https://example.org", title="title", excerpt="snippet")
            result = agent.crawl([source], output_dir=td)[0]
            self.assertEqual(result.status, "fetch_failed")
            self.assertIsNone(result.body_path)
            self.assertEqual(result.excerpt, "")

    def test_fallback_after_browser_failure(self):
        agent = ResearchDispatchAgent(client=FakeMCP(fail={"playwright"}))
        with tempfile.TemporaryDirectory() as td:
            source = SearchSource(id="s", url="https://example.org", title="title")
            result = agent.crawl([source], output_dir=td)[0]
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.locator, "MCP:firecrawl")

    def test_url_dedupe_and_page_budget(self):
        client = FakeMCP()
        agent = ResearchDispatchAgent(client=client, max_pages=1)
        with tempfile.TemporaryDirectory() as td:
            a = SearchSource(id="a", url="https://example.org/a", title="A")
            b = SearchSource(id="b", url=a.url, title="A", channel="brave")
            c = SearchSource(id="c", url="https://example.org/c", title="C")
            result = agent.crawl([a, b, c], output_dir=td)
            self.assertEqual(result[0].body_path, result[1].body_path)
            self.assertEqual(result[2].status, "fetch_failed")
            self.assertEqual(len(client.calls), 1)

    def test_mcp_text_json_and_errors(self):
        result = {"content": [{"type": "text", "text": json.dumps({"markdown": "body"})}]}
        self.assertEqual(body_text(unpack(result)), "body")
        self.assertEqual(body_text("plain extracted body"), "plain extracted body")
        self.assertEqual(body_text({"description": "snippet"}), "")
        self.assertEqual(body_text({"success": False, "markdown": "error"}), "")
        with self.assertRaises(RuntimeError):
            unpack({"isError": True})


if __name__ == "__main__":
    unittest.main()
