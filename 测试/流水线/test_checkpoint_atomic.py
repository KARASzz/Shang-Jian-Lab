"""模拟写入失败，验证 ``.tmp + rename`` 不留半文件。"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from 工作台.接口 import TaskState
from 工作台.流水线.checkpoint import (
    CHECKPOINT_NAME,
    CHECKPOINT_TMP,
    CheckpointError,
    atomic_write_checkpoint,
    load_checkpoint,
)


def _state() -> TaskState:
    return TaskState(issue_id="x", stage="topic_selection", snapshot_id="s")


class AtomicWriteHappyPathTests(unittest.TestCase):
    def test_atomic_write_creates_checkpoint(self):
        with tempfile.TemporaryDirectory() as td:
            atomic_write_checkpoint(_state(), td)
            target = Path(td) / CHECKPOINT_NAME
            self.assertTrue(target.exists())
            self.assertFalse((Path(td) / CHECKPOINT_TMP).exists())

    def test_load_checkpoint_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            atomic_write_checkpoint(_state(), td)
            loaded = load_checkpoint(td)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.snapshot_id, "s")
            self.assertEqual(loaded.stage, "topic_selection")


class AtomicWriteFailureTests(unittest.TestCase):
    def test_replace_failure_cleans_tmp(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            # 第一次：把 .tmp 替换成不可执行的目录 → os.replace 抛 OSError
            real_replace = os.replace

            def fail_replace(src, dst):
                # 模拟目标已是目录
                Path(dst).mkdir()
                try:
                    real_replace(src, dst)
                except OSError:
                    Path(dst).rmdir()
                    raise

            with patch("工作台.流水线.checkpoint.os.replace", side_effect=fail_replace):
                with self.assertRaises(CheckpointError):
                    atomic_write_checkpoint(_state(), td)
            # .tmp 必须被清理
            self.assertFalse((td_path / CHECKPOINT_TMP).exists())
            # 也不留半文件
            self.assertFalse((td_path / CHECKPOINT_NAME).exists())

    def test_tmp_left_over_is_cleaned_on_next_write(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            # 模拟上次崩溃残留 .tmp
            (td_path / CHECKPOINT_TMP).write_text("garbage", encoding="utf-8")
            atomic_write_checkpoint(_state(), td)
            # 残留 .tmp 已被清理，新 checkpoint 已就位
            self.assertFalse((td_path / CHECKPOINT_TMP).exists())
            self.assertTrue((td_path / CHECKPOINT_NAME).exists())
            data = json.loads((td_path / CHECKPOINT_NAME).read_text(encoding="utf-8"))
            self.assertEqual(data["snapshot_id"], "s")


if __name__ == "__main__":
    unittest.main()
