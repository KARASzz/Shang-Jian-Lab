"""8 号配置必须把密钥写入 gitignore 路径，且不得回显。"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from 工作台.菜单.screens import config_screen
from 工作台.菜单.tests._harness import TempRepo
from 工作台.菜单.tests.test_menu_loop import _StubIO


class ConfigPersistTests(unittest.TestCase):
    def test_hidden_input_written_to_credentials_env(self) -> None:
        with TempRepo() as repo:
            default = repo.config() / "默认.toml"
            local = repo.config() / "本地.toml"
            config_screen.copy_default_to_local(default, local)
            dest = config_screen.persist_secrets(
                repo.root,
                {"MINIMAX_API_KEY": "glm-not-sk-pattern-abcdef123456"},
            )
            self.assertTrue(dest.exists())
            text = dest.read_text(encoding="utf-8")
            self.assertIn("MINIMAX_API_KEY=glm-not-sk-pattern-abcdef123456", text)
            self.assertEqual(os.environ.get("MINIMAX_API_KEY"), "glm-not-sk-pattern-abcdef123456")
            self.assertTrue(
                str(dest).endswith("配置/凭据/.env") or dest.name == ".env"
            )

    def test_run_does_not_echo_raw_key(self) -> None:
        with TempRepo():
            io = _StubIO(["https://example.invalid/v1"])  # base url visible field
            # getpass is used for env keys; patch it
            from unittest.mock import patch
            from 工作台.菜单 import prompt

            with patch.object(prompt, "read_hidden", return_value="super-secret-key-value-xyz"):
                config_screen.run(io)
            out = io.out.getvalue()
            self.assertNotIn("super-secret-key-value-xyz", out)
