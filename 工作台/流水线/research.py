"""选题前研究：两轮三渠道搜索后抓取网页，再交给 planner 生成候选。"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from 工作台.接口 import CrawlClient, SearchClient, SearchSource
from 工作台.流水线.checkpoint import commit_stage


EXPECTED_CHANNELS = frozenset({"tavily", "brave", "bing"})


class TopicResearchStage:
    """固定两轮调用 Tavily / Brave / Bing，并抓取搜索结果正文。"""

    def __init__(
        self,
        *,
        search: SearchClient,
        crawler: CrawlClient,
        rounds_max: int = 2,
        max_sources_per_round: int = 6,
        min_valid_channels_per_round: int = 2,
    ) -> None:
        if rounds_max != 2:
            raise ValueError("选题研究必须严格执行 2 轮")
        if max_sources_per_round < 1:
            raise ValueError("max_sources_per_round 必须大于 0")
        if not 1 <= min_valid_channels_per_round <= 3:
            raise ValueError("min_valid_channels_per_round 必须在 1–3 之间")
        self.search = search
        self.crawler = crawler
        self.rounds_max = rounds_max
        self.max_sources_per_round = max_sources_per_round
        self.min_valid_channels_per_round = min_valid_channels_per_round

    @staticmethod
    def build_query(
        *,
        column: str,
        round_idx: int,
        topic_seed: str | None = None,
        prior_titles: list[str] | None = None,
    ) -> str:
        seed = (topic_seed or "").strip()
        if round_idx == 0:
            return (
                f"{column} {seed} 近期趋势 争议 研究 报告 生产力 评测 2026".strip()
            )
        focus = "；".join(title.strip() for title in (prior_titles or []) if title.strip())
        return (
            f"{column} {seed} {focus} 反方证据 失败案例 可验证数据 生产实践 2026".strip()
        )[:600]

    @staticmethod
    def _validate_attempts(round_idx: int, sources: list[SearchSource]) -> None:
        attempted = {source.channel for source in sources}
        missing = sorted(EXPECTED_CHANNELS - attempted)
        if missing:
            raise RuntimeError(
                f"选题研究第 {round_idx + 1} 轮未完成三渠道调用：缺少 {', '.join(missing)}"
            )

    def _select_seeds(self, sources: list[SearchSource]) -> list[SearchSource]:
        selected: list[SearchSource] = []
        seen_urls: set[str] = set()
        for source in sources:
            if source.status != "ok" or not source.url or source.url in seen_urls:
                continue
            selected.append(source)
            seen_urls.add(source.url)
            if len(selected) >= self.max_sources_per_round:
                break
        return selected

    @staticmethod
    def _dedupe_seeds(sources: list[SearchSource]) -> list[SearchSource]:
        """合并两轮种子；不能再次套用单轮上限，避免漏抓第二轮来源。"""
        out: list[SearchSource] = []
        seen_urls: set[str] = set()
        for source in sources:
            if source.status != "ok" or not source.url or source.url in seen_urls:
                continue
            out.append(source)
            seen_urls.add(source.url)
        return out

    def _validate_crawled_round(self, round_idx: int, sources: list[SearchSource]) -> None:
        valid_channels = {
            source.channel
            for source in sources
            if source.status == "ok" and source.url and source.excerpt.strip()
        }
        if len(valid_channels) < self.min_valid_channels_per_round:
            raise RuntimeError(
                f"选题研究第 {round_idx + 1} 轮抓取后有效渠道不足："
                f"{len(valid_channels)}/{self.min_valid_channels_per_round}"
            )

    @staticmethod
    def _round_payload(round_idx: int, query: str, sources: list[SearchSource]) -> dict:
        return {
            "round": round_idx + 1,
            "query": query,
            "channels_required": sorted(EXPECTED_CHANNELS),
            "channels_attempted": sorted({source.channel for source in sources}),
            "sources": [asdict(source) for source in sources],
        }

    @staticmethod
    def _summary(payloads: list[dict]) -> str:
        lines = ["# 选题研究摘要", "", "候选选题只能基于以下两轮研究生成。", ""]
        for payload in payloads:
            lines.extend([f"## 第 {payload['round']} 轮", "", f"查询：{payload['query']}", ""])
            for source in payload["sources"]:
                status = source.get("status", "fetch_failed")
                title = source.get("title") or "（无标题）"
                url = source.get("url") or "（无 URL）"
                excerpt = " ".join(str(source.get("excerpt") or "").split())[:500]
                lines.append(
                    f"- [{source.get('channel')}] {source.get('id')} {status}：{title}（{url}）"
                )
                if excerpt:
                    lines.append(f"  摘要：{excerpt}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def run(
        self,
        state,
        *,
        issue_dir: str,
        column: str,
        recent_issues: list[str],
        topic_seed: str | None = None,
    ):
        research_dir = Path(issue_dir) / "选题" / "研究"
        research_dir.mkdir(parents=True, exist_ok=True)

        payloads: list[dict] = []
        all_sources: list[SearchSource] = []
        prior_titles: list[str] = []
        for round_idx in range(self.rounds_max):
            path = research_dir / f"第{round_idx + 1}轮-搜索.json"
            if path.exists():
                payload = json.loads(path.read_text(encoding="utf-8"))
                sources = [SearchSource(**item) for item in payload.get("sources", [])]
                self._validate_attempts(round_idx, sources)
                self._validate_crawled_round(round_idx, sources)
                payloads.append(payload)
                all_sources.extend(sources)
                prior_titles.extend(source.title for source in sources if source.title)
                continue

            query = self.build_query(
                column=column,
                round_idx=round_idx,
                topic_seed=topic_seed,
                prior_titles=prior_titles,
            )
            # recent_issues 进入查询上下文，避免候选研究重复旧期；不把其原文写入日志。
            if recent_issues:
                query = f"{query} 排除已用主题数量 {len(recent_issues)}"
            print(f"正在进行选题研究第 {round_idx + 1}/2 轮：搜索 Tavily、Brave、Bing…", flush=True)
            searched = self.search.search(query, round_idx=round_idx)
            self._validate_attempts(round_idx, searched)
            seeds = self._select_seeds(searched)
            # 保留每个失败渠道的真实记录；成功结果只抓取受上限约束的种子 URL。
            seed_ids = {source.id for source in seeds}
            round_sources = seeds + [
                source for source in searched
                if source.status != "ok" and source.id not in seed_ids
            ]
            all_sources.extend(round_sources)
            prior_titles.extend(source.title for source in searched if source.title)
            payloads.append(self._round_payload(round_idx, query, round_sources))

        print("正在抓取两轮搜索结果中的网页正文…", flush=True)
        crawled = self.crawler.crawl(
            self._dedupe_seeds(all_sources),
            output_dir=str(research_dir / "抓取"),
        )
        crawled_by_id = {source.id: source for source in crawled}
        crawled_by_url = {source.url: source for source in crawled if source.url}
        for payload in payloads:
            updated: list[SearchSource] = []
            for raw in payload["sources"]:
                source = SearchSource(**raw)
                updated.append(crawled_by_id.get(source.id) or crawled_by_url.get(source.url, source))
            self._validate_crawled_round(payload["round"] - 1, updated)
            payload["sources"] = [asdict(source) for source in updated]
            payload["channels_attempted"] = sorted({source.channel for source in updated})
            (research_dir / f"第{payload['round']}轮-搜索.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        summary = self._summary(payloads)
        summary_path = research_dir / "研究摘要.md"
        summary_path.write_text(summary, encoding="utf-8")
        state = commit_stage(
            state,
            Path(issue_dir) / "运行记录",
            version_key="topic_research",
            text=summary,
        )
        return state, summary


__all__ = ["TopicResearchStage", "EXPECTED_CHANNELS"]
