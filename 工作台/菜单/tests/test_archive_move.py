"""6 号归档前后文件清单与 SHA-256 一致。"""

from __future__ import annotations

import unittest
from pathlib import Path

from 工作台.菜单 import paths
from 工作台.菜单.screens import archive


def _seed_issue(repo_root: Path, issue_id: str) -> Path:
    """构造一个最小化的「进行中/<issue>/」样例。"""

    issue_root = repo_root / "进行中" / issue_id
    sub = archive.CARRY_SUBDIRS
    for name in sub:
        (issue_root / name).mkdir(parents=True)
    # 写两份不同内容
    (issue_root / "选题" / "选题-候选.md").write_text("选题候选 1", encoding="utf-8")
    (issue_root / "待定稿" / "推荐稿.md").write_text("流水线推荐稿", encoding="utf-8")
    # 加一份带书名号定稿
    (issue_root / "待定稿" / "熵减进化室-公众号成稿-《智能变得廉价》.md").write_text(
        "定稿正文", encoding="utf-8"
    )
    # 不应随期迁移：.env / .workbuddy / 运行日志 / 本期.toml
    (issue_root / ".env").write_text("OPENAI_API_KEY=sk-stub-abcdefghijklmnop", encoding="utf-8")
    (issue_root / ".workbuddy").mkdir()
    (issue_root / ".workbuddy" / "memory.md").write_text("备忘", encoding="utf-8")
    (issue_root / "运行记录").mkdir(exist_ok=True)
    (issue_root / "运行记录" / "checkpoint.json").write_text("{}", encoding="utf-8")
    (issue_root / "运行记录" / "运行日志.ndjson").write_text("{}\n", encoding="utf-8")
    return issue_root


class ArchiveMoveTests(unittest.TestCase):
    def test_archive_keeps_sha256_and_excludes_logs(self) -> None:
        from 工作台.菜单.tests._harness import TempRepo

        with TempRepo() as repo:
            issue_id = "2026-09-09-14-34-16-大模型二三事"
            issue_root = _seed_issue(repo.root, issue_id)
            carried_paths = [
                issue_root / "选题" / "选题-候选.md",
                issue_root / "待定稿" / "推荐稿.md",
                issue_root / "待定稿" / "熵减进化室-公众号成稿-《智能变得廉价》.md",
            ]
            pre_hashes = {p: paths.sha256_file(p) for p in carried_paths}

            result = archive.archive_issue(issue_id, confirm_callback=lambda *a, **k: True)
            self.assertEqual(result.issue_id, issue_id)
            dst = repo.archive() / issue_id

            # 迁走的三个文件应在 ``存档/`` 中出现，且哈希一致。
            for p in carried_paths:
                rel = p.relative_to(issue_root)
                moved = dst / rel
                self.assertTrue(moved.exists(), f"应迁入：{rel}")
                self.assertEqual(paths.sha256_file(moved), pre_hashes[p])

            # 排除项 **必须** 不出现在 ``存档/`` 中（核心约束）。
            self.assertFalse((dst / "运行记录").exists())
            self.assertFalse((dst / ".env").exists())
            self.assertFalse((dst / ".workbuddy").exists())
            # 源期目录必须消失，避免「进行中」仍列出空壳。
            self.assertFalse(issue_root.exists())

    def test_archive_carries_top_level_images(self) -> None:
        from 工作台.菜单.tests._harness import TempRepo

        with TempRepo() as repo:
            issue_id = "2026-09-09-14-34-16-大模型二三事"
            issue_root = _seed_issue(repo.root, issue_id)
            cover = issue_root / "封面图.png"
            cover.write_bytes(b"PNGDATA")
            pre = paths.sha256_file(cover)
            archive.archive_issue(issue_id, confirm_callback=lambda *a, **k: True)
            moved = repo.archive() / issue_id / "封面图.png"
            self.assertTrue(moved.exists())
            self.assertEqual(paths.sha256_file(moved), pre)
            self.assertFalse(issue_root.exists())

    def test_archive_rejects_existing_destination(self) -> None:
        from 工作台.菜单.tests._harness import TempRepo

        with TempRepo() as repo:
            issue_id = "2026-09-09-14-34-16-大模型二三事"
            _seed_issue(repo.root, issue_id)
            (repo.archive() / issue_id).mkdir()
            with self.assertRaises(FileExistsError):
                archive.archive_issue(issue_id, confirm_callback=lambda *a, **k: True)

    def test_archive_cancelled_keeps_source_intact(self) -> None:
        from 工作台.菜单.tests._harness import TempRepo

        with TempRepo() as repo:
            issue_id = "2026-09-09-14-34-16-大模型二三事"
            issue_root = _seed_issue(repo.root, issue_id)
            with self.assertRaises(PermissionError):
                archive.archive_issue(issue_id, confirm_callback=lambda *a, **k: False)
            # 源目录应保持不动。
            self.assertTrue(issue_root.exists())
            self.assertFalse((repo.archive() / issue_id).exists())


if __name__ == "__main__":
    unittest.main()