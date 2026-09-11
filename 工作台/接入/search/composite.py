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
        for channel, client in (
            ("tavily", self._tavily),
            ("brave", self._brave),
            ("bing", self._bing),
        ):
            if client is None:
                batch = [self._failure(channel, query, round_idx, "未配置")]
            else:
                try:
                    batch = client.search(query, round_idx=round_idx)
                except Exception:  # noqa: BLE001 - 记录真实渠道失败，交由证据阶段拦截
                    batch = [self._failure(channel, query, round_idx, "调用失败")]
                if not batch:
                    batch = [self._failure(channel, query, round_idx, "未返回可用结果")]
            for src in batch:
                if src.id in seen:
                    continue
                seen.add(src.id)
                out.append(src)
        return out

    @staticmethod
    def _failure(channel: str, query: str, round_idx: int, reason: str) -> SearchSource:
        return SearchSource(
            id=f"{channel}-failed-r{round_idx}",
            url="",
            title=f"{channel} 搜索{reason}",
            publisher=None,
            published_at=None,
            accessed_at="",
            excerpt=query,
            locator=None,
            body_path=None,
            status="fetch_failed",
            channel=channel,
        )

    def fetch(self, source: SearchSource) -> SearchSource:
        channel = {
            "tavily": self._tavily,
            "brave": self._brave,
            "bing": self._bing,
        }.get(source.channel)
        if channel is None:
            return source
        return channel.fetch(source)
