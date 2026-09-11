"""Bing 公开网页搜索接入。"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
import ssl
from collections import deque
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Callable

from 工作台.接入.config import PublicSearchConfig
from 工作台.接入.search.schemas import SearchSource


def _secure_opener() -> Any:
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))


class BingSearchError(RuntimeError):
    """Bing 搜索调用失败。"""


class _BingParser(HTMLParser):
    def __init__(self, limit: int) -> None:
        super().__init__()
        self.limit = limit
        self.in_result = False
        self.in_title = False
        self.in_description = False
        self.current: dict[str, str] = {}
        self.results: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        classes = set((attr.get("class") or "").split())
        if tag == "li" and "b_algo" in classes:
            if len(self.results) >= self.limit:
                return
            self.in_result = True
            self.current = {}
        elif self.in_result and tag == "a" and not self.current.get("url"):
            href = attr.get("href")
            if href:
                self.current["url"] = href
                self.in_title = True
        elif self.in_result and tag == "p":
            self.in_description = True

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.current["title"] = self.current.get("title", "") + data
        elif self.in_description:
            self.current["description"] = self.current.get("description", "") + data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self.in_title = False
        elif tag == "p":
            self.in_description = False
        elif tag == "li" and self.in_result:
            if self.current.get("url") and self.current.get("title"):
                self.results.append({k: v.strip() for k, v in self.current.items()})
            self.current = {}
            self.in_result = False


class BingPublicSearch:
    def __init__(
        self,
        config: PublicSearchConfig,
        *,
        sleeper: Callable[[float], None] | None = None,
        clock: Callable[[], float] | None = None,
        http_opener: Callable[..., Any] | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self._config = config
        self._sleeper = sleeper or __import__("time").sleep
        self._clock = clock or __import__("time").monotonic
        self._http_opener = http_opener or _secure_opener
        self._timeout_seconds = timeout_seconds
        self._hits: deque[float] = deque(maxlen=config.rate_limit_per_minute)

    @property
    def config(self) -> PublicSearchConfig:
        return self._config

    def _throttle(self) -> None:
        now = self._clock()
        while self._hits and now - self._hits[0] > 60.0:
            self._hits.popleft()
        if len(self._hits) >= self._config.rate_limit_per_minute:
            self._sleeper(max(0.0, 60.0 - (now - self._hits[0])))

    def search(self, query: str, *, round_idx: int = 0, max_results: int = 10) -> list[SearchSource]:
        self._throttle()
        self._hits.append(self._clock())
        url = self._config.endpoint + "?" + urllib.parse.urlencode({"q": query, "count": max_results})
        request = urllib.request.Request(url, method="GET", headers={"User-Agent": self._config.user_agent})
        try:
            response = self._http_opener().open(request, timeout=self._timeout_seconds)
            try:
                html = response.read().decode("utf-8", errors="replace")
            finally:
                close = getattr(response, "close", None)
                if close:
                    close()
        except urllib.error.HTTPError as exc:
            raise BingSearchError(f"Bing 搜索服务返回 HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise BingSearchError("Bing 搜索服务暂时无法连接") from exc
        parser = _BingParser(max_results)
        parser.feed(html)
        accessed = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return [SearchSource(
            id=f"bing-{round_idx}-{index}", url=item["url"], title=item["title"],
            publisher=None, published_at=None, accessed_at=accessed,
            excerpt=item.get("description", ""), locator=None, body_path=None,
            status="ok", channel="bing",
        ) for index, item in enumerate(parser.results)]

    def fetch(self, source: SearchSource) -> SearchSource:
        return source

    def debug_info(self) -> dict[str, Any]:
        return {
            "endpoint": self._config.endpoint,
            "rate_limit_per_minute": self._config.rate_limit_per_minute,
            "status": "ready",
        }


__all__ = ["BingPublicSearch", "BingSearchError"]
