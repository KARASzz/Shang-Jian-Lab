"""5 号导入定稿不覆盖既有定稿（除非用户显式确认）。"""

from __future__ import annotations

import unittest

from 工作台.菜单.screens import import_final


def _seed_simple_issue(repo, issue_id: str) -> "Path":
    issue_root = repo.in_progress() / issue_id
    (issue_root / "待定稿").mkdir(parents=True)
    return issue_root


class ImportFinalTests(unittest.TestCase):
    def test_no_confirm_blocks_existing(self) -> None:
        """目标位置已有同名定稿；不通过回调确认 → PermissionError。"""

        from 工作台.菜单.tests._harness import TempRepo

        with TempRepo() as repo:
            issue_root = _seed_simple_issue(repo, "2026-09-09-14-34-16-大模型二三事")
            existing = issue_root / "待定稿" / "熵减进化室-公众号成稿-《智能变得廉价》.md"
            existing.write_text("旧版正文", encoding="utf-8")

            # 用户源稿使用与既有定稿**同名**的文件名。
            src = repo.root / "熵减进化室-公众号成稿-《智能变得廉价》.md"
            src.write_text("新版正文", encoding="utf-8")

            with self.assertRaises(PermissionError):
                import_final.import_final(
                    src,
                    issue_root,
                    confirm_callback=lambda *a, **k: False,
                )
            # 既有定稿必须原封不动。
            self.assertEqual(existing.read_text(encoding="utf-8"), "旧版正文")

    def test_explicit_confirm_overwrites(self) -> None:
        from 工作台.菜单.tests._harness import TempRepo

        with TempRepo() as repo:
            issue_root = _seed_simple_issue(repo, "2026-09-09-14-34-16-大模型二三事")
            existing = issue_root / "待定稿" / "熵减进化室-公众号成稿-《智能变得廉价》.md"
            existing.write_text("旧版正文", encoding="utf-8")
            src = repo.root / "熵减进化室-公众号成稿-《智能变得廉价》.md"
            src.write_text("新版正文", encoding="utf-8")

            result = import_final.import_final(
                src,
                issue_root,
                confirm_callback=lambda *a, **k: True,
            )
            self.assertTrue(result.overwrote)
            self.assertTrue(import_final.is_final_filename(src.name))
            self.assertEqual(existing.read_text(encoding="utf-8"), "新版正文")

    def test_final_filename_recognized(self) -> None:
        self.assertTrue(import_final.is_final_filename("熵减进化室-公众号成稿-《智能变得廉价》.md"))
        self.assertFalse(import_final.is_final_filename("熵减进化室-公众号成稿.md"))


if __name__ == "__main__":
    unittest.main()