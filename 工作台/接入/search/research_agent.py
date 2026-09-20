"""受限 MCP 检索调度：先按任务选入口，再根据有效来源补查。"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from typing import Any, Iterable

from 工作台.接口 import SearchSource
from 工作台.接入.search.capability_registry import ALIASES, CapabilityRegistry, find_tool
from 工作台.接入.search.local_mcp import LocalMCPClient, LocalMCPError, classify_error


# 保留只读便捷映射，真实服务解析仍由 CapabilityRegistry 完成。
SERVERS = {channel: aliases[0] for channel, aliases in ALIASES.items()}
SEARCH_TOOLS = {
    "firecrawl": ("firecrawl_search", "firecrawl_scrape", "firecrawl_research_search_papers"),
    "tavily": ("tavily_search", "tavily_extract"),
    "brave": ("brave_web_search", "brave_news_search"),
    "context7": ("resolve-library-id", "query-docs"),
    "playwright": ("browser_navigate",),
}
WEB_CHANNELS = ("firecrawl", "brave", "tavily")


def unpack(result: Any) -> Any:
    """兼容 MCP structuredContent、JSON text 与普通文本响应。"""
    if not isinstance(result, dict):
        return result
    if result.get("isError"):
        raise LocalMCPError("MCP 工具返回错误", category=classify_error(result))
    structured = result.get("structuredContent")
    if structured:
        return structured
    content = result.get("content")
    if isinstance(content, list):
        parts = [x.get("text", "") for x in content if isinstance(x, dict) and x.get("type") == "text"]
        parsed = []
        for part in parts:
            try:
                parsed.append(json.loads(part))
            except (ValueError, TypeError):
                continue
        if parsed:
            return parsed[0] if len(parsed) == 1 else parsed
        return "\n".join(parts)
    return result


def search_items(value: Any):
    if isinstance(value, list):
        for item in value:
            yield from search_items(item)
    elif isinstance(value, dict):
        if value.get("url") or value.get("link"):
            yield value
        else:
            for key in ("data", "web", "results", "items", "result", "papers"):
                if key in value:
                    yield from search_items(value[key])
    elif isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, (dict, list)):
            yield from search_items(parsed)
            return
        seen = set()
        for match in re.finditer(
            r"Title:\s*(.*?)\nURL:\s*(https?://\S+)\n(?:Description:\s*)?(.*?)(?=\nTitle:|\Z)",
            value, re.S,
        ):
            url = match[2].rstrip(".,;)")
            seen.add(url)
            yield {"title": match[1].strip(), "url": url, "description": match[3].strip()}
        for match in re.finditer(r"https?://[^\s<>\"']+", value):
            url = match[0].rstrip(".,;)")
            if url in seen:
                continue
            prefix = value[:match.start()].splitlines()[-1].strip()
            prefix = re.sub(r"^[-*#\d.)\s]+", "", prefix).strip()
            yield {"title": prefix[:200] or url, "url": url, "description": prefix}


def body_text(value: Any) -> str:
    """只从正文提取响应读取正文，不把搜索 snippet 或错误当正文。"""
    if isinstance(value, dict):
        if value.get("success") is False or value.get("error"):
            return ""
        for key in ("markdown", "raw_content", "text", "content"):
            if isinstance(value.get(key), str) and value[key].strip():
                return value[key].strip()
        for key in ("data", "results", "result"):
            if key in value:
                text = body_text(value[key])
                if text:
                    return text
    if isinstance(value, list):
        return "\n\n".join(filter(None, (body_text(item) for item in value)))
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""


def _library_id(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("libraryId", "library_id", "id"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.startswith("/"):
                return candidate.strip()
        for child in value.values():
            found = _library_id(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _library_id(child)
            if found:
                return found
    elif isinstance(value, str):
        match = re.search(r"(?:Context7-compatible library ID:\s*)?(/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?)", value)
        if match:
            return match.group(1)
    return None


class ResearchDispatchAgent:
    """实现 SearchClient / CrawlClient，避免扫描或调用非检索 MCP。"""

    def __init__(self, *, client=None, ima=None, max_results=20, max_pages=96, server_overrides=None):
        self.client = client or LocalMCPClient()
        self.ima = ima
        self.max_results = max(1, int(max_results))
        self.max_pages = max(1, int(max_pages))
        self.registry = CapabilityRegistry(self.client, overrides=server_overrides)
        self._output_dir: Path | None = None
        self._pending: list[dict[str, Any]] = []
        self._intent = "general"
        self._required_channel = "firecrawl"
        self._inline_bodies: dict[str, str] = {}

    def set_intent(self, intent: str) -> None:
        if intent not in {"general", "topic_research", "evidence"}:
            raise ValueError("检索意图不受支持")
        self._intent = intent

    def expected_channels(self):
        return {self._required_channel}

    def required_channels(self, _intent: str | None = None):
        return {self._required_channel}

    def validate_attempts(self, round_idx: int, sources: list[SearchSource], *, intent: str | None = None) -> None:
        attempted = {source.channel for source in sources}
        if attempted.intersection((*WEB_CHANNELS, "context7")):
            return
        raise RuntimeError(f"选题研究第 {round_idx + 1} 轮没有完成公开网页检索")

    def disabled_channels(self):
        disabled = set(WEB_CHANNELS)
        for channel in WEB_CHANNELS:
            try:
                self.registry.server(channel)
                disabled.discard(channel)
            except LocalMCPError:
                continue
        return disabled

    def set_output_dir(self, output_dir):
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        if self.ima:
            self.ima.set_output_dir(output_dir)
        for record in self._pending:
            self._write_record(record)
        self._pending.clear()

    def _write_record(self, record):
        if self._output_dir is None:
            self._pending.append(record)
            return
        with (self._output_dir / "MCP调度记录.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _call(self, channel: str, names: tuple[str, ...], arguments: dict[str, Any]):
        server = ""
        tool_name = names[0]
        try:
            server = self.registry.server(channel)
            call_any = getattr(self.client, "call_any", None)
            if callable(call_any):
                called = call_any(server, names, arguments)
                tool_name = called["tool"]["name"]
                result = unpack(called["result"])
            else:
                tool = find_tool(self.registry, channel, names)
                tool_name = tool["name"]
                schema = tool.get("inputSchema", {})
                properties = schema.get("properties") if isinstance(schema, dict) else None
                if isinstance(properties, dict):
                    arguments = {key: value for key, value in arguments.items() if key in properties}
                required = set(schema.get("required", [])) if isinstance(schema, dict) else set()
                if required - set(arguments):
                    raise LocalMCPError("检索参数与 MCP 工具要求不匹配", category="protocol")
                result = unpack(self.client.call(server, tool_name, arguments))
        except Exception as exc:
            category = getattr(exc, "category", None) or classify_error(exc)
            self._write_record({"at": self._now(), "channel": channel, "server": server or None,
                                "tool": tool_name, "status": "failed", "category": category})
            raise LocalMCPError("检索 MCP 调用失败", category=category) from None
        self._write_record({"at": self._now(), "channel": channel, "server": server,
                            "tool": tool_name, "status": "ok"})
        return result

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _canonical_url(url: str) -> str:
        parsed = urlsplit(url.strip())
        host = (parsed.hostname or "").lower()
        if not host:
            return ""
        port = parsed.port
        netloc = host if port is None or (parsed.scheme == "https" and port == 443) or (parsed.scheme == "http" and port == 80) else f"{host}:{port}"
        tracking = {"fbclid", "gclid", "msclkid", "ref_src"}
        query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                 if not key.lower().startswith("utm_") and key.lower() not in tracking]
        query.sort()
        return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", urlencode(query, doseq=True), ""))

    @staticmethod
    def _public_url(url):
        try:
            parsed = urlsplit(url)
            return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and not parsed.username
        except ValueError:
            return False

    @staticmethod
    def _embedded_body(item: dict[str, Any]) -> str:
        # 搜索的 description/content/snippet 通常是摘要；只信明确标为原文的字段。
        for key in ("markdown", "raw_content", "full_content", "page_content"):
            body = item.get(key)
            if isinstance(body, str) and body.strip():
                return body.strip()
        return ""

    def _channel_sources(self, channel: str, result: Any, round_idx: int) -> list[SearchSource]:
        batch: list[SearchSource] = []
        seen: set[str] = set()
        for item in search_items(result):
            url = str(item.get("url") or item.get("link") or "").strip()
            if not self._public_url(url):
                continue
            url = self._canonical_url(url)
            if not url or url in seen:
                continue
            seen.add(url)
            digest = hashlib.sha256(url.encode()).hexdigest()[:16]
            body = self._embedded_body(item)
            if channel == "context7" and not body:
                body = str(item.get("content") or "").strip()
            if body:
                self._inline_bodies[url] = body
            batch.append(SearchSource(
                id=f"{channel}-{round_idx}-{digest}", channel=channel, url=url,
                title=str(item.get("title") or url),
                published_at=item.get("published_date") or item.get("date"),
                publisher=item.get("publisher"), accessed_at=self._now(),
                excerpt=(body or str(item.get("description") or item.get("content") or item.get("snippet") or ""))[:1800],
            ))
            if len(batch) >= self.max_results:
                break
        return batch

    def _firecrawl_search(self, query: str, round_idx: int, *, papers: bool = False) -> list[SearchSource]:
        news = bool(re.search(r"新闻|news|breaking", query, re.I))
        arguments: dict[str, Any] = {"query": query, "limit": self.max_results,
                                     "k": self.max_results}
        if news:
            arguments["sources"] = [{"type": "news"}]
        if papers:
            arguments["categories"] = ["research"]
        names = ((SEARCH_TOOLS["firecrawl"][2], SEARCH_TOOLS["firecrawl"][0]) if papers
                 else (SEARCH_TOOLS["firecrawl"][0],))
        result = self._call("firecrawl", names, arguments)
        return self._channel_sources("firecrawl", result, round_idx)

    def _context7_search(self, query: str, round_idx: int) -> list[SearchSource]:
        candidates = re.findall(r"\b[A-Za-z][A-Za-z0-9_.-]*(?:\.js|\.py|\.ts)?\b", query)
        stop_words = {"how", "what", "where", "when", "why", "which", "show", "find", "search",
                      "read", "use", "using", "to", "for", "about", "the", "a", "an", "official",
                      "documentation", "docs", "api", "reference", "setup", "configure", "configuration",
                      "install", "installation", "example", "examples", "usage", "version", "library",
                      "framework", "sdk", "package"}
        library = next((candidate for candidate in candidates if candidate.lower() not in stop_words), query)
        resolved = self._call("context7", (SEARCH_TOOLS["context7"][0], "resolve_library_id"),
                              {"libraryName": library, "query": query})
        library_id = _library_id(resolved)
        if not library_id:
            raise LocalMCPError("Context7 未返回库标识", category="empty")
        result = self._call("context7", (SEARCH_TOOLS["context7"][1], "query_docs"),
                            {"libraryId": library_id, "query": query})
        return self._channel_sources("context7", result, round_idx)

    @staticmethod
    def _is_developer_query(query: str) -> bool:
        docs_request = re.search(
            r"Context7|官方文档|文档用法|API reference|developer docs|official documentation|documentation",
            query, re.I,
        )
        technical_usage = re.search(
            r"(?:how to|how do i|how can i|configure|install|upgrade|debug|fix|用法|怎么配置|如何使用|安装错误|版本配置)",
            query, re.I,
        ) and re.search(r"\b(?:SDK|API|CLI|Python|Node(?:\.js)?|React|Next\.js|library|framework|package)\b", query, re.I)
        return bool(docs_request or technical_usage)

    @staticmethod
    def _is_paper_query(query: str) -> bool:
        return bool(re.search(r"学术论文|论文检索|\barxiv\b|peer.reviewed|scholarly papers|\bpapers?\b", query, re.I))

    @staticmethod
    def _needs_tavily(query: str, intent: str) -> bool:
        return intent == "topic_research" and bool(re.search(r"研究|论文|学术|research|paper", query, re.I))

    def search(self, query, *, round_idx=0):
        intent = self._intent
        if self._is_developer_query(query):
            route = ["context7", "firecrawl", "brave", "tavily"]
        elif self._is_paper_query(query):
            route = ["firecrawl", "tavily", "brave"]
        else:
            # Firecrawl 是常规入口；Brave/Tavily 只在结果不足或研究需要时补查。
            route = ["firecrawl", "brave", "tavily"]
        if self._needs_tavily(query, intent) and "tavily" not in route:
            route.append("tavily")
        self._required_channel = route[0]

        sources: list[SearchSource] = []
        seen_urls: set[str] = set()
        for channel in route:
            unique_count = len(seen_urls)
            # Primary and explicitly requested complementary sources always run;
            # later fallback providers run only when the evidence gap remains.
            forced = (
                channel == route[0]
                or (intent in {"topic_research", "evidence"} and channel == "brave")
                or (channel == "tavily" and self._needs_tavily(query, intent))
            )
            if not forced and unique_count >= self.max_results:
                break
            try:
                if channel == "firecrawl":
                    batch = self._firecrawl_search(query, round_idx, papers=self._is_paper_query(query))
                elif channel == "context7":
                    batch = self._context7_search(query, round_idx)
                elif channel == "brave":
                    names = ("brave_news_search", "brave_web_search") if re.search(r"新聞|news|breaking", query, re.I) else ("brave_web_search",)
                    result = self._call(channel, names, {"query": query, "count": self.max_results,
                                                         "max_results": self.max_results})
                    batch = self._channel_sources(channel, result, round_idx)
                else:
                    result = self._call(channel, (SEARCH_TOOLS["tavily"][0],), {
                        # Tavily schema enforces 5..20; normalization still applies
                        # this project's stricter max_results cap to returned rows.
                        "query": query, "max_results": max(5, min(20, self.max_results)),
                        "search_depth": "advanced",
                    })
                    batch = self._channel_sources(channel, result, round_idx)
                fresh = [source for source in batch if source.url not in seen_urls]
                for source in fresh:
                    seen_urls.add(source.url)
                sources.extend(fresh)
                status = "ok" if fresh else ("empty" if not batch else "duplicate")
                self._write_record({"at": self._now(), "channel": channel,
                                    "status": status, "returned_results": len(batch),
                                    "unique_results": len(fresh)})
                if not batch:
                    sources.append(SearchSource(
                        id=f"{channel}-empty-r{round_idx}", url="",
                        title=f"{channel} 未返回有效来源", status="fetch_failed",
                        accessed_at=self._now(), channel=channel,
                    ))
                if channel == "context7" and fresh:
                    # Context7 returns version-aware official documentation; only
                    # fall back to web search when it returns no citeable page.
                    break
            except Exception as exc:
                category = getattr(exc, "category", None) or classify_error(exc)
                self._write_record({"at": self._now(), "channel": channel,
                                    "status": "failed", "category": category})
                sources.append(SearchSource(
                    id=f"{channel}-failed-r{round_idx}", url="",
                    title=f"{channel} 检索失败（{category}）", status="fetch_failed",
                    accessed_at=self._now(), channel=channel,
                ))
        if self.ima:
            try:
                sources.extend(self.ima.search(query, round_idx=round_idx))
            except Exception as exc:
                category = getattr(exc, "category", None) or classify_error(exc)
                self._write_record({"at": self._now(), "channel": "ima", "status": "failed", "category": category})
                sources.append(SearchSource(id=f"ima-failed-r{round_idx}", url="", title=f"IMA 检索失败（{category}）",
                                            channel="ima", status="fetch_failed"))
        return sources

    def fetch(self, source):
        return self.ima.fetch(source) if source.channel == "ima" and self.ima else source

    def _extract(self, channel: str, url: str) -> str:
        if channel == "playwright":
            result = self._call(channel, SEARCH_TOOLS["playwright"], {"url": url})
            if isinstance(result, str) and "### Snapshot" in result:
                snapshot = result.split("### Snapshot", 1)[1].strip()
                if "- paragraph:" in snapshot or "- article" in snapshot:
                    return snapshot
            return ""
        if channel == "firecrawl":
            result = self._call(channel, (SEARCH_TOOLS["firecrawl"][1],),
                                {"url": url, "formats": ["markdown"], "onlyMainContent": True, "maxAge": 0})
        else:
            result = self._call(channel, (SEARCH_TOOLS["tavily"][1],),
                                {"urls": [url], "format": "markdown", "extract_depth": "advanced"})
        return body_text(result)

    @staticmethod
    def _requires_interaction(source: SearchSource) -> bool:
        return bool(source.locator and source.locator.lower() in {"requires_interaction", "interactive"})

    def crawl(self, sources: Iterable[SearchSource], *, output_dir):
        self.set_output_dir(output_dir)
        body_dir = Path(output_dir) / "正文"
        body_dir.mkdir(parents=True, exist_ok=True)
        out: list[SearchSource] = []
        cached: dict[str, tuple[str, Path | None, str | None]] = {}
        page_count = 0
        for source in sources:
            if source.status != "ok" or not self._public_url(source.url):
                out.append(source)
                continue
            if source.url in cached:
                text, path, extractor = cached[source.url]
            else:
                text = self._inline_bodies.get(source.url, "")
                path: Path | None = None
                extractor: str | None = "search-response" if text else None
                if text:
                    path = body_dir / (hashlib.sha256(source.url.encode()).hexdigest()[:16] + ".md")
                    path.write_text(text, encoding="utf-8")
                elif page_count < self.max_pages:
                    order = ["firecrawl", "tavily"]
                    if self._requires_interaction(source):
                        order = ["playwright", *order]
                    page_count += 1
                    for channel in order:
                        try:
                            text = self._extract(channel, source.url)
                        except LocalMCPError:
                            continue
                        if text.strip():
                            extractor = channel
                            break
                    if text.strip():
                        path = body_dir / (hashlib.sha256(source.url.encode()).hexdigest()[:16] + ".md")
                        path.write_text(text, encoding="utf-8")
                cached[source.url] = (text, path, extractor)
            out.append(replace(source, status="ok" if path else "fetch_failed",
                               body_path=str(path) if path else None,
                               excerpt=text[:1800] if path else "", accessed_at=self._now(),
                               locator=f"MCP:{extractor}" if path else None))
        return out
