"""4 类必阻断独立用例；``score=100`` 也不通过。"""

from __future__ import annotations

import unittest

from 工作台.接口 import ReviewIssue, ReviewVerdict
from 工作台.流水线.review import (
    BLOCK_CATEGORIES,
    compute_pass,
    has_blocking_issue,
)


def _verdict(category: str, *, score: float = 100.0) -> ReviewVerdict:
    return ReviewVerdict(
        draft_version="draft_1",
        issues=[ReviewIssue(severity="block", category=category,
                            location="loc", description="desc")],
        score=score,
        recommendation="draft_1",
        pass_=True,  # 故意设 True；compute_pass 必须覆盖
    )


class BlockCategoryTests(unittest.TestCase):
    def test_block_categories_complete(self):
        # 与接口规范 §3 字面量一致
        self.assertEqual(
            set(BLOCK_CATEGORIES),
            {
                "fabricated_citation",
                "unsupported_key_fact",
                "out_of_scope_sample",
                "fake_personal_experience",
            },
        )

    def test_fabricated_citation_blocks_even_with_score_100(self):
        v = _verdict("fabricated_citation", score=100)
        self.assertTrue(has_blocking_issue(v))
        v2 = compute_pass(v)
        self.assertFalse(v2.pass_)
        # 评分不得救活
        self.assertEqual(v2.score, 100.0)

    def test_unsupported_key_fact_blocks_even_with_score_100(self):
        v = _verdict("unsupported_key_fact", score=100)
        v2 = compute_pass(v)
        self.assertFalse(v2.pass_)
        self.assertEqual(v2.score, 100.0)

    def test_out_of_scope_sample_blocks_even_with_score_100(self):
        v = _verdict("out_of_scope_sample", score=100)
        v2 = compute_pass(v)
        self.assertFalse(v2.pass_)
        self.assertEqual(v2.score, 100.0)

    def test_fake_personal_experience_blocks_even_with_score_100(self):
        v = _verdict("fake_personal_experience", score=100)
        v2 = compute_pass(v)
        self.assertFalse(v2.pass_)
        self.assertEqual(v2.score, 100.0)


class NonBlockingIssueTests(unittest.TestCase):
    def test_major_issue_does_not_block(self):
        v = ReviewVerdict(
            draft_version="draft_1",
            issues=[ReviewIssue(severity="major", category="tone")],
            score=80,
            recommendation="draft_1",
            pass_=True,
        )
        v2 = compute_pass(v)
        self.assertTrue(v2.pass_)

    def test_block_severity_always_blocks(self):
        # 接口规范 §3：severity == block 条数 > 0 → pass_=False
        v = ReviewVerdict(
            draft_version="draft_1",
            issues=[ReviewIssue(severity="block", category="tone")],
            score=70,
            recommendation="draft_1",
            pass_=True,
        )
        v2 = compute_pass(v)
        self.assertFalse(v2.pass_)

    def test_required_category_blocks_even_if_marked_major(self):
        v = ReviewVerdict(
            draft_version="draft_1",
            issues=[ReviewIssue(severity="major", category="fabricated_citation")],
            score=99,
            recommendation="draft_1",
            pass_=True,
        )
        v2 = compute_pass(v)
        self.assertFalse(v2.pass_)


if __name__ == "__main__":
    unittest.main()
