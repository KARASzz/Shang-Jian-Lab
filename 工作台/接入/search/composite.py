"""旧版搜索兼容层；生产流水线改由 ``ResearchDispatchAgent`` 调度本地 MCP。"""

from __future__ import annotations

from typing import Iterable

from 工作台.接入.config import WorkbenchConfig
from 工作台.接入.search.bing_public import BingPublicSearch
from 工作台.接入.search.brave_mcp import BraveMCPClient
from 工作台.接入.search.ima_kb import IMAKnowledgeBaseSearch
from 工作台.接入.search.schemas import SearchSource
from 工作台.接入.search.tavily_mcp import TavilyMCPClient


class CompositeSearch:
    """旧版三渠道兼容层；生产流水线由五 MCP 调度器负责，不假装零命中。"""

    def __init__(self, config: WorkbenchConfig) -> None:
        self._tavily = TavilyMCPClient(config.tavily) if config.tavily else None
        self._brave = BraveMCPClient(config.brave) if config.brave else None
        self._bing = BingPublicSearch(config.bing) if config.bing else None
        self._ima = IMAKnowledgeBaseSearch(config.ima) if config.ima else None

    def disabled_channels(self) -> set[str]:
        """返回本进程内被永久禁用（配额用尽/未配置）的渠道集合。

        选题研究阶段据此把 Tavily 等"已不可用"的渠道从必需集合中剔除，
        避免每次重跑都因为单一渠道失败而整轮抛错。其余渠道仍按真实结果
        计入 ``valid_channels``。
        """
        disabled: set[str] = set()
        if self._tavily is None:
            disabled.add("tavily")
        elif getattr(self._tavily, "_disabled_reason", None):
            disabled.add("tavily")
        if self._brave is None:
            disabled.add("brave")
        if self._bing is None:
            disabled.add("bing")
        if self._ima is None:
            disabled.add("ima")
        return disabled

    def expected_channels(self, base: Iterable[str] = ("tavily", "brave", "bing")) -> set[str]:
        """返回本轮仍需被尝试的渠道；已禁用渠道自动豁免。"""
        disabled = self.disabled_channels()
        return {channel for channel in base if channel not in disabled}

    def search(self, query: str, *, round_idx: int) -> list[SearchSource]:
        out: list[SearchSource] = []
        seen: set[str] = set()
        for channel, client in (
            ("tavily", self._tavily),
            ("brave", self._brave),
            ("bing", self._bing),
            ("ima", self._ima),
        ):
            reason: str | None = "未配置" if client is None else None
            if client is None:
                batch = [self._failure(channel, query, round_idx, reason or "未配置")]
            else:
                try:
                    batch = client.search(query, round_idx=round_idx)
                except Exception as exc:  # noqa: BLE001 - 记录真实渠道失败，交由证据阶段拦截
                    reason = f"调用失败（{exc}）"
                    batch = [self._failure(channel, query, round_idx, reason)]
                if not batch:
                    reason = "未返回可用结果"
                    batch = [self._failure(channel, query, round_idx, reason)]
            if reason is not None:
                # 渠道参与但零命中必须可见，否则看起来像"没检索"。
                print(f"提示：{channel} 本轮零命中（{reason}）", flush=True)
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
            "ima": self._ima,
        }.get(source.channel)
        if channel is None:
            return source
        return channel.fetch(source)

    def set_output_dir(self, output_dir: str) -> None:
        """为支持正文落盘的参考来源设置当期资料目录。"""

        if self._ima is not None:
            self._ima.set_output_dir(output_dir)
