"""工作台 / 接入 / search / schemas —— 接口规范 §2 字段一致。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class SearchSource:
    """接口规范 §2：搜索来源统一结构。"""

    id: str
    url: str
    title: str
    publisher: str | None
    published_at: str | None          # ISO 8601
    accessed_at: str                  # ISO 8601
    excerpt: str
    locator: str | None
    body_path: str | None
    status: Literal["ok", "paywall", "captcha", "fetch_failed", "pdf_unparsed"]
    channel: Literal["tavily", "brave", "bing"]
