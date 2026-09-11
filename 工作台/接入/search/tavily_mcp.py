"""Tavily 搜索 HTTP API 接入。"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from 工作台.接入.config import MCPStdioConfig, resolve_api_key
from 工作台.接入.search.schemas import SearchSource


def _secure_opener() -> Any:
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))


@dataclass(frozen=True)
class MCPStdioPlan:
    """兼容旧配置展示的环境变量映射。"""

    command: str
    args: tuple[str, ...]
    env_keys: dict[str, str]


class TavilySearchError(RuntimeError):
    """Tavily 搜索调用失败。"""


class TavilyMCPClient:
    """按现有配置读取 ``TAVILY_API_KEY``，直接调用 Tavily Search API。"""

    _API_URL = "https://api.tavily.com/search"

    def __init__(
        self,
        config: MCPStdioConfig,
        *,
        http_opener: Callable[..., Any] | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        if config.transport != "stdio":
            raise ValueError("TavilyMCPClient 仅接受 stdio 配置")
        self._config = config
        self._http_opener = http_opener or _secure_opener
        self._timeout_seconds = timeout_seconds
        self._disabled_reason: str | None = None
        self._disabled_notified = False

    @property
    def config(self) -> MCPStdioConfig:
        return self._config

    def build_plan(self) -> MCPStdioPlan:
        return MCPStdioPlan(self._config.command, self._config.args, dict(self._config.env_keys))

    def _key(self) -> str:
        for parent_name in self._config.env_keys.values():
            key = resolve_api_key(parent_name)
            if key:
                return key
        raise TavilySearchError("未配置 Tavily 搜索凭据")

    def start(self) -> dict[str, Any]:
        self._key()
        return {"status": "ok", "transport": "https", "endpoint": self._API_URL}

    def discover_tools(self) -> list[str]:
        self._key()
        return ["search"]

    def search(self, query: str, *, round_idx: int = 0, max_results: int = 10) -> list[SearchSource]:
        if self._disabled_reason:
            return []
        payload = {
            "api_key": self._key(),
            "query": query,
            "search_depth": "advanced",
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
        }
        request = urllib.request.Request(
            self._API_URL,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            response = self._http_opener().open(request, timeout=self._timeout_seconds)
            try:
                data = json.loads(response.read())
            finally:
                close = getattr(response, "close", None)
                if close:
                    close()
        except urllib.error.HTTPError as exc:
            if exc.code in (402, 432):
                self._disabled_reason = "quota"
                if not self._disabled_notified:
                    print("Tavily 当前额度不可用，本轮改用其他搜索渠道。", flush=True)
                    self._disabled_notified = True
                return []
            raise TavilySearchError(f"Tavily 搜索服务返回 HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise TavilySearchError("Tavily 搜索服务暂时无法连接") from exc
        return self._sources(data, round_idx=round_idx)

    def fetch(self, source: SearchSource) -> SearchSource:
        return source

    @staticmethod
    def _sources(data: Any, *, round_idx: int) -> list[SearchSource]:
        results = data.get("results", []) if isinstance(data, dict) else []
        accessed = datetime.now(timezone.utc).isoformat(timespec="seconds")
        out: list[SearchSource] = []
        for index, item in enumerate(results):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or "").strip()
            if not url or not title:
                continue
            out.append(SearchSource(
                id=f"tavily-{round_idx}-{index}", url=url, title=title,
                publisher=item.get("source"), published_at=item.get("published_date"),
                accessed_at=accessed, excerpt=str(item.get("content") or "").strip(),
                locator=None, body_path=None, status="ok", channel="tavily",
            ))
        return out

    @staticmethod
    def build_child_env(plan: MCPStdioPlan) -> dict[str, str]:
        child_env = dict(os.environ)
        for child_var, parent_var in plan.env_keys.items():
            child_env[child_var] = resolve_api_key(parent_var) or ""
        return child_env


__all__ = ["MCPStdioPlan", "TavilyMCPClient", "TavilySearchError"]
