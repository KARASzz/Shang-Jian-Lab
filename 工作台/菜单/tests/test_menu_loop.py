"""主菜单循环：输入 ``1\\n0\\n`` 应走到「新建一期」再正常退出。"""

from __future__ import annotations

import io
import unittest

from 工作台.菜单 import menu
from 工作台.菜单.screens import new_issue


class _StubIO:
    def __init__(self, lines: list[str]) -> None:
        self._lines = list(lines)
        self._idx = 0
        self.out = io.StringIO()

    def println(self, text: str = "") -> None:
        self.out.write(text + "\n")

    def print(self, text: str) -> None:
        self.out.write(text)

    def read_line(self) -> str:
        if self._idx >= len(self._lines):
            return "0"
        line = self._lines[self._idx]
        self._idx += 1
        return line


class MenuLoopTests(unittest.TestCase):
    def test_one_then_zero_walks_new_issue_and_exits(self) -> None:
        from 工作台.菜单.tests._harness import TempRepo

        with TempRepo() as repo:
            io = _StubIO(["1", "1", "0"])  # 1 号 -> 选第 1 个专栏 -> 退出
            rc = menu.run_loop(io)
            self.assertEqual(rc, 0)
            output = io.out.getvalue()
            self.assertIn("1 新建一期", output)
            self.assertIn("已创建：", output)
            self.assertIn("本期快照：", output)
            # 实际快照文件必须存在
            self.assertTrue((repo.config() / "本期.toml").exists())

    def test_zero_exits_immediately(self) -> None:
        io = _StubIO(["0"])
        self.assertEqual(menu.run_loop(io), 0)
        self.assertIn("已退出", io.out.getvalue())

    def test_invalid_choice_keeps_loop(self) -> None:
        io = _StubIO(["x", "0"])
        rc = menu.run_loop(io)
        self.assertEqual(rc, 0)
        self.assertIn("未识别的选项", io.out.getvalue())

    def test_empty_line_on_eof_exits(self) -> None:
        class _EOFIO:
            def __init__(self) -> None:
                self.out = io.StringIO()

            def println(self, text: str = "") -> None:
                self.out.write(text + "\n")

            def print(self, text: str) -> None:
                self.out.write(text)

            def read_line(self) -> str:
                return ""

        eof_io = _EOFIO()
        rc = menu.run_loop(eof_io)
        self.assertEqual(rc, 0)
        self.assertIn("已退出", eof_io.out.getvalue())

    def test_handler_exception_does_not_break_loop(self) -> None:
        """一个屏抛错也要让循环继续；最后 0 退出码仍为 0。"""

        from 工作台.菜单.tests._harness import TempRepo

        with TempRepo():
            import 工作台.菜单.menu as m

            orig = m._HANDLERS["1"]

            def _boom(_io):
                raise RuntimeError("boom")

            m._HANDLERS["1"] = _boom
            try:
                io = _StubIO(["1", "0"])
                rc = menu.run_loop(io)
            finally:
                m._HANDLERS["1"] = orig
        self.assertEqual(rc, 0)
        self.assertIn("boom", io.out.getvalue())


if __name__ == "__main__":
    unittest.main()