"""模型客户端测试 —— 业务契约：错误分类、超时上限、岗位不被替换。"""

from __future__ import annotations

import json
import unittest
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock

import urllib.error

from 工作台.接入.config import ModelConfig
from 工作台.接入.models.client import ModelClient
from 工作台.接入.models.errors import (
    AuthError,
    NetworkError,
    RateLimitError,
    RoleMismatchError,
    TimeoutError,
)
from 工作台.接入.models.schemas import ModelRequest


def _make_config(**overrides: Any) -> ModelConfig:
    base = dict(
        role="planner",
        provider="openai-compatible",
        base_url_env="TEST_BASE_URL",
        api_key_env="TEST_API_KEY",
        request_model="MiniMax-M3",
        temperature=0.4,
        timeout_seconds=180,
        max_retries=2,
    )
    base.update(overrides)
    return ModelConfig(**base)


def _make_request(**overrides: Any) -> ModelRequest:
    base = dict(
        role="planner",
        messages=[{"role": "user", "content": "hi"}],
        temperature=None,
        max_tokens=None,
        request_model="MiniMax-M3",
        snapshot_id="snap-1",
    )
    base.update(overrides)
    return ModelRequest(**base)


def _http_response(status: int, body: dict[str, Any] | str) -> MagicMock:
    raw = body if isinstance(body, str) else json.dumps(body).encode("utf-8")
    resp = MagicMock()
    resp.read = MagicMock(return_value=raw)
    resp.status = status
    resp.headers = {}
    return resp


class ModelClientAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        # 确保测试环境干净
        import os

        os.environ.pop("TEST_API_KEY", None)
        os.environ.pop("TEST_BASE_URL", None)

    def test_missing_api_key_raises_auth_error(self) -> None:
        cfg = _make_config()
        client = ModelClient(cfg, sleeper=MagicMock(), clock=MagicMock())
        req = _make_request()
        with self.assertRaises(AuthError):
            client.complete(req)

    def test_missing_base_url_raises_auth_error(self) -> None:
        import os

        os.environ["TEST_API_KEY"] = "test-key"
        cfg = _make_config()
        client = ModelClient(cfg, sleeper=MagicMock(), clock=MagicMock())
        req = _make_request()
        with self.assertRaises(AuthError):
            client.complete(req)

    def test_role_mismatch_raises_role_mismatch_error(self) -> None:
        import os

        os.environ["TEST_API_KEY"] = "test-key"
        os.environ["TEST_BASE_URL"] = "https://example.com/v1"
        cfg = _make_config()
        client = ModelClient(cfg, sleeper=MagicMock(), clock=MagicMock())
        req = _make_request(role="writer")  # 与 config.role=planner 不一致
        with self.assertRaises(RoleMismatchError):
            client.complete(req)


