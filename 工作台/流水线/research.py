"""选题前研究：两轮三渠道搜索后抓取网页，再交给 planner 生成候选。"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from 工作台.接口 import CrawlClient, SearchClient, SearchSource
from 工作台.流水线.checkpoint import commit_stage


EXPECTED_CHANNELS = frozenset({"tavily", "brave", "bing"})


def _disabled_channels(search: SearchClient) -> set[str]:
    """返回本进程内被永久禁用的渠道；不存在该方法时按空集合处理。"""
    getter = getattr(search, "disabled_channels", None)
    if not callable(getter):
        return set()
    try:
        return set(getter()) or set()
    except Exception:  # noqa: BLE001 - 上报而非阻断：渠道元数据不该影响主流程
        return set()


class TopicResearchStage:
    """固定两轮调用 Tavily / Brave / Bing，并抓取搜索结果正文。"""

    def __init__(
        self,
        *,
        search: SearchClient,
        crawler: CrawlClient,
        rounds_max: int = 2,
        max_sources_per_round: int = 24,
        min_valid_channels_per_round: int = 2,
        min_sources_total: int = 0,
    ) -> None:
        if rounds_max != 2:
            raise ValueError("选题研究必须严格执行 2 轮")
        if max_sources_per_round < 1:
            raise ValueError("max_sources_per_round 必须大于 0")
        if not 1 <= min_valid_channels_per_round <= 3:
            raise ValueError("min_valid_channels_per_round 必须在 1–3 之间")
        if min_sources_total < 0:
            raise ValueError("min_sources_total 不能为负")
        self.search = search
        self.crawler = crawler
        self.rounds_max = rounds_max
        self.max_sources_per_round = max_sources_per_round
        self.min_valid_channels_per_round = min_valid_channels_per_round
        # 去重来源总下限；0 表示不启用（单测直接构造时默认关闭，生产由配置注入）。
        self.min_sources_total = min_sources_total

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

    def _validate_attempts(self, round_idx: int, sources: list[SearchSource]) -> None:
        attempted = {source.channel for source in sources}
        disabled = _disabled_channels(self.search)
        required = EXPECTED_CHANNELS - disabled
        missing = sorted(required - attempted)
        if missing:
            raise RuntimeError(
                f"选题研究第 {round_idx + 1} 轮未完成渠道调用：缺少 {', '.join(missing)}"
                + (f"（已禁用：{', '.join(sorted(disabled)) or '无'}）" if disabled else "")
            )

    def _select_seeds(
        self,
        sources: list[SearchSource],
        exclude_urls: frozenset[str] = frozenset(),
    ) -> list[SearchSource]:
        """按渠道轮转挑选种子，避免单一渠道占满配额；``exclude_urls`` 用于
        跨轮去重，防止第二轮种子名额被第一轮已收录的 URL 浪费。"""
        ok_by_channel: dict[str, list[SearchSource]] = {}
        seen: set[str] = set()
        for source in sources:
            if source.status != "ok" or not source.url:
                continue
            if source.url in seen or source.url in exclude_urls:
                continue
            seen.add(source.url)
            ok_by_channel.setdefault(source.channel, []).append(source)
        ordered_channels = [
            channel
            for channel in ("tavily", "brave", "bing", "ima")
            if channel in ok_by_channel
        ]
        ordered_channels += sorted(set(ok_by_channel) - set(ordered_channels))
        selected: list[SearchSource] = []
        while len(selected) < self.max_sources_per_round:
            progressed = False
            for channel in ordered_channels:
                queue = ok_by_channel.get(channel)
                if queue:
                    selected.append(queue.pop(0))
                    progressed = True
                    if len(selected) >= self.max_sources_per_round:
                        break
            if not progressed:
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

    # ---------------- 来源下限 ----------------

    @staticmethod
    def _round_paths(issue_dir: str | Path) -> list[Path]:
        research_dir = Path(issue_dir) / "选题" / "研究"
        return [research_dir / f"第{idx}轮-搜索.json" for idx in (1, 2)]

    @staticmethod
    def _unique_urls_from_payloads(payloads: list[dict]) -> set[str]:
        urls: set[str] = set()
        for payload in payloads:
            for source in payload.get("sources", []):
                url = str(source.get("url") or "").strip()
                if url:
                    urls.add(url)
        return urls

    def count_retrieved_sources(self, issue_dir: str | Path) -> int:
        """统计已落盘两轮研究中的去重来源数（按 URL）；文件缺失按 0 计。"""
        urls: set[str] = set()
        for path in self._round_paths(issue_dir):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for source in payload.get("sources", []):
                url = str(source.get("url") or "").strip()
                if url:
                    urls.add(url)
        return len(urls)

    def meets_source_floor(self, issue_dir: str | Path) -> bool:
        """已落盘研究是否达到去重来源下限；未启用下限时恒为 True。"""
        if self.min_sources_total <= 0:
            return True
        return self.count_retrieved_sources(issue_dir) >= self.min_sources_total

    def discard(self, issue_dir: str | Path) -> None:
        """作废已落盘的两轮研究与摘要；抓取正文缓存保留供诊断。"""
        research_dir = Path(issue_dir) / "选题" / "研究"
        for name in ("第1轮-搜索.json", "第2轮-搜索.json", "研究摘要.md"):
            try:
                (research_dir / name).unlink()
            except FileNotFoundError:
                pass

    def _validate_crawled_round(self, round_idx: int, sources: list[SearchSource]) -> None:
        # 两类"不可用"分别处理：
        # ① client 被永久禁用（如 Tavily 402、未配置）：从必需集合里直接剔除；
        # ② 本轮尝试过但零 ok 命中（如 Bing HTML 改版、MCP 端口未起、凭据失效）：
        #    也视为这一轮不可用，自动降级。下次重试可能恢复，仍照常记录供诊断。
        permanent_disabled = _disabled_channels(self.search)
        ok_channels: set[str] = set()
        attempted_channels: set[str] = set()
        for source in sources:
            attempted_channels.add(source.channel)
            if (
                source.channel not in permanent_disabled
                and source.status == "ok"
                and (source.url or source.channel == "ima")
                and source.excerpt.strip()
            ):
                ok_channels.add(source.channel)
        # "本轮可用渠道" = attempted − permanent_disabled − 本轮零命中。
        # 它是这一轮真正能为候选提供多样视角的渠道。
        dead_in_round = (attempted_channels - permanent_disabled) - ok_channels
        usable_in_round = attempted_channels - permanent_disabled - dead_in_round
        # 兜底：当所有渠道都被永久禁用或全部零命中时，跳过校验，避免空跑。
        # 此时把可用渠道集合放宽为 attempted（仅剔除永久禁用）。
        if not usable_in_round:
            usable_in_round = attempted_channels - permanent_disabled
            if not usable_in_round:
                return
        effective_min = min(self.min_valid_channels_per_round, len(usable_in_round))
        if len(ok_channels) < effective_min:
            raise RuntimeError(
                f"选题研究第 {round_idx + 1} 轮抓取后有效渠道不足："
                f"{len(ok_channels)}/{effective_min}"
                + (f"（已禁用：{', '.join(sorted(permanent_disabled)) or '无'}；"
                   f"本轮零命中：{', '.join(sorted(dead_in_round)) or '无'}）"
                   if permanent_disabled or dead_in_round else "")
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
                # 只有抓取成功的来源才能作为候选选题的证据指针。
                citable = status == "ok" and source.get("url")
                marker = "" if citable else "（抓取失败，不可引用）"
                lines.append(
                    f"- [{source.get('channel')}] {source.get('id')} {status}{marker}："
                    f"{title}（{url}）"
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
        set_output_dir = getattr(self.search, "set_output_dir", None)
        if callable(set_output_dir):
            set_output_dir(str(research_dir / "抓取"))

        # 来源下限：已落盘研究不达标时整体作废重检索，避免续跑带着"勉强够用"的
        # 旧数据进入策划阶段。
        if self.min_sources_total > 0 and not self.meets_source_floor(issue_dir):
            stale = any(path.exists() for path in self._round_paths(issue_dir))
            if stale:
                print(
                    f"已有选题研究仅检索到 {self.count_retrieved_sources(issue_dir)} 个来源，"
                    f"低于下限 {self.min_sources_total} 个，重新执行两轮检索…",
                    flush=True,
                )
                self.discard(issue_dir)

        payloads: list[dict] = []
        all_sources: list[SearchSource] = []
        prior_titles: list[str] = []
        seen_urls: set[str] = set()
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
                seen_urls.update(source.url for source in sources if source.url)
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
            # IMA 参考资料没有公开 URL；先由来源客户端取正文并落盘，公开 URL
            # 仍交给后面的 Scrapy 统一抓取。
            searched = [self.search.fetch(source) for source in searched]
            self._validate_attempts(round_idx, searched)
            # 跨轮去重：第二轮种子名额不要被第一轮已收录的 URL 浪费。
            seeds = self._select_seeds(searched, exclude_urls=frozenset(seen_urls))
            # 保留每个失败渠道的真实记录；成功结果只抓取受上限约束的种子 URL。
            seed_ids = {source.id for source in seeds}
            round_sources = seeds + [
                source for source in searched
                if (
                    source.id not in seed_ids
                    and (source.status != "ok" or source.channel == "ima")
                )
            ]
            all_sources.extend(round_sources)
            seen_urls.update(source.url for source in round_sources if source.url)
            prior_titles.extend(source.title for source in searched if source.title)
            payloads.append(self._round_payload(round_idx, query, round_sources))

        # 来源下限：两轮检索去重来源必须达到下限，否则落盘诊断并停止。
        retrieved_urls = self._unique_urls_from_payloads(payloads)
        disabled = _disabled_channels(self.search)
        if self.min_sources_total > 0 and len(retrieved_urls) < self.min_sources_total:
            counts: dict[str, int] = {}
            for payload in payloads:
                for source in payload["sources"]:
                    if source.get("status") == "ok":
                        channel = str(source.get("channel") or "?")
                        counts[channel] = counts.get(channel, 0) + 1
            detail = "，".join(
                f"{ch} {n} 条" for ch, n in sorted(counts.items())
            ) or "无有效结果"
            for payload in payloads:
                payload["disabled_channels"] = sorted(disabled)
                (research_dir / f"第{payload['round']}轮-搜索.json").write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            note = (
                f"\n\n> 注意：本轮仅检索到 {len(retrieved_urls)} 个去重来源，"
                f"低于下限 {self.min_sources_total} 个，流水线已停止；"
                f"各渠道命中：{detail}。\n"
            )
            (research_dir / "研究摘要.md").write_text(
                self._summary(payloads) + note, encoding="utf-8",
            )
            raise RuntimeError(
                f"选题研究仅检索到 {len(retrieved_urls)} 个去重来源，"
                f"低于要求的 {self.min_sources_total} 个（各渠道命中：{detail}），已停止。"
                "请检查 Tavily / Brave / Bing 渠道配置（额度/凭据/网络）后重试；"
                "也可在 配置/本地.toml [pipeline] 调整 topic_research_min_sources_total。"
            )

        print("正在抓取两轮搜索结果中的网页正文…", flush=True)
        crawled = self.crawler.crawl(
            self._dedupe_seeds(all_sources),
            output_dir=str(research_dir / "抓取"),
        )
        crawled_by_id = {source.id: source for source in crawled}
        crawled_by_url = {source.url: source for source in crawled if source.url}
        last_error: RuntimeError | None = None
        for payload in payloads:
            updated: list[SearchSource] = []
            for raw in payload["sources"]:
                source = SearchSource(**raw)
                updated.append(crawled_by_id.get(source.id) or crawled_by_url.get(source.url, source))
            try:
                self._validate_crawled_round(payload["round"] - 1, updated)
            except RuntimeError as exc:
                last_error = exc
                # 失败时也要把已经抓到的正文落盘，下次续跑可直接复用，
                # 避免 Tavily 等渠道禁用时整轮白跑。
                payload["sources"] = [asdict(source) for source in updated]
                payload["channels_attempted"] = sorted({source.channel for source in updated})
                payload["disabled_channels"] = sorted(disabled)
                (research_dir / f"第{payload['round']}轮-搜索.json").write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                continue
            payload["sources"] = [asdict(source) for source in updated]
            payload["channels_attempted"] = sorted({source.channel for source in updated})
            payload["disabled_channels"] = sorted(disabled)
            (research_dir / f"第{payload['round']}轮-搜索.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        if last_error is not None:
            # 把已落盘的中间结果提前汇总成 summary，再抛出原异常，
            # 让用户在配置文件/编辑注中能看到当前各渠道状态。
            summary = self._summary(payloads)
            (research_dir / "研究摘要.md").write_text(
                summary + "\n\n> 注意：本轮研究未通过有效渠道数校验，中间结果已落盘，"
                "可手工修整后从 menu 4 续跑。\n",
                encoding="utf-8",
            )
            raise last_error

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
