"""把 Tavily / Brave / Bing 合成 ``SearchClient`` Protocol。"""

from __future__ import annotations

from 工作台.接入.config import WorkbenchConfig
from 工作台.接入.search.bing_public import BingPublicSearch
from 工作台.接入.search.brave_mcp import BraveMCPClient
from 工作台.接入.search.schemas import SearchSource
from 工作台.接入.search.tavily_mcp import TavilyMCPClient


class CompositeSearch:
    """三渠道合一；任一渠道失败以 ``fetch_failed`` 源记录，不假装零命中。"""

    def __init__(self, config: WorkbenchConfig) -> None:
        self._tavily = TavilyMCPClient(config.tavily) if config.tavily else None
        self._brave = BraveMCPClient(config.brave) if config.brave else None
        self._bing = BingPublicSearch(config.bing) if config.bing else None

    def search(self, query: str, *, round_idx: int) -> list[SearchSource]:
        out: list[SearchSource] = []
        seen: set[str] = set()
        for client in (self._tavily, self._brave, self._bing):
            if client is None:
                continue
            batch = client.search(query, round_idx=round_idx)
            for src in batch:
                if src.id in seen:
                    continue
                seen.add(src.id)
                out.append(src)
        return out

    def fetch(self, source: SearchSource) -> SearchSource:
        channel = {
            "tavily": self._tavily,
            "brave": self._brave,
            "bing": self._bing,
        }.get(source.channel)
        if channel is None:
            return source
        return channel.fetch(source)