class ModelClientHTTPErrorTests(unittest.TestCase):
    def setUp(self) -> None:
        import os

        os.environ["TEST_API_KEY"] = "test-key"
        os.environ["TEST_BASE_URL"] = "https://example.com/v1"

    def _build_client_with_opener(self, opener: MagicMock) -> ModelClient:
        cfg = _make_config(max_retries=0)
        return ModelClient(
            cfg,
            http_opener=lambda: opener,
            sleeper=MagicMock(),
            clock=lambda: 0.0,
        )

    def test_http_401_raises_auth_error_no_retry(self) -> None:
        sleeper = MagicMock()
        opener = MagicMock()
        err = urllib.error.HTTPError(
            "https://example.com/v1/chat/completions",
            401,
            "Unauthorized",
            {},
            BytesIO(b'{"error":"invalid key"}'),
        )
        opener.open.side_effect = err
        cfg = _make_config(max_retries=2)
        client = ModelClient(
            cfg,
            http_opener=lambda: opener,
            sleeper=sleeper,
            clock=lambda: 0.0,
        )
        req = _make_request()
        with self.assertRaises(AuthError) as ctx:
            client.complete(req)
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(opener.open.call_count, 1, "Auth 失败不应重试")
        self.assertEqual(sleeper.call_count, 0, "Auth 失败不应退避")

    def test_http_429_retries_then_succeeds(self) -> None:
        sleeper = MagicMock()
        opener = MagicMock()
        rl_err = urllib.error.HTTPError(
            "https://example.com/v1/chat/completions",
            429,
            "Too Many Requests",
            {"Retry-After": "1"},
            BytesIO(b'{"error":"rate"}'),
        )
        ok = _http_response(
            200,
            {
                "model": "MiniMax-M3",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            },
        )
        opener.open.side_effect = [rl_err, ok]
        cfg = _make_config(max_retries=2)
        client = ModelClient(
            cfg,
            http_opener=lambda: opener,
            sleeper=sleeper,
            clock=lambda: 0.0,
        )
        req = _make_request()
        resp = client.complete(req)
        self.assertEqual(resp.text, "ok")
        self.assertEqual(resp.served_model, "MiniMax-M3")
        self.assertEqual(resp.usage["total_tokens"], 3)
        self.assertIsNone(resp.raw_error)
        self.assertEqual(opener.open.call_count, 2)
        self.assertEqual(sleeper.call_count, 1, "应退避一次")

    def test_http_429_exhausts_retries(self) -> None:
        opener = MagicMock()
        rl_err = urllib.error.HTTPError(
            "https://example.com/v1/chat/completions",
            429,
            "Too Many Requests",
            {},
            BytesIO(b'{"error":"rate"}'),
        )
        opener.open.side_effect = [rl_err, rl_err, rl_err]
        cfg = _make_config(max_retries=2)
        client = ModelClient(
            cfg,
            http_opener=lambda: opener,
            sleeper=MagicMock(),
            clock=lambda: 0.0,
        )
        with self.assertRaises(RateLimitError):
            client.complete(_make_request())
        self.assertEqual(opener.open.call_count, 3, "max_retries=2 共调用 3 次")

    def test_http_500_raises_network_error(self) -> None:
        opener = MagicMock()
        err = urllib.error.HTTPError(
            "https://example.com/v1/chat/completions",
            500,
            "Internal Server Error",
            {},
            BytesIO(b'{"error":"boom"}'),
        )
        opener.open.side_effect = err
        cfg = _make_config(max_retries=0)
        client = ModelClient(
            cfg,
            http_opener=lambda: opener,
            sleeper=MagicMock(),
            clock=lambda: 0.0,
        )
        with self.assertRaises(NetworkError) as ctx:
            client.complete(_make_request())
        self.assertEqual(ctx.exception.status_code, 500)

    def test_timeout_raises_timeout_error_with_upper_bound(self) -> None:
        opener = MagicMock()
        opener.open.side_effect = urllib.error.URLError("timed out")
        cfg = _make_config(timeout_seconds=180, max_retries=0)
        client = ModelClient(
            cfg,
            http_opener=lambda: opener,
            sleeper=MagicMock(),
            clock=lambda: 0.0,
        )
        with self.assertRaises(TimeoutError):
            client.complete(_make_request())
        # 检查传给 opener 的 timeout 来自配置（180s 上限）
        _, kwargs = opener.open.call_args
        self.assertEqual(kwargs["timeout"], 180.0)

    def test_read_timeout_retries_and_closes_response(self) -> None:
        import builtins
        bad = _http_response(200, {})
        bad.read.side_effect = builtins.TimeoutError("timed out")
        good = _http_response(200, {"choices": [{"message": {"content": "ok"}}]})
        opener = MagicMock()
        opener.open.side_effect = [bad, good]
        client = ModelClient(_make_config(), http_opener=lambda: opener, sleeper=MagicMock())
        self.assertEqual(client.complete(_make_request()).text, "ok")
        bad.close.assert_called_once()
        good.close.assert_called_once()

    def test_waiting_progress_without_debug_details(self) -> None:
        from contextlib import redirect_stdout
        from io import StringIO
        from threading import Event
        output = StringIO()
        ok = _http_response(200, {"choices": [{"message": {"content": "ok"}}]})
        opener = MagicMock()
        def slow_open(*args, **kwargs):
            Event().wait(0.04)
            return ok
        opener.open.side_effect = slow_open
        client = ModelClient(_make_config(), http_opener=lambda: opener)
        client.progress_interval_seconds = 0.01
        with redirect_stdout(output):
            client.complete(_make_request())
        text = output.getvalue()
        self.assertIn("正在", text)
        self.assertIn("等待", text)
        self.assertNotIn("[调试]", text)
        self.assertNotIn("https://", text)
        self.assertNotIn("MiniMax", text)
        after = output.getvalue()
        Event().wait(0.03)
        self.assertEqual(output.getvalue(), after)

    def test_other_url_error_raises_network_error(self) -> None:
        opener = MagicMock()
        opener.open.side_effect = urllib.error.URLError("Name or service not known")
        cfg = _make_config(max_retries=0)
        client = ModelClient(
            cfg,
            http_opener=lambda: opener,
            sleeper=MagicMock(),
            clock=lambda: 0.0,
        )
        with self.assertRaises(NetworkError):
            client.complete(_make_request())


class ModelClientPayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        import os

        os.environ["TEST_API_KEY"] = "test-key"
        os.environ["TEST_BASE_URL"] = "https://example.com/v1"

    def test_request_payload_contains_endpoint_and_model(self) -> None:
        opener = MagicMock()
        ok = _http_response(
            200,
            {
                "model": "MiniMax-M3",
                "choices": [{"message": {"content": "hello"}}],
                "usage": {},
            },
        )
        opener.open.return_value = ok
        cfg = _make_config()
        client = ModelClient(
            cfg,
            http_opener=lambda: opener,
            sleeper=MagicMock(),
            clock=lambda: 0.0,
        )
        client.complete(_make_request())
        request_obj = opener.open.call_args[0][0]
        self.assertEqual(request_obj.method, "POST")
        self.assertEqual(
            request_obj.full_url,
            "https://example.com/v1/chat/completions",
        )
        body = json.loads(request_obj.data.decode("utf-8"))
        self.assertEqual(body["model"], "MiniMax-M3")
        self.assertEqual(body["messages"], [{"role": "user", "content": "hi"}])
        # 关键：request_model 在请求体里随配置固定
        self.assertEqual(body["model"], cfg.request_model)


class ModelClientContractTests(unittest.TestCase):
    """接口规范：chat()、Retry-After、岗位冻结、空 URL、max_retries=0。"""

    def setUp(self) -> None:
        import os

        os.environ["TEST_API_KEY"] = "test-key"
        os.environ["TEST_BASE_URL"] = "https://example.com/v1"

    def test_chat_aliases_complete(self) -> None:
        opener = MagicMock()
        opener.open.return_value = _http_response(
            200,
            {
                "model": "MiniMax-M3",
                "choices": [{"message": {"content": "via-chat"}}],
                "usage": {},
            },
        )
        client = ModelClient(
            _make_config(),
            http_opener=lambda: opener,
            sleeper=MagicMock(),
            clock=lambda: 0.0,
        )
        resp = client.chat(_make_request())
        self.assertEqual(resp.text, "via-chat")
        self.assertEqual(opener.open.call_count, 1)

    def test_http_429_respects_retry_after_seconds(self) -> None:
        sleeper = MagicMock()
        opener = MagicMock()
        rl_err = urllib.error.HTTPError(
            "https://example.com/v1/chat/completions",
            429,
            "Too Many Requests",
            {"Retry-After": "7"},
            BytesIO(b'{"error":"rate"}'),
        )
        ok = _http_response(
            200,
            {
                "model": "MiniMax-M3",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {},
            },
        )
        opener.open.side_effect = [rl_err, ok]
        client = ModelClient(
            _make_config(max_retries=2),
            http_opener=lambda: opener,
            sleeper=sleeper,
            clock=lambda: 0.0,
        )
        client.complete(_make_request())
        sleeper.assert_called()
        waited = sleeper.call_args[0][0]
        self.assertEqual(waited, 7.0)

    def test_request_model_mismatch_is_not_auth_error(self) -> None:
        from 工作台.接入.models.errors import AuthError, ModelCallError

        opener = MagicMock()
        client = ModelClient(
            _make_config(),
            http_opener=lambda: opener,
            sleeper=MagicMock(),
            clock=lambda: 0.0,
        )
        req = _make_request(request_model="some-other-model")
        with self.assertRaises(ModelCallError) as ctx:
            client.complete(req)
        self.assertNotIsInstance(ctx.exception, AuthError)
        self.assertEqual(opener.open.call_count, 0, "岗位不一致不得发请求")

    def test_empty_base_url_raises_auth_error(self) -> None:
        import os

        from 工作台.接入.models.errors import AuthError

        os.environ["TEST_BASE_URL"] = "   "
        client = ModelClient(
            _make_config(),
            sleeper=MagicMock(),
            clock=lambda: 0.0,
        )
        with self.assertRaises(AuthError):
            client.complete(_make_request())

    def test_max_retries_zero_does_not_retry_500(self) -> None:
        opener = MagicMock()
        err = urllib.error.HTTPError(
            "https://example.com/v1/chat/completions",
            500,
            "Internal Server Error",
            {},
            BytesIO(b'{"error":"boom"}'),
        )
        opener.open.side_effect = err
        client = ModelClient(
            _make_config(max_retries=0),
            http_opener=lambda: opener,
            sleeper=MagicMock(),
            clock=lambda: 0.0,
        )
        from 工作台.接入.models.errors import NetworkError

        with self.assertRaises(NetworkError):
            client.complete(_make_request())
        self.assertEqual(opener.open.call_count, 1)


if __name__ == "__main__":
    unittest.main()
