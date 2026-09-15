"""本地五 MCP 检索调度智能体：固定职责、真实工具调用、正文与调用记录落盘。

这是受约束的工作流智能体，不额外调用语言模型。选题判断仍由 planner 负责。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from 工作台.接口 import SearchSource
from 工作台.接入.search.local_mcp import LocalMCPClient


SERVERS = {
    "brave": "brave-search", "tavily": "tavily",
    "omnisearch": "mcp-omnisearch", "firecrawl": "firecrawl-stdio",
    "playwright": "playwright",
}
SEARCH_TOOLS = {
    "brave": ("brave_web_search",), "tavily": ("tavily_search",),
    "omnisearch": ("web_search",), "firecrawl": ("firecrawl_search",),
}


def unpack(result):
    """兼容 MCP structuredContent、JSON text 与普通文本响应。"""
    if not isinstance(result, dict):
        return result
    if result.get("isError"):
        raise RuntimeError("MCP 工具返回错误")
    structured = result.get("structuredContent")
    if structured:
        return structured
    content = result.get("content")
    if isinstance(content, list):
        parts = [x.get("text", "") for x in content if x.get("type") == "text"]
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


def search_items(value):
    if isinstance(value, list):
        for item in value:
            yield from search_items(item)
    elif isinstance(value, dict):
        if value.get("url") or value.get("link"):
            yield value
        else:
            for key in ("data", "web", "results", "items", "result"):
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
        # Brave MCP 的文本格式：Title / URL / Description。
        seen = set()
        for match in re.finditer(
            r"Title:\s*(.*?)\nURL:\s*(https?://\S+)\n(?:Description:\s*)?(.*?)(?=\nTitle:|\Z)",
            value, re.S,
        ):
            url = match[2].rstrip(".,;)")
            seen.add(url)
            yield {"title": match[1].strip(), "url": url, "description": match[3].strip()}
        # Tavily 及部分 MCP 文本结果是一段说明后跟一个裸 URL；保留说明
        # 作为标题/摘要，避免因响应不是 JSON 而丢掉整个渠道。
        for match in re.finditer(r"https?://[^\s<>\"']+", value):
            url = match[0].rstrip(".,;)")
            if url in seen:
                continue
            prefix = value[:match.start()].splitlines()[-1].strip()
            prefix = re.sub(r"^[-*#\d.)\s]+", "", prefix).strip()
            yield {"title": prefix[:200] or url, "url": url, "description": prefix}


def body_text(value):
    """只接受提取正文，不把搜索 snippet、调用元数据或错误说明当正文。"""
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
        return "\n\n".join(filter(None, (body_text(x) for x in value)))
    if isinstance(value, str) and value.strip():
        # 某些提取器把正文作为普通 text 返回；此函数只接收正文提取响应，
        # 搜索摘要仍只在 search_items 中处理，不会走到这里。
        return value.strip()
    return ""


class ResearchDispatchAgent:
    """同时实现 SearchClient / CrawlClient，供两个研究阶段共用。

    每轮搜索四个 MCP；每次抓取至少用 Playwright 检查一个来源，其他来源
    轮转三个提取器，失败时换工具。工具发现失败也留下真实记录。
    """

    def __init__(self, *, client=None, ima=None, max_results=20, max_pages=96):
        self.client = client or LocalMCPClient()
        self.ima = ima
        self.max_results = max_results
        self.max_pages = max_pages
        self._tools = {}
        self._output_dir = None
        self._pending = []

    def expected_channels(self):
        return set(SEARCH_TOOLS)

    def disabled_channels(self):
        # 所有必需渠道都应留下尝试记录，不能通过“禁用”绕过验收。
        return set()

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

    def _call(self, channel, names, arguments):
        server = SERVERS[channel]
        name = names[0]
        try:
            if channel not in self._tools:
                self._tools[channel] = self.client.discover(server)
            tool = next((t for n in names for t in self._tools[channel] if t["name"] == n), None)
            if tool is None:
                raise RuntimeError("未发现所需工具")
            name = tool["name"]
            schema = tool.get("inputSchema", {})
            properties = schema.get("properties")
            if properties is not None:
                arguments = {k: v for k, v in arguments.items() if k in properties}
            if set(schema.get("required", [])) - set(arguments):
                raise RuntimeError("工具参数与已发现协议不匹配")
            result = unpack(self.client.call(server, name, arguments))
            if isinstance(result, dict) and (result.get("success") is False or result.get("error")):
                raise RuntimeError("工具返回失败")
        except Exception as exc:
            # 服务错误可能含凭据、命令行或响应正文；日志只存类型。
            self._write_record({"at": self._now(), "server": server, "tool": name,
                                "status": "failed", "error_type": type(exc).__name__})
            raise RuntimeError(f"{channel} 工具调用失败（{type(exc).__name__}）") from None
        self._write_record({"at": self._now(), "server": server, "tool": name, "status": "ok"})
        return result

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _public_url(url):
        parsed = urlsplit(url)
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and not parsed.username

    def search(self, query, *, round_idx=0):
        sources = []
        for channel, names in SEARCH_TOOLS.items():
            args = {"query": query, "count": self.max_results, "max_results": self.max_results,
                    "limit": self.max_results, "search_depth": "advanced"}
            if channel == "omnisearch":
                args.update(provider="brave", large_result_mode="inline")
            try:
                result = self._call(channel, names, args)
                batch = []
                seen = set()
                for item in search_items(result):
                    url = str(item.get("url") or item.get("link") or "").strip()
                    if not self._public_url(url) or url in seen:
                        continue
                    seen.add(url)
                    digest = hashlib.sha256(url.encode()).hexdigest()[:16]
                    batch.append(SearchSource(
                        id=f"{channel}-{round_idx}-{digest}", channel=channel,
                        url=url, title=str(item.get("title") or url),
                        published_at=item.get("published_date") or item.get("date"),
                        publisher=item.get("publisher"), accessed_at=self._now(),
                        excerpt=str(item.get("description") or item.get("content") or item.get("snippet") or ""),
                    ))
                    if len(batch) >= self.max_results:
                        break
                if not batch:
                    raise RuntimeError("未返回可用结果")
                sources.extend(batch)
            except Exception:
                sources.append(SearchSource(
                    id=f"{channel}-failed-r{round_idx}", url="", channel=channel,
                    title=f"{channel} 检索失败或没有可用结果", status="fetch_failed",
                    accessed_at=self._now(),
                ))
        if self.ima:
            try:
                sources.extend(self.ima.search(query, round_idx=round_idx))
            except Exception:
                sources.append(SearchSource(id=f"ima-failed-r{round_idx}", url="", title="IMA 检索失败",
                                            channel="ima", status="fetch_failed"))
        return sources

    def fetch(self, source):
        return self.ima.fetch(source) if source.channel == "ima" and self.ima else source

    def _extract(self, channel, url):
        if channel == "playwright":
            result = self._call(channel, ("browser_navigate",), {"url": url})
            # navigate 的响应包含浏览器快照；只保留快照，去掉操作日志。
            if isinstance(result, str) and "### Snapshot" in result:
                snapshot = result.split("### Snapshot", 1)[1].strip()
                if "- paragraph:" in snapshot or "- article" in snapshot:
                    return snapshot
            return ""
        if channel == "firecrawl":
            result = self._call(channel, ("firecrawl_scrape",),
                                {"url": url, "formats": ["markdown"], "onlyMainContent": True, "maxAge": 0})
        elif channel == "tavily":
            result = self._call(channel, ("tavily_extract",),
                                {"urls": [url], "format": "markdown", "extract_depth": "advanced"})
        else:
            result = self._call(channel, ("web_extract",),
                                {"urls": [url], "url": url, "provider": "tavily", "large_result_mode": "inline"})
        return body_text(result)

    def crawl(self, sources, *, output_dir):
        self.set_output_dir(output_dir)
        body_dir = Path(output_dir) / "正文"
        body_dir.mkdir(parents=True, exist_ok=True)
        out, cached = [], {}
        extractors = ["firecrawl", "tavily", "omnisearch"]
        page_count = 0
        for source in sources:
            if source.status != "ok" or not self._public_url(source.url):
                out.append(source)
                continue
            if source.url in cached:
                text, path, extractor = cached[source.url]
            else:
                text, path, extractor = "", None, None
                if page_count < self.max_pages:
                    primary = extractors[page_count % len(extractors)]
                    order = (["playwright", primary] if page_count == 0 else [primary])
                    order += [x for x in extractors + ["playwright"] if x not in order]
                    page_count += 1
                    for channel in order:
                        try:
                            text = self._extract(channel, source.url)
                        except RuntimeError:
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
