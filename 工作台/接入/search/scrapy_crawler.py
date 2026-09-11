"""用 Scrapy 抓取搜索结果页正文。

搜索渠道只负责发现 URL；本模块负责有限深度的网页抓取和正文落盘。
Scrapy 是运行时依赖，未安装时明确失败，不回退成假成功。
"""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from 工作台.接入.search.schemas import SearchSource


class ScrapyUnavailableError(RuntimeError):
    """当前 Python 环境没有安装 Scrapy。"""


class ScrapyCrawlerError(RuntimeError):
    """Scrapy 抓取失败。"""


def _source_key(source: SearchSource) -> str:
    return hashlib.sha256(source.url.encode("utf-8")).hexdigest()[:16]


def _build_spider(scrapy: Any):
    class SeedSpider(scrapy.Spider):
        name = "shang_jian_topic_research"

        def __init__(self, *, seeds: list[dict[str, Any]], max_links_per_page: int, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.seeds = seeds
            self.max_links_per_page = max_links_per_page

        def _seed_requests(self):
            for seed in self.seeds:
                url = str(seed["url"])
                domain = urlparse(url).netloc.lower()
                yield scrapy.Request(
                    url,
                    callback=self.parse,
                    errback=self.on_error,
                    dont_filter=True,
                    meta={
                        "source_id": str(seed["source_id"]),
                        "seed_url": url,
                        "seed_domain": domain,
                        "depth": 0,
                    },
                )

        async def start(self):
            """Scrapy 2.18+ 的入口；保持 start_requests 兼容旧版。"""
            for request in self._seed_requests():
                yield request

        def start_requests(self):
            for request in self._seed_requests():
                yield request

        def parse(self, response):
            meta = response.meta
            raw_content_type = response.headers.get(b"Content-Type", b"")
            content_type = (
                raw_content_type.decode("ascii", errors="ignore")
                if isinstance(raw_content_type, bytes)
                else str(raw_content_type)
            ).lower()
            if "pdf" in content_type:
                yield {
                    "source_id": meta["source_id"],
                    "url": response.url,
                    "status": "pdf_unparsed",
                    "title": "",
                    "text": "",
                    "depth": meta["depth"],
                }
                return

            title = " ".join(response.css("title::text").getall()).strip()
            text = " ".join(
                part.strip()
                for part in response.css("body ::text").getall()
                if part.strip()
            )
            yield {
                "source_id": meta["source_id"],
                "url": response.url,
                "status": "ok",
                "title": title,
                "text": text[:12000],
                "depth": meta["depth"],
            }

            depth = int(meta["depth"])
            depth_limit = int(self.crawler.settings.getint("DEPTH_LIMIT", 0))
            if depth >= depth_limit:
                return
            seed_domain = str(meta["seed_domain"])
            for href in response.css("a::attr(href)").getall()[: self.max_links_per_page]:
                absolute = response.urljoin(href)
                parsed = urlparse(absolute)
                if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != seed_domain:
                    continue
                yield scrapy.Request(
                    absolute,
                    callback=self.parse,
                    errback=self.on_error,
                    meta={**meta, "depth": depth + 1},
                )

        def on_error(self, failure):
            request = failure.request
            yield {
                "source_id": request.meta.get("source_id", ""),
                "url": request.url,
                "status": "fetch_failed",
                "title": "",
                "text": "",
                "error": str(getattr(failure, "value", failure)),
                "depth": request.meta.get("depth", 0),
            }

    return SeedSpider


class ScrapyCrawler:
    """一次研究任务内运行一个 Scrapy crawler，避免重复启动 Twisted reactor。"""

    def __init__(
        self,
        *,
        depth_limit: int = 1,
        max_pages: int = 36,
        max_links_per_page: int = 4,
        download_timeout: int = 20,
        obey_robots_txt: bool = True,
    ) -> None:
        if depth_limit < 0:
            raise ValueError("Scrapy depth_limit 不能为负")
        if max_pages < 1:
            raise ValueError("Scrapy max_pages 必须大于 0")
        self.depth_limit = depth_limit
        self.max_pages = max_pages
        self.max_links_per_page = max_links_per_page
        self.download_timeout = download_timeout
        self.obey_robots_txt = obey_robots_txt

    def crawl(self, sources: list[SearchSource], *, output_dir: str) -> list[SearchSource]:
        if not sources:
            return []
        try:
            import scrapy
            from scrapy.crawler import CrawlerProcess
        except ImportError as exc:  # pragma: no cover - depends on runtime environment
            raise ScrapyUnavailableError(
                "未安装 Scrapy，无法进行选题网页抓取；请先安装 Scrapy 后重试"
            ) from exc

        out_dir = Path(output_dir)
        body_dir = out_dir / "正文"
        body_dir.mkdir(parents=True, exist_ok=True)
        feed_path = out_dir / "抓取记录.jsonl"
        seeds = [
            {"source_id": source.id, "url": source.url}
            for source in sources
            if source.status == "ok" and source.url
        ]
        if not seeds:
            return list(sources)

        settings = {
            "LOG_ENABLED": False,
            "ROBOTSTXT_OBEY": self.obey_robots_txt,
            "DEPTH_LIMIT": self.depth_limit,
            "CLOSESPIDER_PAGECOUNT": self.max_pages,
            "DOWNLOAD_TIMEOUT": self.download_timeout,
            "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
            "AUTOTHROTTLE_ENABLED": True,
            "AUTOTHROTTLE_START_DELAY": 0.5,
            "AUTOTHROTTLE_MAX_DELAY": 8.0,
            "FEEDS": {
                str(feed_path): {
                    "format": "jsonlines",
                    "encoding": "utf8",
                    "overwrite": True,
                }
            },
        }
        process = CrawlerProcess(settings=settings)
        spider = _build_spider(scrapy)
        try:
            process.crawl(
                spider,
                seeds=seeds,
                max_links_per_page=self.max_links_per_page,
            )
            if "install_signal_handlers" in inspect.signature(process.start).parameters:
                process.start(stop_after_crawl=True, install_signal_handlers=False)
            else:  # pragma: no cover - older Scrapy compatibility
                process.start()
        except Exception as exc:  # noqa: BLE001 - preserve a truthful crawl failure
            raise ScrapyCrawlerError(f"Scrapy 抓取失败：{type(exc).__name__}") from exc

        records: list[dict[str, Any]] = []
        if feed_path.exists():
            for line in feed_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    records.append(json.loads(line))
        by_source: dict[str, list[dict[str, Any]]] = {}
        by_url: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            by_source.setdefault(str(record.get("source_id", "")), []).append(record)
            if record.get("url"):
                by_url.setdefault(str(record["url"]), []).append(record)

        result: list[SearchSource] = []
        for source in sources:
            items = by_source.get(source.id, []) or by_url.get(source.url, [])
            root = next((item for item in items if item.get("url") == source.url), None)
            if root is None:
                root = items[0] if items else None
            if not root or root.get("status") != "ok" or not str(root.get("text", "")).strip():
                result.append(replace(source, status="fetch_failed"))
                continue
            text = " ".join(str(root.get("text", "")).split())
            body_path = body_dir / f"{_source_key(source)}.txt"
            body_path.write_text(text, encoding="utf-8")
            title = str(root.get("title") or source.title).strip()
            result.append(replace(
                source,
                title=title or source.title,
                excerpt=text[:1800],
                body_path=str(body_path),
                status="ok",
            ))
        return result


__all__ = ["ScrapyCrawler", "ScrapyCrawlerError", "ScrapyUnavailableError"]
