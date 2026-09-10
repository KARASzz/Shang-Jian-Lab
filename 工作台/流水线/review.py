"""审稿（PLAN §3 步骤 5、复审步骤 6；接口规范 §3）。

4 类必阻断（``fabricated_citation / unsupported_key_fact / out_of_scope_sample /
fake_personal_experience``）任一触发即 ``pass_=False``；``score`` 仅作显示，
不参与通过判定。
"""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path

from 工作台.接口 import (
    ModelClient,
    ModelRequest,
    ReviewCategory,
    ReviewIssue,
    ReviewVerdict,
)


# 接口规范 §3 必阻断类别（与 配置/默认.toml ``[review]`` 完全一致）。
BLOCK_CATEGORIES: tuple[ReviewCategory, ...] = (
    "fabricated_citation",
    "unsupported_key_fact",
    "out_of_scope_sample",
    "fake_personal_experience",
)


def has_blocking_issue(verdict: ReviewVerdict) -> bool:
    """任一阻断类出现 → 阻断；``score`` 不得救活。"""
    return any(
        issue.severity == "block" and issue.category in BLOCK_CATEGORIES
        for issue in verdict.issues
    )


def compute_pass(verdict: ReviewVerdict) -> ReviewVerdict:
    """强制重算 ``pass_``，屏蔽任何把 score 抬到通过的实现。"""
    return replace(verdict, pass_=not has_blocking_issue(verdict))


class ReviewStage:
    """调 reviewer 审稿。"""

    def __init__(
        self,
        *,
        reviewer: ModelClient,
        snapshot_id: str,
        block_categories: tuple[ReviewCategory, ...] = BLOCK_CATEGORIES,
    ) -> None:
        self.reviewer = reviewer
        self.snapshot_id = snapshot_id
        self.block_categories = block_categories

    def build_request(
        self,
        *,
        draft_path: str,
        draft_text: str,
        previous_verdict: ReviewVerdict | None,
    ) -> ModelRequest:
        messages: list[dict] = [
            {"role": "system", "content": "reviewer-system"},
            {"role": "user", "content": f"稿件：{draft_path}\n\n{draft_text}"},
        ]
        if previous_verdict is not None:
            messages.append({
                "role": "user",
                "content": (
                    "上一轮 ReviewVerdict：\n"
                    + json.dumps(asdict(previous_verdict), ensure_ascii=False)
                    + "\n请逐条给出处理结果（已修 / 不修并说明）。"
                ),
            })
        return ModelRequest(
            role="reviewer",
            messages=messages,
            temperature=0.2,
            request_model="glm-5.1",
            snapshot_id=self.snapshot_id,
        )

    def parse_verdict(
        self,
        text: str,
        *,
        draft_version: str,
    ) -> ReviewVerdict:
        """骨架解析：信任外部 reviewer 输出 JSON；占位直接还原字段。

        真实解析应基于 reviewer-system 提示词约定的 JSON Schema；骨架里
        仅做兜底（mock-friendly），禁止在解析阶段掩盖阻断类。
        """
        try:
            data = json.loads(text)
            issues = [
                ReviewIssue(
                    severity=item.get("severity", "minor"),
                    category=item.get("category", "other"),
                    location=item.get("location", ""),
                    description=item.get("description", ""),
                    evidence_source_ids=list(item.get("evidence_source_ids", [])),
                    suggestion=item.get("suggestion"),
                )
                for item in data.get("issues", [])
            ]
            return compute_pass(ReviewVerdict(
                draft_version=draft_version,
                issues=issues,
                score=float(data.get("score", 0.0)),
                recommendation=data.get("recommendation", "draft_1"),
                pass_=False,
            ))
        except (ValueError, KeyError, TypeError):
            # 解析失败按 0 分 + 全阻断处理；不静默通过
            return compute_pass(ReviewVerdict(
                draft_version=draft_version,
                issues=[ReviewIssue(
                    severity="block",
                    category="unsupported_key_fact",
                    location="全文",
                    description="审稿输出无法解析，按阻断处理",
                )],
                score=0.0,
                recommendation="draft_1",
                pass_=False,
            ))

    def review_drafts(
        self,
        drafts: list[tuple[str, str]],
        *,
        previous_verdict: ReviewVerdict | None = None,
    ) -> list[ReviewVerdict]:
        """对 3 篇初稿各做一次独立审查。"""
        verdicts: list[ReviewVerdict] = []
        for version, text in drafts:
            req = self.build_request(
                draft_path=version,
                draft_text=text,
                previous_verdict=previous_verdict,
            )
            resp = self.reviewer.chat(req)
            verdicts.append(self.parse_verdict(resp.text, draft_version=version))
        return verdicts

    def recommend(self, verdicts: list[ReviewVerdict]) -> ReviewVerdict:
        """选推荐稿：未阻断且评分最高者。"""
        candidates = [v for v in verdicts if v.pass_]
        if not candidates:
            return max(verdicts, key=lambda v: v.score)
        return max(candidates, key=lambda v: v.score)

    def run(
        self,
        state,
        *,
        issue_dir: str,
        drafts: list[tuple[str, str]],
        previous_verdict: ReviewVerdict | None = None,
        review_round: int = 1,
    ):
        verdicts = self.review_drafts(drafts, previous_verdict=previous_verdict)
        rec = self.recommend(verdicts)

        review_dir = Path(issue_dir) / "审稿与返修"
        review_dir.mkdir(parents=True, exist_ok=True)
        suffix = "初轮" if review_round == 1 else "复审"
        (review_dir / f"审稿-{suffix}.json").write_text(
            json.dumps(
                {
                    "round": review_round,
                    "verdicts": [v.__dict__ for v in verdicts],
                    "recommendation": rec.__dict__,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        # 不在这里推进阶段；revise.py 决定下一阶段（revise_1 / review_2 / finalizing / awaiting_human）
        return state, verdicts, rec


__all__ = [
    "BLOCK_CATEGORIES",
    "has_blocking_issue",
    "compute_pass",
    "ReviewStage",
]
