"""按任务路由、按缺口回退、正文复用及错误类别记录。"""
import json
import tempfile
import unittest
from pathlib import Path

from 工作台.接口 import SearchSource
from 工作台.接入.search.research_agent import ResearchDispatchAgent, body_text, unpack


class FakeMCP:
    def __init__(self, *, fail=(), include_body=False):
        self.calls = []
        self.fail = set(fail)
        self.include_body = include_body
        self.servers = {
            "firecrawl-mcp": ("firecrawl_search", "firecrawl_scrape", "firecrawl_research_search_papers"),
            "brave-search": ("brave_web_search", "brave_news_search"),
            "tavily-search": ("tavily_search", "tavily_extract"),
            "context7": ("resolve-library-id", "query-docs"),
            "playwright-MCP": ("browser_navigate",),
            "mcp-omnisearch": ("web_search", "web_extract"),
        }

    def configured_servers(self):
        return {name: {"enabled": True, "transport": "stdio"} for name in self.servers}

    def discover(self, server):
        return [{"name": name, "inputSchema": {"type": "object"}}
                for name in self.servers[server]]

    def call(self, server, tool, args):
        self.calls.append((server, tool, args))
        if server in self.fail:
            raise RuntimeError("Bearer SECRET_TOKEN 429 rate limit")
        if tool in {"firecrawl_search", "brave_web_search", "brave_news_search", "tavily_search", "firecrawl_research_search_papers"}:
            rows = [{"title": f"Report {server}", "url": f"https://example.org/{server}", "description": "short snippet"}]
            if self.include_body and server == "firecrawl-mcp":
                rows[0]["raw_content"] = "Full report body with methodology, context, and source data."
            return {"structuredContent": {"results": rows}}
        if tool == "resolve-library-id":
            return {"structuredContent": {"libraryId": "/python/docs"}}
        if tool == "query-docs":
            return {"structuredContent": {"results": [{"title": "Python SDK docs", "url": "https://docs.example.org/python-sdk", "content": "SDK setup and client API documentation."}]}}
        if tool == "browser_navigate":
            return {"content": [{"type": "text", "text": "### Snapshot\n- article:\n  - paragraph: Browser evidence"}]}
        return {"structuredContent": {"data": {"markdown": "Extracted evidence with context."}}}


