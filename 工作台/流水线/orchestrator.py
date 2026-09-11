"""一句话编排：阶段顺序 + checkpoint 调度。

各阶段以 ``StageXxx.run(...)`` 形式对外暴露；``Orchestrator.run_issue`` 把
PLAN §3 步骤 1–8 串成一次完整流水线（除步骤 8「用户导入手改稿」外）。

设计要点：
- 所有外部依赖（``ModelClient`` / ``SearchClient`` / ``UserInput``）由
  构造时注入；测试可替换为 stub。
- 阶段推进走 ``state.advance``；每个阶段结束 ``atomic_write_checkpoint``。
- 返修超限 → ``MaxRevisionsExceeded`` → 切到 ``awaiting_human``，不再调模型。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from 工作台.接口 import (
    CrawlClient,
    ModelClient,
    SearchClient,
    UserInput,
)
from 工作台.流水线.checkpoint import (
    VersionMixingError,
    atomic_write_checkpoint,
    load_checkpoint,
    verify_versions,
)
from 工作台.流水线.drafts import DraftsStage
from 工作台.流水线.evidence import EvidenceCollectionStage
from 工作台.流水线.finalizing import FinalizingStage
from 工作台.流水线.planning import PlanningStage, extract_angles
from 工作台.流水线.review import ReviewStage, has_blocking_issue
from 工作台.流水线.revise import MaxRevisionsExceeded, ReviseStage
from 工作台.流水线.research import TopicResearchStage
from 工作台.流水线.state import (
    FINALIZING,
    STAGE_ORDER,
    advance,
    rerun as mark_rerun,
    resume_after_rerun,
)
from 工作台.流水线.topic_selection import TopicSelectionStage


class Orchestrator:
    """把流水线 1→8 步骤串起来。"""

    def __init__(
        self,
        *,
        issue_id: str,
        issue_dir: str,
        snapshot_id: str,
        planner: ModelClient,
        writer: ModelClient,
        reviewer: ModelClient,
        search: SearchClient,
        user: UserInput,
        crawler: CrawlClient | None = None,
        column: str,
        topic_seed: str | None = None,
        recent_issues: Iterable[str] = (),
        anchor_reports: Iterable[str] = (),
        revision_rounds_max: int = 2,
        deep_search_rounds_max: int = 2,
        deep_search_unique_max: int = 30,
        site_depth_max: int = 2,
        topic_research_rounds_max: int = 2,
        topic_research_sources_max_per_round: int = 6,
        topic_research_min_valid_channels: int = 2,
    ) -> None:
        self.issue_id = issue_id
        self.issue_dir = issue_dir
        self.snapshot_id = snapshot_id
        self.topic_seed = topic_seed
        self.column = column
        self.recent_issues = list(recent_issues)
        self.anchor_reports = list(anchor_reports)
        self.revision_rounds_max = revision_rounds_max

        self.topic_research_stage = (
            TopicResearchStage(
                search=search,
                crawler=crawler,
                rounds_max=topic_research_rounds_max,
                max_sources_per_round=topic_research_sources_max_per_round,
                min_valid_channels_per_round=topic_research_min_valid_channels,
            )
            if crawler is not None else None
        )

        self.topic_stage = TopicSelectionStage(
            planner=planner,
            user=user,
            snapshot_id=snapshot_id,
            require_research=crawler is not None,
        )
        self.evidence_stage = EvidenceCollectionStage(
            search=search,
            crawler=crawler,
            require_crawl=crawler is not None,
            rounds_max=deep_search_rounds_max,
            unique_max=deep_search_unique_max,
            site_depth_max=site_depth_max,
        )
        self.planning_stage = PlanningStage(planner=planner, snapshot_id=snapshot_id)
        self.drafts_stage = DraftsStage(writer=writer, snapshot_id=snapshot_id)
        self.review_stage = ReviewStage(
            reviewer=reviewer, snapshot_id=snapshot_id, column=column,
        )
        self.revise_stage = ReviseStage(
            writer=writer,
            reviewer=reviewer,
            snapshot_id=snapshot_id,
            revision_rounds_max=revision_rounds_max,
            column=column,
        )
        self.finalizing_stage = FinalizingStage(writer=writer, snapshot_id=snapshot_id)

    # ---------------- 状态存取 ----------------

    def load_state(self):
        log_dir = Path(self.issue_dir) / "运行记录"
        ckpt = load_checkpoint(log_dir)
        if ckpt is None:
            from 工作台.接口 import TaskState
            return TaskState(
                issue_id=self.issue_id,
                stage="topic_research" if self.topic_research_stage is not None else "topic_selection",
                snapshot_id=self.snapshot_id,
            )
        return ckpt

    def save_state(self, state) -> None:
        atomic_write_checkpoint(state, Path(self.issue_dir) / "运行记录")

    # ---------------- 主流程 ----------------

    def run_issue(self):
        state = self.load_state()
        if state.stage in ("finalizing", "archived", "awaiting_human"):
            return state

        if state.stage not in ("topic_research", "topic_selection"):
            self._selected_topic()  # 恢复也必须有明确选题，禁止栏目名兜底。

        # 1) 选题前研究：两轮各调用 Tavily / Brave / Bing，再用 Scrapy 抓取。
        if state.stage == "topic_research":
            if self.topic_research_stage is None:
                raise RuntimeError("缺少 Scrapy 选题研究客户端，不能生成候选选题")
            state, _summary = self.topic_research_stage.run(
                state,
                issue_dir=self.issue_dir,
                column=self.column,
                recent_issues=self.recent_issues,
                topic_seed=self.topic_seed,
            )

        # 2) 选题
        if state.stage == "topic_selection":
            state, _md = self.topic_stage.run(
                state,
                issue_dir=self.issue_dir,
                column=self.column,
                recent_issues=self.recent_issues,
            )

        # 3) 证据
        if state.stage == "evidence_collection":
            topic = self._selected_topic()
            state, _sources = self.evidence_stage.run(
                state,
                issue_dir=self.issue_dir,
                topic=topic,
                anchor_reports=self.anchor_reports,
            )

        # 4) 策划
        if state.stage == "planning":
            evidence_ids = self._collect_evidence_ids()
            topic = self._selected_topic()
            state, _plan = self.planning_stage.run(
                state,
                issue_dir=self.issue_dir,
                topic=topic,
                evidence_summary="\n".join(evidence_ids),
            )

        # 5) 三稿
        if state.stage in ("draft_1", "draft_2", "draft_3"):
            plan_text = self._read(Path(self.issue_dir) / "策划" / "三角度策划.md")
            angles = extract_angles(plan_text)
            evidence_ids = self._collect_evidence_ids()
            topic = self._selected_topic()
            state, _paths = self.drafts_stage.run(
                state,
                issue_dir=self.issue_dir,
                topic=topic,
                angles=angles,
                plan_text=plan_text,
                evidence_ids=evidence_ids,
            )

        # 6) 初轮审稿
        if state.stage == "review_1":
            drafts = self._read_drafts()
            state, verdicts, rec = self.review_stage.run(
                state,
                issue_dir=self.issue_dir,
                drafts=drafts,
                previous_verdict=None,
                review_round=1,
            )
            state = self._enter_post_review(state, rec)
            self.save_state(state)

        # 6) 返修循环（含 review_2）
        if state.stage in ("revise_1", "review_2", "revise_2"):
            state = self._run_revise_loop(state)

        # 7) finalizing（审稿通过 + 返修 ≤ 上限时）
        if state.stage == FINALIZING or (
            state.stage == STAGE_ORDER[-1] and self._last_verdict_passed()
        ):
            state = self._finalize(state)

        self.save_state(state)
        return state

    # ---------------- 子流程 ----------------

    def _enter_post_review(self, state, rec):
        """review_1 之后的去向：未阻断 → revise_1；通过 → 直接 finalizing。"""
        if rec.pass_:
            state = advance(state, event="finalizing")
            return state
        state = advance(state)  # 进入 revise_1
        return state

    def _run_revise_loop(self, state):
        verdict = self._load_latest_verdict()
        rec_text, rec_verdict = self._recommended_draft_and_verdict(verdict)
        draft_text = rec_text

        try:
            state, draft_text, new_verdict = self.revise_stage.run(
                state,
                issue_dir=self.issue_dir,
                draft_text=draft_text,
                verdict=rec_verdict,
                draft_version=rec_verdict.recommendation,
            )
        except MaxRevisionsExceeded:
            # 超限 → 切到 awaiting_human；不再调模型
            state = advance(state, event="await_human")
            self.save_state(state)
            return state

        # 复审通过 → 进 finalizing
        if new_verdict.pass_:
            self._persist_revised(state, draft_text, new_verdict)
            state = advance(state, event="finalizing")
            return state
        return state

    def _finalize(self, state):
        verdict = self._load_latest_verdict()
        rec_text, rec_verdict = self._recommended_draft_and_verdict(verdict)
        evidence_ids = self._collect_evidence_ids()
        source_titles = self._collect_source_titles()
        state, _paths = self.finalizing_stage.run(
            state,
            issue_dir=self.issue_dir,
            draft_text=rec_text,
            verdict=rec_verdict,
            source_titles=source_titles,
            evidence_citations=evidence_ids,
        )
        return state

    # ---------------- 辅助 ----------------

    def _selected_topic(self) -> str:
        path = Path(self.issue_dir) / "选题" / "选定.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                topic = data.get("topic") if isinstance(data, dict) else None
                if isinstance(topic, str) and topic.strip():
                    return topic.strip()
            except json.JSONDecodeError:
                pass
        raise ValueError("尚未选择选题，不能继续；请先返回选题阶段完成选择")

    def _collect_evidence_ids(self) -> list[str]:
        path = Path(self.issue_dir) / "资料" / "证据清单.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return [s.get("id", "") for s in data.get("sources", []) if s.get("id")]

    def _collect_source_titles(self) -> list[str]:
        import json
        path = Path(self.issue_dir) / "资料" / "证据清单.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return [s.get("title", "") for s in data.get("sources", []) if s.get("title")]

    def _read_drafts(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for i in (1, 2, 3):
            p = Path(self.issue_dir) / "三篇初稿" / f"初稿-{i}.md"
            if p.exists():
                out.append((f"draft_{i}", p.read_text(encoding="utf-8")))
        return out

    def _read(self, p: Path) -> str:
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def _load_latest_verdict(self):
        """读取 ``审稿-复审.json``，不存在则回退 ``审稿-初轮.json``。"""
        from 工作台.接口 import ReviewVerdict, ReviewIssue

        for fname in ("审稿-复审.json", "审稿-初轮.json"):
            path = Path(self.issue_dir) / "审稿与返修" / fname
            if not path.exists():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            rec_raw = data.get("recommendation") or {}
            issues = [
                ReviewIssue(
                    severity=i.get("severity", "minor"),
                    category=i.get("category", "other"),
                    location=i.get("location", ""),
                    description=i.get("description", ""),
                    evidence_source_ids=list(i.get("evidence_source_ids", [])),
                    suggestion=i.get("suggestion"),
                )
                for i in rec_raw.get("issues", [])
            ]
            return ReviewVerdict(
                draft_version=rec_raw.get("draft_version", "draft_1"),
                issues=issues,
                score=float(rec_raw.get("score", 0.0)),
                recommendation=rec_raw.get("recommendation", "draft_1"),
                pass_=bool(rec_raw.get("pass_", False)),
            )
        # 没有审稿结果 → 视为阻断
        return ReviewVerdict(pass_=False, issues=[
            ReviewIssue(severity="block", category="unsupported_key_fact",
                        location="审稿缺失", description="未找到任何审稿结果")
        ])

    def _recommended_draft_and_verdict(self, verdict):
        """优先取返修稿；否则按 draft_version / recommendation 取初稿。"""
        revised = Path(self.issue_dir) / "审稿与返修" / "推荐修订.md"
        if revised.exists():
            return revised.read_text(encoding="utf-8"), verdict
        rec = verdict.draft_version or verdict.recommendation
        idx = {"draft_1": 1, "draft_2": 2, "draft_3": 3}.get(rec, 1)
        path = Path(self.issue_dir) / "三篇初稿" / f"初稿-{idx}.md"
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        return text, verdict

    def _last_verdict_passed(self) -> bool:
        return self._load_latest_verdict().pass_

    def _persist_revised(self, state, draft_text: str, verdict) -> None:
        """复审通过时把修订稿落到磁盘，供 finalizing 复用。"""
        from 工作台.流水线.checkpoint import record_version

        review_dir = Path(self.issue_dir) / "审稿与返修"
        review_dir.mkdir(parents=True, exist_ok=True)
        (review_dir / "推荐修订.md").write_text(draft_text, encoding="utf-8")
        new_state = record_version(state, "draft_recommended", draft_text)
        self.save_state(new_state)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _parse_column(issue_id: str) -> str:
    parts = issue_id.split("-")
    return "-".join(parts[6:]) if len(parts) > 6 else issue_id


def _find_issue_dir(issue_id: str, issue_root: str | Path | None = None) -> Path:
    if issue_root is not None:
        return Path(issue_root)
    return _repo_root() / "进行中" / issue_id


def build_orchestrator(issue_root: str | Path, *, user=None) -> Orchestrator:
    """按本地配置组装真实客户端。测试可注入 ``user``；缺密钥时由 ModelClient 抛 AuthError。"""
    from 工作台.接入.config import ConfigError, load_default_config, load_local_config
    from 工作台.接入.envfile import load_env_files
    from 工作台.接入.models.client import ModelClient
    from 工作台.接入.search.composite import CompositeSearch
    from 工作台.接入.search.scrapy_crawler import ScrapyCrawler
    from 工作台.流水线.cli_user import CliUser

    root = _repo_root()
    load_env_files(root)
    try:
        cfg = load_local_config(root)
    except ConfigError:
        cfg = load_default_config(root)
    issue_path = Path(issue_root)
    issue_id = issue_path.name
    pipe = cfg.pipeline
    return Orchestrator(
        issue_id=issue_id,
        issue_dir=str(issue_path),
        snapshot_id=str((root / "配置" / "本期.toml").resolve()),
        planner=ModelClient(cfg.models["planner"]),
        writer=ModelClient(cfg.models["writer"]),
        reviewer=ModelClient(cfg.models["reviewer"]),
        search=CompositeSearch(cfg),
        user=user or CliUser(),
        crawler=ScrapyCrawler(
            depth_limit=pipe.site_depth_max if pipe else 1,
            max_pages=pipe.scrapy_max_pages if pipe else 36,
        ),
        column=_parse_column(issue_id),
        revision_rounds_max=pipe.revision_rounds_max if pipe else 2,
        deep_search_rounds_max=pipe.deep_search_rounds_max if pipe else 2,
        deep_search_unique_max=pipe.deep_search_unique_sources_max if pipe else 30,
        site_depth_max=pipe.site_depth_max if pipe else 2,
        topic_research_rounds_max=pipe.topic_research_rounds_max if pipe else 2,
        topic_research_sources_max_per_round=pipe.topic_research_sources_max_per_round if pipe else 6,
        topic_research_min_valid_channels=pipe.topic_research_min_valid_channels if pipe else 2,
    )


def resume(*, issue_root, stage=None, orchestrator=None, user=None, **_):
    """菜单 2 入口：从 checkpoint 续跑。"""
    root = Path(issue_root)
    orch = orchestrator or build_orchestrator(root, user=user)
    state = orch.load_state()
    current = {}
    for key, rel in (
        ("topic_research", Path("选题") / "研究" / "研究摘要.md"),
        ("topic_selection", Path("选题") / "选题-候选.md"),
        ("planning", Path("策划") / "三角度策划.md"),
    ):
        path = root / rel
        if path.exists():
            from 工作台.流水线.checkpoint import file_hash
            current[key] = file_hash(path)
    if state.rerun_invalidated:
        resume_after_rerun(state, current)
    return orch.run_issue()


def rerun(*, issue_id, upstream, invalidate=None, issue_root=None, orchestrator=None, user=None, **_):
    """菜单 4 入口：把阶段打回 upstream 并续跑。"""
    root = _find_issue_dir(issue_id, issue_root)
    orch = orchestrator or build_orchestrator(root, user=user)
    state = orch.load_state()
    state = mark_rerun(state, upstream)
    orch.save_state(state)
    return orch.run_issue()


__all__ = ["Orchestrator", "build_orchestrator", "resume", "rerun"]
