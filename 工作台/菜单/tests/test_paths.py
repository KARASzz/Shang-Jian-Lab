"""中文 / 空格路径下的 Path 行为。"""

from __future__ import annotations

import unittest
from pathlib import Path

from 工作台.菜单 import paths


class PathsTests(unittest.TestCase):
    def test_repo_root_is_absolute(self) -> None:
        self.assertTrue(paths.repo_root().is_absolute())

    def test_issue_dir_rejects_separator(self) -> None:
        with self.assertRaises(ValueError):
            paths.issue_dir("2026-09-09-14-34-16/大模型二三事")
        with self.assertRaises(ValueError):
            paths.issue_dir("../escape")

    def test_read_write_text_roundtrip_with_chinese_and_space(self) -> None:
        from 工作台.菜单.tests._harness import TempRepo

        with TempRepo() as repo:
            nested = repo.root / "进行中" / "中文 期-大模型二三事" / "子目录 含空格"
            paths.write_text(nested / "稿件.md", "你好，世界。  —— 含空格路径")
            data = paths.read_text(nested / "稿件.md")
            self.assertEqual(data, "你好，世界。  —— 含空格路径")

    def test_sha256_is_stable(self) -> None:
        # 不走 TempRepo：直接对仓库内的 ``_harness.py`` 计算哈希。
        real_harness = paths.REPO_ROOT / "工作台" / "菜单" / "tests" / "_harness.py"
        # 测试前先确定文件存在（若不在，提示测试环境异常而非静默跳过）。
        self.assertTrue(real_harness.exists(), f"缺少测试目标：{real_harness}")
        h1 = paths.sha256_file(real_harness)
        h2 = paths.sha256_file(real_harness)
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)

    def test_resolve_under_blocks_parent_traversal(self) -> None:
        with self.assertRaises(ValueError):
            paths.resolve_under(paths.repo_root(), Path("../../etc/passwd"))

    def test_list_issue_dirs_skips_hidden(self) -> None:
        from 工作台.菜单.tests._harness import TempRepo

        with TempRepo() as repo:
            (repo.in_progress() / "2026-09-09-14-34-16-大模型二三事").mkdir()
            (repo.in_progress() / ".hidden").mkdir()
            names = [p.name for p in paths.list_issue_dirs(repo.in_progress())]
            self.assertIn("2026-09-09-14-34-16-大模型二三事", names)
            self.assertNotIn(".hidden", names)


if __name__ == "__main__":
    unittest.main()