class ResearchAgentTests(unittest.TestCase):
    def test_general_search_starts_with_firecrawl_and_supplements_shortfall_with_brave(self):
        client = FakeMCP()
        agent = ResearchDispatchAgent(client=client, max_results=2)
        sources = agent.search("AI workplace changes")
        self.assertEqual([call[0] for call in client.calls], ["firecrawl-mcp", "brave-search"])
        self.assertEqual({source.channel for source in sources}, {"firecrawl", "brave"})
        self.assertNotIn("mcp-omnisearch", [call[0] for call in client.calls])

    def test_successful_search_with_no_sources_is_recorded_as_empty(self):
        client = FakeMCP()
        def empty_call(server, tool, args):
            client.calls.append((server, tool, args))
            if tool in {"firecrawl_search", "brave_web_search", "tavily_search"}:
                return {"structuredContent": {"results": []}}
            return client.call(server, tool, args)
        client.call = empty_call
        agent = ResearchDispatchAgent(client=client, max_results=2)
        with tempfile.TemporaryDirectory() as td:
            agent.set_output_dir(td)
            sources = agent.search("AI workflow")
            log = [json.loads(line) for line in (Path(td) / "MCP调度记录.jsonl").read_text().splitlines()]
        self.assertEqual({source.channel for source in sources}, {"firecrawl", "brave", "tavily"})
        self.assertTrue(all(source.status == "fetch_failed" for source in sources))
        self.assertTrue(all(item["status"] == "empty" for item in log if item.get("unique_results") == 0))

    def test_topic_research_adds_tavily_for_research_queries_and_freezes_omnisearch(self):
        client = FakeMCP()
        agent = ResearchDispatchAgent(client=client, max_results=5)
        agent.set_intent("topic_research")
        sources = agent.search("近期研究报告与反方证据")
        self.assertEqual({source.channel for source in sources}, {"firecrawl", "brave", "tavily"})
        self.assertFalse(any(call[0] == "mcp-omnisearch" for call in client.calls))

    def test_tavily_provider_minimum_does_not_expand_project_result_limit(self):
        client = FakeMCP()
        agent = ResearchDispatchAgent(client=client, max_results=2)
        agent.set_intent("topic_research")
        sources = agent.search("近期研究报告")
        tavily_call = next(call for call in client.calls if call[1] == "tavily_search")
        self.assertGreaterEqual(tavily_call[2]["max_results"], 5)
        self.assertEqual(sum(source.channel == "tavily" for source in sources), 1)

    def test_search_deduplicates_tracking_variants_by_canonical_url(self):
        client = FakeMCP()
        original = client.call
        def with_duplicate(server, tool, args):
            result = original(server, tool, args)
            if tool in {"brave_web_search", "tavily_search"}:
                return {"structuredContent": {"results": [
                    {"title": "Duplicate", "url": "https://EXAMPLE.org/firecrawl-mcp?utm_source=brave#section", "description": "copy"}
                ]}}
            return result
        client.call = with_duplicate
        agent = ResearchDispatchAgent(client=client, max_results=2)
        sources = agent.search("AI workplace")
        self.assertEqual([source.url for source in sources], ["https://example.org/firecrawl-mcp"])

    def test_context7_resolves_library_before_querying_docs(self):
        client = FakeMCP()
        agent = ResearchDispatchAgent(client=client)
        sources = agent.search("Python SDK official documentation usage")
        self.assertEqual([call[1] for call in client.calls], ["resolve-library-id", "query-docs"])
        self.assertEqual(sources[0].channel, "context7")
        self.assertEqual(sources[0].url, "https://docs.example.org/python-sdk")
        self.assertEqual(client.calls[1][2]["libraryId"], "/python/docs")

    def test_context7_extracts_library_after_english_instruction_words(self):
        client = FakeMCP()
        agent = ResearchDispatchAgent(client=client)
        agent.search("How to use React SDK")
        self.assertEqual(client.calls[0][1], "resolve-library-id")
        self.assertEqual(client.calls[0][2]["libraryName"], "React")

    def test_search_embedded_body_is_saved_and_reused_without_scraping(self):
        client = FakeMCP(include_body=True)
        agent = ResearchDispatchAgent(client=client, max_results=1)
        sources = agent.search("AI workflow")
        firecrawl = next(source for source in sources if source.channel == "firecrawl")
        with tempfile.TemporaryDirectory() as td:
            result = agent.crawl([firecrawl], output_dir=td)[0]
            self.assertEqual(result.status, "ok")
            self.assertIn("Full report body", Path(result.body_path).read_text(encoding="utf-8"))
        self.assertFalse(any(call[1] == "firecrawl_scrape" for call in client.calls))

    def test_playwright_runs_only_for_explicit_interaction_source(self):
        client = FakeMCP()
        agent = ResearchDispatchAgent(client=client)
        regular = SearchSource(id="a", url="https://example.org/a", title="A")
        interactive = SearchSource(id="b", url="https://example.org/b", title="B", locator="requires_interaction")
        with tempfile.TemporaryDirectory() as td:
            agent.crawl([regular, interactive], output_dir=td)
        browser_calls = [call for call in client.calls if call[1] == "browser_navigate"]
        self.assertEqual(len(browser_calls), 1)
        self.assertEqual(browser_calls[0][2]["url"], interactive.url)

    def test_category_log_redacts_service_error_and_records_rate_limit(self):
        client = FakeMCP(fail={"firecrawl-mcp", "brave-search", "tavily-search"})
        agent = ResearchDispatchAgent(client=client, max_results=3)
        with tempfile.TemporaryDirectory() as td:
            agent.set_output_dir(td)
            sources = agent.search("research source", round_idx=1)
            log = (Path(td) / "MCP调度记录.jsonl").read_text(encoding="utf-8")
        self.assertTrue(sources)
        self.assertNotIn("SECRET_TOKEN", log)
        self.assertIn('"category": "rate_limit"', log)
        self.assertNotIn("omnisearch", log)

    def test_body_and_protocol_parsing(self):
        result = {"content": [{"type": "text", "text": json.dumps({"markdown": "body"})}]}
        self.assertEqual(body_text(unpack(result)), "body")
        self.assertEqual(body_text("plain extracted body"), "plain extracted body")
        self.assertEqual(body_text({"description": "snippet"}), "")
        self.assertEqual(body_text({"success": False, "markdown": "error"}), "")


if __name__ == "__main__":
    unittest.main()
