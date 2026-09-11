"""证据收集（PLAN §3 步骤 2）。"""

from __future__ import annotations

import json
from pathlib import Path

from 工作台.接口 import SearchClient, SearchSource
from 工作台.流水线.checkpoint import commit_stage


class EvidenceCollectionStage:
    """调 search 拿证据 → ``资料/证据清单.json``。

    严格遵守接口规范 §2 + 配置 ``[pipeline].deep_search_*``：
    - 最多 2 轮深入检索；
    - 去重来源上限 30；
    - 站内深度 2 层。
    """

    def __init__(
        self,
        *,
        search: SearchClient,
        rounds_max: int = 2,
        unique_max: int = 30,
        site_depth_max: int = 2,
    ) -> None:
        if rounds_max < 1:
            raise ValueError("deep_search_rounds_max 必须 ≥ 1")
        self.search = search
        self.rounds_max = rounds_max
        self.unique_max = unique_max
        self.site_depth_max = site_depth_max

    def collect(
        self,
        topic: str,
        *,
        anchor_reports: list[str] | None = None,
    ) -> list[SearchSource]:
        seen: dict[str, SearchSource] = {}
        for r in range(self.rounds_max):
            if len(seen) >= self.unique_max:
                break
            batch = self.search.search(
                f"{topic} {' '.join(anchor_reports or [])}".strip(),
                round_idx=r,
            )
            for src in batch:
                if len(seen) >= self.unique_max:
                    break
                if src.id in seen:
                    continue
                fetched = self.search.fetch(src)
                seen[src.id] = fetched
        return list(seen.values())

    def render_anchor_md(self, anchor_reports: list[str]) -> str:
        body = ["# 锚点报告 · 版本核验", ""]
        for line in anchor_reports:
            body.append(f"- {line}")
        return "\n".join(body) + "\n"

    def run(self, state, *, issue_dir: str, topic: str, anchor_reports: list[str]):
        sources = self.collect(topic, anchor_reports=anchor_reports)
        if len(sources) > self.unique_max:
            sources = sources[: self.unique_max]
        usable_sources = [source for source in sources if source.status == "ok" and source.url]

        material_dir = Path(issue_dir) / "资料"
        material_dir.mkdir(parents=True, exist_ok=True)

        (material_dir / "锚点报告-版本核验.md").write_text(
            self.render_anchor_md(anchor_reports),
            encoding="utf-8",
        )

        evidence_payload = {
            "topic": topic,
            "snapshot_id": state.snapshot_id,
            "sources": [s.__dict__ for s in sources],
        }
        evidence_path = material_dir / "证据清单.json"
        evidence_path.write_text(
            json.dumps(evidence_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if not usable_sources:
            raise RuntimeError("检索未获得有效资料，已停止，不能继续策划和写稿")

        state = commit_stage(
            state,
            Path(issue_dir) / "运行记录",
            version_key="evidence_collection",
            text=evidence_path.read_text(encoding="utf-8"),
        )
        return state, sources


__all__ = ["EvidenceCollectionStage"]
