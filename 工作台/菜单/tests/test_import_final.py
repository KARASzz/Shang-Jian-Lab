"""5 号导入定稿不覆盖既有定稿（除非用户显式确认）。"""

from __future__ import annotations

import unittest
import io
from unittest.mock import patch

from 工作台.菜单.screens import import_final


def _seed_simple_issue(repo, issue_id: str) -> "Path":
    issue_root = repo.in_progress() / issue_id
    (issue_root / "待定稿").mkdir(parents=True)
    return issue_root


class _RunIO:
    def __init__(self) -> None:
        self.out = io.StringIO()

    def println(self, text: str = "") -> None:
        self.out.write(text + "\n")

    def print(self, text: str) -> None:
        self.out.write(text)

    def read_line(self) -> str:
        return ""


class ImportFinalTests(unittest.TestCase):
    def test_y_auto_names_recommendation_and_archives(self) -> None:
        from 工作台.菜单.tests._harness import TempRepo

        with TempRepo() as repo:
            issue_id = "2026-09-09-14-34-16-大模型二三事"
            issue_root = _seed_simple_issue(repo, issue_id)
            (issue_root / "待定稿" / "推荐稿.md").write_text(
                "# 评测榜第一为何无法复现\n\n正文", encoding="utf-8"
            )
            output = _RunIO()
            prompt_file = repo.archive() / issue_id / "待定稿" / (
                "熵减进化室-公众号成稿-《评测榜第一为何无法复现》-配图提示词.md"
            )
            with patch.object(import_final.prompt, "confirm", return_value=True), patch(
                "工作台.流水线.image_prompts.generate_image_prompt_file",
                return_value=prompt_file,
            ):
                import_final.run(output)

            archived = repo.archive() / issue_id / "待定稿" / (
                "熵减进化室-公众号成稿-《评测榜第一为何无法复现》.md"
            )
            self.assertTrue(archived.exists())
            self.assertFalse(issue_root.exists())
            self.assertIn("已完成归档", output.out.getvalue())
            self.assertIn("三张图的一条总提示词已写入", output.out.getvalue())

    def test_n_leaves_recommendation_untouched(self) -> None:
        from 工作台.菜单.tests._harness import TempRepo

        with TempRepo() as repo:
            issue_id = "2026-09-09-14-34-16-大模型二三事"
            issue_root = _seed_simple_issue(repo, issue_id)
            recommendation = issue_root / "待定稿" / "推荐稿.md"
            recommendation.write_text("# 标题\n\n正文", encoding="utf-8")
            output = _RunIO()
            with patch.object(import_final.prompt, "confirm", return_value=False):
                import_final.run(output)

            self.assertTrue(recommendation.exists())
            self.assertFalse((repo.archive() / issue_id).exists())
            self.assertIn("已取消，文件未修改", output.out.getvalue())

    def test_normalize_shell_escaped_dragged_path(self) -> None:
        from 工作台.菜单.tests._harness import TempRepo

        with TempRepo() as repo:
            source = (
                repo.root
                / "Sea of Symbols"
                / "+Python mac"
                / "+shang-jian-lab"
                / "稿件.md"
            )
            source.parent.mkdir(parents=True)
            source.write_text("正文", encoding="utf-8")
            raw = str(source).replace(" ", r"\ ").replace("+", r"\+")
            self.assertEqual(import_final.normalize_source_path(raw), source)

            # 兼容界面多加一层反斜杠的粘贴结果。
            doubled = raw.replace(r"\+", r"\\+")
            self.assertEqual(import_final.normalize_source_path(doubled), source)

    def test_existing_recommendation_does_not_import_over_itself(self) -> None:
        from 工作台.菜单.tests._harness import TempRepo

        with TempRepo() as repo:
            issue_root = _seed_simple_issue(repo, "2026-09-09-14-34-16-大模型二三事")
            source = issue_root / "待定稿" / "推荐稿.md"
            source.write_text("推荐稿", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "无需重复导入"):
                import_final.import_final(source, issue_root)

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
