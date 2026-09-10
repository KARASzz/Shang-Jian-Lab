"""getpass 隐藏输入与日志脱敏。"""

from __future__ import annotations

import builtins
import getpass
import io
import unittest
from unittest import mock

from 工作台.菜单 import prompt


class RedactTests(unittest.TestCase):
    def test_redacts_key_value_pairs(self) -> None:
        text = 'OPENAI_API_KEY=sk-stub-abcdefghijklmnop AND api_key="ghp_aaaabbbbccccddddeeee"'
        out = prompt.redact(text)
        self.assertNotIn("sk-stub-abcdefghijklmnop", out)
        self.assertNotIn("ghp_aaaabbbbccccddddeeee", out)
        self.assertIn(prompt.REDACTED, out)

    def test_redacts_standalone_keys(self) -> None:
        text = "prefix sk-abcdefghijklmnopqrst suffix"
        out = prompt.redact(text)
        self.assertNotIn("sk-abcdefghijklmnopqrst", out)
        self.assertIn(prompt.REDACTED, out)

    def test_redact_empty(self) -> None:
        self.assertEqual(prompt.redact(""), "")


class HiddenPromptTests(unittest.TestCase):
    def test_getpass_does_not_echo(self) -> None:
        """getpass.getpass 默认不回显；用 patch 验证它确实被调用。"""

        with mock.patch.object(getpass, "getpass", return_value="sk-stub-abcdefghijklmnop") as gp:
            value = prompt.read_hidden("token: ")
        gp.assert_called_once()
        self.assertEqual(value, "sk-stub-abcdefghijklmnop")

        # 测试本身不能把真值打印到 stdout/stderr；这里显式断言日志脱敏。
        sanitized = prompt.redact("raw=sk-stub-abcdefghijklmnop")
        buf = io.StringIO()
        buf.write(sanitized)
        self.assertNotIn("sk-stub-abcdefghijklmnop", buf.getvalue())

    def test_getpass_keyboardinterrupt_returns_empty(self) -> None:
        with mock.patch.object(getpass, "getpass", side_effect=KeyboardInterrupt):
            self.assertEqual(prompt.read_hidden("x: "), "")


class ConfirmTests(unittest.TestCase):
    def test_confirm_default_no_on_empty(self) -> None:
        with mock.patch.object(builtins, "input", return_value=""):
            self.assertFalse(prompt.confirm("ok?", default_no=True))
        with mock.patch.object(builtins, "input", return_value="y"):
            self.assertTrue(prompt.confirm("ok?", default_no=True))
        with mock.patch.object(builtins, "input", return_value="n"):
            self.assertFalse(prompt.confirm("ok?", default_no=True))


if __name__ == "__main__":
    unittest.main()