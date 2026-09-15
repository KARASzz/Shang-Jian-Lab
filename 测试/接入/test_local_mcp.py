"""本地 Codex MCP 客户端的配置、生命周期与安全边界测试。"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from 工作台.接入.search import local_mcp


class _AsyncContext:
    def __init__(self, value: object) -> None:
        self.value = value
        self.entered = False
        self.exited = False

    async def __aenter__(self) -> object:
        self.entered = True
        return self.value

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.exited = True


class _Parameters:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        for key, value in kwargs.items():
            setattr(self, key, value)


class _Session:
    def __init__(
        self,
        pages: list[object],
        result: object | None = None,
        initialize_error: BaseException | None = None,
        list_error: BaseException | None = None,
    ) -> None:
        self.pages = list(pages)
        self.result = result if result is not None else {}
        self.initialize_error = initialize_error
        self.list_error = list_error
        self.entered = False
        self.exited = False
        self.initialized = False
        self.cursors: list[object] = []
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def __aenter__(self) -> "_Session":
        self.entered = True
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.exited = True

    async def initialize(self) -> object:
        if self.initialize_error is not None:
            raise self.initialize_error
        self.initialized = True
        return {"protocolVersion": "test"}

    async def list_tools(self, cursor: object | None = None) -> object:
        if self.list_error is not None:
            raise self.list_error
        self.cursors.append(cursor)
        if not self.pages:
            return {"tools": []}
        return self.pages.pop(0)

    async def call_tool(self, name: str, arguments: dict[str, object]) -> object:
        self.calls.append((name, arguments))
        return self.result


class _Runtime:
    ClientSession = _Session
    StdioServerParameters = _Parameters

    def __init__(self, session: _Session, transport: _AsyncContext) -> None:
        self.session = session
        self.transport = transport
        self.ClientSession = lambda _read, _write: self.session
        self.http_calls: list[tuple[str, dict[str, object]]] = []

    def stdio_client(self, params: object, *, errlog: object | None = None) -> _AsyncContext:
        self.transport.params = params  # type: ignore[attr-defined]
        self.transport.errlog = errlog  # type: ignore[attr-defined]
        if errlog is not None:
            self.transport.errlog_fileno = errlog.fileno()  # type: ignore[attr-defined]
        return self.transport

    def streamablehttp_client(
        self, url: str, *, headers: dict[str, str], timeout: float
    ) -> _AsyncContext:
        self.http_calls.append((url, {"headers": headers, "timeout": timeout}))
        return self.transport


def _write_config(text: str) -> Path:
    directory = Path(tempfile.mkdtemp(prefix="local-mcp-test-"))
    path = directory / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


class LocalMCPClientTests(unittest.TestCase):
    def test_discover_returns_all_paginated_tools_with_original_schema(self) -> None:
        config = _write_config(
            '[mcp_servers."mcp-omnisearch"]\n'
            'type = "stdio"\n'
            'command = "fake-mcp"\n'
            'args = []\n'
        )
        schema = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }
        session = _Session(
            pages=[
                {"tools": [{"name": "search", "inputSchema": schema}], "nextCursor": "page-2"},
                {"tools": [{"name": "fetch", "description": "fetch"}]},
            ]
        )
        transport = _AsyncContext(("read", "write"))
        runtime = _Runtime(session, transport)

        with patch.object(local_mcp, "_load_sdk", return_value=runtime):
            tools = local_mcp.LocalMCPClient(config_path=config).discover("mcp-omnisearch")

        self.assertEqual(
            tools,
            [
                {"name": "search", "inputSchema": schema},
                {"name": "fetch", "description": "fetch"},
            ],
        )
        self.assertEqual(session.cursors, [None, "page-2"])
        self.assertTrue(session.initialized)
        self.assertTrue(session.entered)
        self.assertTrue(session.exited)
        self.assertTrue(transport.entered)
        self.assertTrue(transport.exited)

    def test_call_initializes_discovers_calls_requested_tool_and_closes_contexts(self) -> None:
        config = _write_config(
            '[mcp_servers."brave-search"]\n'
            'type = "stdio"\n'
            'command = "fake-mcp"\n'
            'args = ["--test"]\n'
        )
        session = _Session(
            pages=[{"tools": [{"name": "brave_web_search", "inputSchema": {}}]}],
            result={"content": [{"type": "text", "text": "result"}], "isError": False},
        )
        transport = _AsyncContext(("read", "write"))
        runtime = _Runtime(session, transport)
        arguments = {"query": "判断力", "count": 3}

        with patch.object(local_mcp, "_load_sdk", return_value=runtime):
            result = local_mcp.LocalMCPClient(config_path=config).call(
                "brave-search", "brave_web_search", arguments
            )

        self.assertEqual(result, {"content": [{"type": "text", "text": "result"}], "isError": False})
        self.assertEqual(session.calls, [("brave_web_search", arguments)])
        self.assertTrue(session.initialized)
        self.assertTrue(session.exited)
        self.assertTrue(transport.exited)

    def test_stdio_passes_configured_environment_to_sdk_parameters(self) -> None:
        config = _write_config(
            '[mcp_servers."firecrawl-stdio"]\n'
            'type = "stdio"\n'
            'command = "firecrawl"\n'
            'args = ["--stdio"]\n'
            '[mcp_servers."firecrawl-stdio".env]\n'
            'FIRECRAWL_API_KEY = "stdio-secret"\n'
        )
        session = _Session(pages=[{"tools": []}])
        transport = _AsyncContext(("read", "write"))
        runtime = _Runtime(session, transport)

        with patch.object(local_mcp, "_load_sdk", return_value=runtime):
            local_mcp.LocalMCPClient(config_path=config).discover("firecrawl-stdio")

        params = transport.params  # type: ignore[attr-defined]
        self.assertEqual(params.command, "firecrawl")
        self.assertEqual(params.args, ["--stdio"])
        self.assertEqual(params.env, {"FIRECRAWL_API_KEY": "stdio-secret"})
        self.assertIsNotNone(transport.errlog)  # type: ignore[attr-defined]
        self.assertTrue(transport.errlog.closed)  # type: ignore[attr-defined]

    def test_http_passes_headers_and_bearer_environment_to_sdk_transport(self) -> None:
        os.environ["LOCAL_MCP_TOKEN"] = "http-secret"
        try:
            config = _write_config(
                '[mcp_servers."http-server"]\n'
                'type = "http"\n'
                'url = "https://example.test/mcp"\n'
                'bearer_token_env_var = "LOCAL_MCP_TOKEN"\n'
                '[mcp_servers."http-server".http_headers]\n'
                'X-Trace = "trace-id"\n'
            )
            session = _Session(pages=[{"tools": []}])
            transport = _AsyncContext(("read", "write"))
            runtime = _Runtime(session, transport)

            with patch.object(local_mcp, "_load_sdk", return_value=runtime):
                local_mcp.LocalMCPClient(config_path=config, timeout_seconds=7).discover("http-server")

            self.assertEqual(runtime.http_calls[0][0], "https://example.test/mcp")
            self.assertEqual(
                runtime.http_calls[0][1],
                {
                    "headers": {"X-Trace": "trace-id", "Authorization": "Bearer http-secret"},
                    "timeout": 7,
                },
            )
        finally:
            os.environ.pop("LOCAL_MCP_TOKEN", None)

    def test_missing_server_and_node_repl_are_explicitly_rejected(self) -> None:
        config = _write_config(
            '[mcp_servers.node_repl]\n'
            'type = "stdio"\n'
            'command = "node-repl"\n'
            'args = []\n'
        )
        client = local_mcp.LocalMCPClient(config_path=config)

        with self.assertRaisesRegex(local_mcp.LocalMCPError, "未找到 MCP 服务"):
            client.discover("missing")
        with self.assertRaisesRegex(local_mcp.LocalMCPError, "Node REPL"):
            client.discover("node_repl")

    def test_missing_sdk_is_reported_without_exposing_config_values(self) -> None:
        secret = "sdk-secret-must-not-appear"
        config = _write_config(
            '[mcp_servers."tavily"]\n'
            'type = "stdio"\n'
            'command = "fake"\n'
            'args = []\n'
            f'[mcp_servers."tavily".env]\nTAVILY_API_KEY = "{secret}"\n'
        )
        with patch.object(local_mcp, "_load_sdk", side_effect=ImportError(secret)):
            with self.assertRaisesRegex(local_mcp.LocalMCPError, "MCP SDK") as raised:
                local_mcp.LocalMCPClient(config_path=config).discover("tavily")
        self.assertNotIn(secret, str(raised.exception))

    def test_service_failure_is_safe_and_contexts_are_closed(self) -> None:
        secret = "service-secret-must-not-appear"
        config = _write_config(
            '[mcp_servers."playwright"]\n'
            'type = "stdio"\n'
            'command = "fake"\n'
            'args = []\n'
        )
        session = _Session(pages=[], initialize_error=RuntimeError(secret))
        transport = _AsyncContext(("read", "write"))
        runtime = _Runtime(session, transport)

        with patch.object(local_mcp, "_load_sdk", return_value=runtime):
            with self.assertRaisesRegex(local_mcp.LocalMCPError, "服务调用失败") as raised:
                local_mcp.LocalMCPClient(config_path=config).discover("playwright")
        self.assertNotIn(secret, str(raised.exception))
        self.assertTrue(transport.exited)
        self.assertTrue(session.entered)
        self.assertTrue(session.exited)

    def test_timeout_is_explicit(self) -> None:
        config = _write_config(
            '[mcp_servers."slow"]\n'
            'type = "stdio"\n'
            'command = "fake"\n'
            'args = []\n'
        )

        class _SlowSession(_Session):
            async def initialize(self) -> object:
                await asyncio.sleep(0.05)
                return await super().initialize()

        session = _SlowSession(pages=[{"tools": []}])
        transport = _AsyncContext(("read", "write"))
        runtime = _Runtime(session, transport)

        with patch.object(local_mcp, "_load_sdk", return_value=runtime):
            with self.assertRaisesRegex(local_mcp.LocalMCPError, "超时"):
                local_mcp.LocalMCPClient(config_path=config, timeout_seconds=0.001).discover("slow")
        self.assertTrue(transport.exited)


if __name__ == "__main__":
    unittest.main()
