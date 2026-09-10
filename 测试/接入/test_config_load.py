"""默认.toml 字段读取、字段缺失报错。"""

from __future__ import annotations

import os
import tempfile
import textwrap
import unittest
from pathlib import Path

from 工作台.接入.config import (
    ConfigError,
    load_default_config,
    load_local_config,
)


SAMPLE_TOML = textwrap.dedent(
    """
    [meta]
    schema_version = "1.0"
    issue_lockfile = "配置/本期.toml"

    [models.planner]
    provider = "openai-compatible"
    base_url_env = "MINIMAX_BASE_URL"
    api_key_env = "MINIMAX_API_KEY"
    request_model = "MiniMax-M3"
    temperature = 0.4
    timeout_seconds = 180
    max_retries = 2

    [models.writer]
    provider = "openai-compatible"
    base_url_env = "QWEN_BASE_URL"
    api_key_env = "QWEN_API_KEY"
    request_model = "qwen3.7-plus"
    temperature = 0.7
    timeout_seconds = 180
    max_retries = 2

    [models.reviewer]
    provider = "openai-compatible"
    base_url_env = "GLM_BASE_URL"
    api_key_env = "GLM_API_KEY"
    request_model = "glm-5.1"
    temperature = 0.2
    timeout_seconds = 180
    max_retries = 2

    [search.mcp.tavily]
    transport = "stdio"
    command = "npx"
    args = ["-y", "@tavily/mcp-server"]
    env = { TAVILY_API_KEY = "TAVILY_API_KEY" }

    [search.mcp.brave]
    transport = "http"
    url = "http://localhost:8080/mcp"
    api_key_env = "BRAVE_API_KEY"

    [search.public.bing]
    endpoint = "https://www.bing.com/search"
    user_agent = "ua"
    rate_limit_per_minute = 20

    [pipeline]
    deep_search_rounds_max = 2
    deep_search_unique_sources_max = 30
    site_depth_max = 2
    revision_rounds_max = 2
    network_retry_max = 2
    auth_failure_abort = true

    [review]
    block_fabricated_citation = true
    block_unsupported_key_fact = true
    block_out_of_scope_sample = true
    block_fake_personal_experience = true
    score_cannot_override_block = true

    [task]
    checkpoint_atomic_write = true
    rerun_upstream_invalidates_downstream = true
    forbid_version_mixing = true
    manual_required_after_max_revisions = true
    """
).strip() + "\n"


class LoadDefaultConfigTests(unittest.TestCase):
    def test_loads_default_config_from_repo(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        cfg = load_default_config(repo_root=repo_root)
        self.assertIn("planner", cfg.models)
        self.assertEqual(cfg.models["planner"].request_model, "MiniMax-M3")
        self.assertEqual(cfg.models["planner"].timeout_seconds, 180)
        self.assertEqual(cfg.models["writer"].request_model, "qwen3.7-plus")
        self.assertEqual(cfg.models["reviewer"].request_model, "glm-5.1")
        self.assertIsNotNone(cfg.tavily)
        self.assertEqual(cfg.tavily.command, "npx")  # type: ignore[union-attr]
        self.assertIsNotNone(cfg.brave)
        self.assertEqual(cfg.brave.url, "http://localhost:8080/mcp")  # type: ignore[union-attr]
        self.assertEqual(cfg.bing.rate_limit_per_minute, 20)  # type: ignore[union-attr]
        self.assertTrue(cfg.pipeline.auth_failure_abort)  # type: ignore[union-attr]
        self.assertTrue(cfg.review.block_fabricated_citation)  # type: ignore[union-attr]

    def test_loads_local_config(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "本地.toml"
            p.write_text(SAMPLE_TOML, encoding="utf-8")
            cfg = load_local_config(repo_root=d, path=str(p))
            self.assertEqual(cfg.models["planner"].request_model, "MiniMax-M3")
            self.assertEqual(cfg.tavily.command, "npx")  # type: ignore[union-attr]

    def test_local_config_missing_raises(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ConfigError):
                load_local_config(repo_root=d, path="配置/本地.toml")


class FieldMissingTests(unittest.TestCase):
    def _write(self, body: str) -> Path:
        td = Path(tempfile.mkdtemp())
        p = td / "本地.toml"
        p.write_text(body, encoding="utf-8")
        return td

    def test_missing_models_role_raises(self) -> None:
        body = textwrap.dedent(
            """
            [meta]
            schema_version = "1.0"
            """
        ).strip() + "\n"
        d = self._write(body)
        with self.assertRaises(ConfigError):
            load_local_config(repo_root=d, path=str(d / "本地.toml"))

    def test_wrong_transport_raises(self) -> None:
        body = textwrap.dedent(
            """
            [meta]
            schema_version = "1.0"

            [models.planner]
            provider = "openai-compatible"
            base_url_env = "A"
            api_key_env = "B"
            request_model = "m"
            temperature = 0.0
            timeout_seconds = 180
            max_retries = 2

            [models.writer]
            provider = "openai-compatible"
            base_url_env = "A"
            api_key_env = "B"
            request_model = "m"
            temperature = 0.0
            timeout_seconds = 180
            max_retries = 2

            [models.reviewer]
            provider = "openai-compatible"
            base_url_env = "A"
            api_key_env = "B"
            request_model = "m"
            temperature = 0.0
            timeout_seconds = 180
            max_retries = 2

            [search.mcp.tavily]
            transport = "http"
            """
        ).strip() + "\n"
        d = self._write(body)
        with self.assertRaises(ConfigError):
            load_local_config(repo_root=d, path=str(d / "本地.toml"))

    def test_review_flag_set_to_false_raises(self) -> None:
        body = textwrap.dedent(
            """
            [meta]
            schema_version = "1.0"

            [models.planner]
            provider = "openai-compatible"
            base_url_env = "A"
            api_key_env = "B"
            request_model = "m"
            temperature = 0.0
            timeout_seconds = 180
            max_retries = 2

            [models.writer]
            provider = "openai-compatible"
            base_url_env = "A"
            api_key_env = "B"
            request_model = "m"
            temperature = 0.0
            timeout_seconds = 180
            max_retries = 2

            [models.reviewer]
            provider = "openai-compatible"
            base_url_env = "A"
            api_key_env = "B"
            request_model = "m"
            temperature = 0.0
            timeout_seconds = 180
            max_retries = 2

            [review]
            block_fabricated_citation = false
            block_unsupported_key_fact = true
            block_out_of_scope_sample = true
            block_fake_personal_experience = true
            score_cannot_override_block = true
            """
        ).strip() + "\n"
        d = self._write(body)
        with self.assertRaises(ConfigError):
            load_local_config(repo_root=d, path=str(d / "本地.toml"))

    def test_auth_failure_abort_false_raises(self) -> None:
        body = SAMPLE_TOML.replace(
            "auth_failure_abort = true", "auth_failure_abort = false"
        )
        d = self._write(body)
        with self.assertRaises(ConfigError):
            load_local_config(repo_root=d, path=str(d / "本地.toml"))


if __name__ == "__main__":
    unittest.main()
