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

from dataclasses import replace
from pathlib import Path
from typing import Iterable

from 工作台.接口 import (
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
from 工作台.流水线.planning import PlanningStage
from 工作台.流水线.review import ReviewStage, has_blocking_issue
from 工作台.流水线.revise import MaxRevisionsExceeded, ReviseStage
from 工作台.流水线.state import (
    FINALIZING,
    STAGE_ORDER,
    advance,
    rerun,
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
        column: str,
        topic_seed: str | None = None,
        recent_issues: Iterable[str] = (),
        anchor_reports: Iterable[str] = (),
        revision_rounds_max: int = 2,
        deep_search_rounds_max: int = 2,
        deep_search_unique_max: int = 30,
        site_depth_max: int = 2,
    ) -> None:
        self.issue_id = issue_id
        self.issue_dir = issue_dir
        self.snapshot_id = snapshot_id
        self.topic_seed = topic_seed
        self.column = column
        self.recent_issues = list(recent_issues)
        self.anchor_reports = list(anchor_reports)
        self.revision_rounds_max = revision_rounds_max

        self.topic_stage = TopicSelectionStage(
            planner=planner, user=user, snapshot_id=snapshot_id,
        )
        self.evidence_stage = EvidenceCollectionStage(
            search=search,
            rounds_max=deep_search_rounds_max,
            unique_max=deep_search_unique_max,
            site_depth_max=site_depth_max,
        )
        self.planning_stage = PlanningStage(planner=planner, snapshot_id=snapshot_id)
        self.drafts_stage = DraftsStage(writer=writer, snapshot_id=snapshot_id)
        self.review_stage = ReviewStage(reviewer=reviewer, snapshot_id=snapshot_id)
        self.revise_stage = ReviseStage(
            writer=writer,
            reviewer=reviewer,
            snapshot_id=snapshot_id,
            revision_rounds_max=revision_rounds_max,
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
                stage="topic_selection",
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

        # 1) 选题
        if state.stage == "topic_selection":
            state, _md = self.topic_stage.run(
                state,
                issue_dir=self.issue_dir,
                column=self.column,
                recent_issues=self.recent_issues,
            )

        # 2) 证据
        if state.stage == "evidence_collection":
            topic = self.topic_seed or self.column
            state, _sources = self.evidence_stage.run(
                state,
                issue_dir=self.issue_dir,
                topic=topic,
                anchor_reports=self.anchor_reports,
            )

        # 3) 策划
        if state.stage == "planning":
            plan_path = Path(self.issue_dir) / "策划" / "三角度策划.md"
            plan_text = plan_path.read_text(encoding="utf-8") if plan_path.exists() else ""
            angles = self._extract_angles(plan_text)
            evidence_ids = self._collect_evidence_ids()
            topic = self.topic_seed or self.column
            state, _plan = self.planning_stage.run(
                state,
                issue_dir=self.issue_dir,
                topic=topic,
                evidence_summary="\n".join(evidence_ids),
            )

        # 4) 三稿
        if state.stage in ("draft_1", "draft_2", "draft_3"):
            plan_text = self._read(Path(self.issue_dir) / "策划" / "三角度策划.md")
            angles = self._extract_angles(plan_text)
            evidence_ids = self._collect_evidence_ids()
            topic = self.topic_seed or self.column
            state, _paths = self.drafts_stage.run(
                state,
                issue_dir=self.issue_dir,
                topic=topic,
                angles=angles,
                plan_text=plan_text,
                evidence_ids=evidence_ids,
            )

        # 5) 初轮审稿
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

        # 6) 返修循环（含 review_2）
        if state.stage in ("revise_1", "review_2", "revise_2"):
            state = self._run_revise_loop(state)

        # 7) finalizing（审稿通过 + 返修 ≤ 上限时）
        if state.stage == FINALIZING or (
            state.stage == STAGE_ORDER[-1] and self._last_verdict_passed()
        ):
            state = self._finalize(state)

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
        # 先找到最近一次 verdict
        verdict = self._last_verdict() if hasattr(self, "_last_verdict") else None
        # 简化：从 review json 中读
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

    def _extract_angles(self, plan_text: str) -> list[str]:
        """骨架解析：每个一级或二级标题视为一个角度；不足 3 个回退到占位。"""
        angles = [
            line.strip("# ").strip()
            for line in plan_text.splitlines()
            if line.strip().startswith("#") and line.strip().lstrip("#").strip()
        ]
        while len(angles) < 3:
            angles.append(f"占位角度 {len(angles) + 1}")
        return angles[:3]

    def _collect_evidence_ids(self) -> list[str]:
        import json
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
        import json
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
        """根据 verdict.recommendation 取初稿正文。"""
        from 工作台.接口 import ReviewVerdict
        rec = verdict.recommendation
        idx = {"draft_1": 1, "draft_2": 2, "draft_3": 3}.get(rec, 1)
        path = Path(self.issue_dir) / "三篇初稿" / f"初稿-{idx}.md"
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        return text, verdict

    def _last_verdict_passed(self) -> bool:
        return self._load_latest_verdict().pass_

    def _persist_revised(self, state, draft_text: str, verdict) -> None:
        """复审通过时把修订稿覆盖推荐稿位置，供 finalizing 复用。"""
        from 工作台.流水线.checkpoint import record_version
        new_state = record_version(state, "draft_recommended", draft_text)
        self.save_state(new_state)


__all__ = ["Orchestrator"]
