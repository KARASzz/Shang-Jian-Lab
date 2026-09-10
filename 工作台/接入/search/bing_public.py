"""工作台 / 接入 / search / bing_public —— 公开搜索占位。

设计原则：

- 仅做基础限流计数与请求占位；不真正联网。
- 真实实现由主线程集成交付阶段接入。
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any, Callable

from 工作台.接入.config import PublicSearchConfig
from 工作台.接入.search.schemas import SearchSource


class BingPublicSearch:
    """Bing 公开搜索客户端（占位）。"""

    def __init__(
        self,
        config: PublicSearchConfig,
        *,
        sleeper: Callable[[float], None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._config = config
        self._sleeper = sleeper or time.sleep
        self._clock = clock or time.monotonic
        self._hits: deque[float] = deque(maxlen=config.rate_limit_per_minute)

    @property
    def config(self) -> PublicSearchConfig:
        return self._config

    def _throttle(self) -> None:
        """简单滑窗限流；超限时阻塞 sleeper（占位：阻塞 1s 不真正发请求）。"""

        now = self._clock()
        window = 60.0
        # 清掉超出窗口的旧 hit
        while self._hits and now - self._hits[0] > window:
            self._hits.popleft()
        if len(self._hits) >= self._config.rate_limit_per_minute:
            wait = max(0.0, window - (now - self._hits[0]))
            self._sleeper(wait)

    def search(
        self, query: str, *, round_idx: int = 0, max_results: int = 10
    ) -> list[SearchSource]:
        """占位：不发起网络请求。

        不得返回空列表假装「零命中」；用 ``fetch_failed`` 标明渠道未运行。
        """

        self._throttle()
        self._hits.append(self._clock())
        print(
            f"[调试] Bing 公开搜索占位：endpoint={self._config.endpoint} "
            f"query={query!r} round_idx={round_idx} max_results={max_results}"
        )
        return [
            SearchSource(
                id=f"bing-unavail-r{round_idx}",
                url=self._config.endpoint,
                title="Bing 公开搜索未启用（占位，未联网）",
                publisher=None,
                published_at=None,
                accessed_at="",
                excerpt=query,
                locator=None,
                body_path=None,
                status="fetch_failed",
                channel="bing",
            )
        ]

    def fetch(self, source: SearchSource) -> SearchSource:
        """占位：不抓正文，保持原 status。"""

        return source

    def debug_info(self) -> dict[str, Any]:
        return {
            "endpoint": self._config.endpoint,
            "user_agent": self._config.user_agent,
            "rate_limit_per_minute": self._config.rate_limit_per_minute,
            "status": "not_run_in_dev",
        }
