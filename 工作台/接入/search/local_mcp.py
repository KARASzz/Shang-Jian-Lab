"""通过本地 Codex 配置调用 MCP 服务。

这个模块只负责 MCP 协议传输和工具发现，不负责搜索结果归一化，也不提供
任何 HTTP API 直连回退。同步方法每次都建立一个新的 asyncio 运行和 SDK
上下文，以便 stdio 子进程、HTTP 流和 ``ClientSession`` 都能在返回前关闭。
"""

from __future__ import annotations

import asyncio
import inspect
import os
import re
import tomllib
from contextlib import asynccontextmanager
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


class LocalMCPError(RuntimeError):
    """本地 MCP 配置、SDK、服务或协议调用失败。"""


@dataclass(frozen=True)
class _MCPRuntime:
    """延迟导入的官方 MCP SDK 运行时对象。"""

    ClientSession: Any
    StdioServerParameters: Any
    stdio_client: Any
    streamablehttp_client: Any | None = None
    sse_client: Any | None = None


_ENV_REFERENCE = re.compile(r"\$(?:\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)\}|(?P<plain>[A-Za-z_][A-Za-z0-9_]*))")
_STDIO_TYPES = {"stdio", "local", "command"}
_HTTP_TYPES = {"http", "streamable_http", "streamablehttp", "streamable"}
_SSE_TYPES = {"sse", "http_sse", "http+sse"}
_BLOCKED_SERVERS = {"node_repl"}


def _load_sdk() -> _MCPRuntime:
    """在真正调用服务时导入官方 ``mcp`` Python SDK。

    模块导入本身不要求安装 SDK，这让配置检查和离线单元测试能正常运行。
    不同 SDK 版本对 ``ClientSession`` 和参数类的导出位置略有差异，这里只
    做导入位置兼容，不实现第二套 MCP 协议。
    """

    try:
        try:
            from mcp.client.session import ClientSession
        except ImportError:
            from mcp import ClientSession

        try:
            from mcp import StdioServerParameters
        except ImportError:
            from mcp.client.stdio import StdioServerParameters

        from mcp.client.stdio import stdio_client
    except ImportError:
        raise LocalMCPError("未安装官方 Python MCP SDK（mcp）") from None

    try:
        from mcp.client.streamable_http import streamablehttp_client
    except ImportError:
        streamablehttp_client = None

    try:
        from mcp.client.sse import sse_client
    except ImportError:
        sse_client = None

    return _MCPRuntime(
        ClientSession=ClientSession,
        StdioServerParameters=StdioServerParameters,
        stdio_client=stdio_client,
        streamablehttp_client=streamablehttp_client,
        sse_client=sse_client,
    )


class LocalMCPClient:
    """读取 ``mcp_servers`` 并同步调用其中一个本地 MCP 服务。

    ``server`` 使用配置中的原始键名，例如 ``brave-search``、
    ``mcp-omnisearch``；不会把下划线、连字符或大小写改写成别名。
    """

    def __init__(
        self,
        config_path: str | os.PathLike[str] | None = None,
        *,
        timeout_seconds: float = 30.0,
        max_pages: int = 1000,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0")
        if max_pages <= 0:
            raise ValueError("max_pages 必须大于 0")
        self.config_path = Path(config_path).expanduser() if config_path else self._default_config_path()
        self.timeout_seconds = float(timeout_seconds)
        self.max_pages = int(max_pages)

    @staticmethod
    def _default_config_path() -> Path:
        codex_home = os.environ.get("CODEX_HOME")
        if codex_home and codex_home.strip():
            return Path(codex_home).expanduser() / "config.toml"
        return Path.home() / ".codex" / "config.toml"

    def discover(self, server: str) -> list[dict]:
        """初始化服务并返回完整的工具 schema 列表（含所有分页）。"""

        spec = self._server_spec(server)
        return self._run(server, lambda runtime: self._discover_async(runtime, spec))

    def call(self, server: str, tool: str, arguments: Mapping[str, Any]) -> dict:
        """初始化、发现工具并调用指定工具，返回 SDK 的原始结果字典。"""

        if not isinstance(tool, str) or not tool:
            raise LocalMCPError("MCP 工具名不能为空")
        if not isinstance(arguments, Mapping):
            raise LocalMCPError("MCP 工具参数必须是对象")
        spec = self._server_spec(server)
        copied_arguments = dict(arguments)
        return self._run(
            server,
            lambda runtime: self._call_async(runtime, spec, tool, copied_arguments),
        )

    def _load_servers(self) -> Mapping[str, Any]:
        path = self.config_path
        if not path.exists():
            raise LocalMCPError(f"MCP 配置文件不存在：{path}")
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            raise LocalMCPError(f"无法读取 MCP 配置文件：{path}") from None
        try:
            raw = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            raise LocalMCPError(f"MCP 配置文件格式无效：{path}") from None
        servers = raw.get("mcp_servers")
        if not isinstance(servers, Mapping):
            raise LocalMCPError("MCP 配置缺少 [mcp_servers] 节点")
        return servers

    def _server_spec(self, server: str) -> dict[str, Any]:
        if not isinstance(server, str) or not server:
            raise LocalMCPError("MCP 服务名不能为空")
        if server in _BLOCKED_SERVERS:
            raise LocalMCPError("Node REPL 不属于检索 MCP，已禁止调用")
        servers = self._load_servers()
        if server not in servers:
            raise LocalMCPError(f"未找到 MCP 服务：{server}")
        raw = servers[server]
        if not isinstance(raw, Mapping):
            raise LocalMCPError(f"MCP 服务配置无效：{server}")
        if raw.get("enabled") is False:
            raise LocalMCPError(f"MCP 服务已禁用：{server}")
        spec = {str(key): value for key, value in raw.items()}
        # 仅供内部错误摘要使用；不会传入 MCP 服务配置或 SDK 参数。
        spec["__server"] = server
        return spec

    def _transport_kind(self, spec: Mapping[str, Any], server: str) -> str:
        raw_type = spec.get("type", spec.get("transport", ""))
        type_name = str(raw_type).strip().lower().replace("-", "_") if raw_type else ""
        has_url = isinstance(spec.get("url"), str) and bool(spec.get("url", "").strip())
        has_command = isinstance(spec.get("command"), str) and bool(spec.get("command", "").strip())

        if type_name in _STDIO_TYPES:
            if not has_command or has_url:
                raise LocalMCPError(f"MCP stdio 配置无效：{server}")
            return "stdio"
        if type_name in _SSE_TYPES:
            if not has_url or has_command:
                raise LocalMCPError(f"MCP HTTP 配置无效：{server}")
            return "sse"
        if type_name in _HTTP_TYPES:
            if not has_url or has_command:
                raise LocalMCPError(f"MCP HTTP 配置无效：{server}")
            return "http"
        if type_name:
            raise LocalMCPError(f"MCP 传输类型不受支持：{server}")
        if has_url and not has_command:
            return "http"
        if has_command and not has_url:
            return "stdio"
        raise LocalMCPError(f"MCP 服务缺少 command 或 url：{server}")

    def _stdio_parameters(self, runtime: Any, spec: Mapping[str, Any], server: str) -> Any:
        command = spec.get("command")
        if not isinstance(command, str) or not command.strip():
            raise LocalMCPError(f"MCP stdio 缺少 command：{server}")
        args = self._string_sequence(spec.get("args", []), "args", server)
        env_raw = spec.get("env", {})
        if not isinstance(env_raw, Mapping):
            raise LocalMCPError(f"MCP stdio 环境变量配置无效：{server}")
        env: dict[str, str] = {}
        for key, value in env_raw.items():
            if not isinstance(key, str) or not key:
                raise LocalMCPError(f"MCP stdio 环境变量配置无效：{server}")
            if not isinstance(value, (str, int, float, bool)):
                raise LocalMCPError(f"MCP stdio 环境变量配置无效：{server}")
            env[key] = str(value)

        params_class = self._runtime_member(runtime, "StdioServerParameters")
        params: dict[str, Any] = {"command": command, "args": args, "env": env}
        cwd = spec.get("cwd")
        if cwd is not None:
            if not isinstance(cwd, str) or not cwd.strip():
                raise LocalMCPError(f"MCP stdio cwd 配置无效：{server}")
            params["cwd"] = cwd
        try:
            return params_class(**params)
        except Exception:
            raise LocalMCPError(f"无法创建 MCP stdio 参数：{server}") from None

    @staticmethod
    def _string_sequence(value: Any, field: str, server: str) -> list[str]:
        if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
            raise LocalMCPError(f"MCP stdio {field} 配置无效：{server}")
        return [str(item) for item in value]

    def _http_spec(self, spec: Mapping[str, Any], server: str) -> tuple[str, dict[str, str]]:
        url = spec.get("url")
        if not isinstance(url, str) or not url.strip():
            raise LocalMCPError(f"MCP HTTP 缺少 url：{server}")
        headers = self._headers(spec, server)
        return url, headers

    @classmethod
    def _headers(cls, spec: Mapping[str, Any], server: str) -> dict[str, str]:
        headers: dict[str, str] = {}
        for field in ("headers", "http_headers"):
            raw_headers = spec.get(field)
            if raw_headers is None:
                continue
            if not isinstance(raw_headers, Mapping):
                raise LocalMCPError(f"MCP HTTP 请求头配置无效：{server}")
            for name, value in raw_headers.items():
                if not isinstance(name, str) or not name.strip():
                    raise LocalMCPError(f"MCP HTTP 请求头配置无效：{server}")
                if not isinstance(value, (str, int, float, bool)):
                    raise LocalMCPError(f"MCP HTTP 请求头配置无效：{server}")
                headers[name] = cls._expand_env_references(str(value), server)

        env_name = None
        for field in (
            "bearer_token_env_var",
            "bearer_token_env",
            "authorization_env_var",
            "auth_token_env_var",
        ):
            candidate = spec.get(field)
            if candidate is not None:
                env_name = candidate
                break
        if env_name is not None:
            if not isinstance(env_name, str) or not env_name.strip():
                raise LocalMCPError(f"MCP HTTP Bearer 环境变量配置无效：{server}")
            token = os.environ.get(env_name)
            if not token or not token.strip():
                raise LocalMCPError(f"MCP HTTP Bearer 环境变量未设置：{server}")
            if not any(name.lower() == "authorization" for name in headers):
                headers["Authorization"] = f"Bearer {token}"

        direct_bearer = spec.get("bearer_token")
        if direct_bearer is not None and not any(name.lower() == "authorization" for name in headers):
            if not isinstance(direct_bearer, (str, int, float, bool)):
                raise LocalMCPError(f"MCP HTTP Bearer 配置无效：{server}")
            token = cls._expand_env_references(str(direct_bearer), server)
            if token.strip():
                headers["Authorization"] = (
                    token if token.lower().startswith("bearer ") else f"Bearer {token}"
                )
        return headers

    @staticmethod
    def _expand_env_references(value: str, server: str) -> str:
        missing = False

        def replace(match: re.Match[str]) -> str:
            nonlocal missing
            env_name = match.group("braced") or match.group("plain")
            resolved = os.environ.get(env_name)
            if resolved is None:
                missing = True
                return ""
            return resolved

        expanded = _ENV_REFERENCE.sub(replace, value)
        if missing:
            raise LocalMCPError(f"MCP HTTP 请求头引用的环境变量未设置：{server}")
        return expanded

    def _run(self, server: str, operation: Callable[[Any], Any]) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise LocalMCPError("同步 MCP 客户端不能在运行中的事件循环内调用")

        async def bounded() -> Any:
            runtime = _load_sdk()
            return await asyncio.wait_for(operation(runtime), timeout=self.timeout_seconds)

        try:
            return asyncio.run(bounded())
        except LocalMCPError:
            raise
        except ImportError:
            raise LocalMCPError("未安装官方 Python MCP SDK（mcp）") from None
        except (asyncio.TimeoutError, TimeoutError):
            raise LocalMCPError(f"MCP 服务调用超时：{server}") from None
        except Exception:
            # SDK 异常可能包含命令行、HTTP header 或服务响应；对外只返回安全摘要。
            raise LocalMCPError(f"MCP 服务调用失败：{server}") from None

    async def _discover_async(self, runtime: Any, spec: Mapping[str, Any]) -> list[dict]:
        async with self._transport_context(runtime, spec) as streams:
            read_stream, write_stream = self._stream_pair(streams)
            async with self._session(runtime, read_stream, write_stream) as session:
                await session.initialize()
                return await self._list_all_tools(session)

    async def _call_async(
        self,
        runtime: Any,
        spec: Mapping[str, Any],
        tool: str,
        arguments: dict[str, Any],
    ) -> dict:
        async with self._transport_context(runtime, spec) as streams:
            read_stream, write_stream = self._stream_pair(streams)
            async with self._session(runtime, read_stream, write_stream) as session:
                await session.initialize()
                tools = await self._list_all_tools(session)
                if not any(item.get("name") == tool for item in tools):
                    raise LocalMCPError(f"未发现 MCP 工具：{tool}")
                try:
                    result = await session.call_tool(name=tool, arguments=arguments)
                except TypeError:
                    # 兼容少数早期 SDK 的位置参数签名；只在 Python 调用签名不兼容时重试。
                    result = await session.call_tool(tool, arguments)
                return self._as_dict(result, "MCP 工具调用结果")

    def _transport_context(self, runtime: Any, spec: Mapping[str, Any]) -> Any:
        server = str(spec.get("__server", "MCP"))
        # ``__server`` 仅用于内部安全错误摘要，不会写回配置。
        kind = self._transport_kind(spec, server)
        if kind == "stdio":
            params = self._stdio_parameters(runtime, spec, server)
            factory = self._runtime_member(runtime, "stdio_client")
            try:
                return self._stdio_context(factory, params)
            except Exception:
                raise LocalMCPError(f"无法启动 MCP stdio 服务：{server}") from None

        url, headers = self._http_spec(spec, server)
        factory_name = "sse_client" if kind == "sse" else "streamablehttp_client"
        factory = self._runtime_member(runtime, factory_name, required=False)
        if factory is None:
            raise LocalMCPError(f"当前 MCP SDK 不支持 {kind} HTTP 传输：{server}")
        try:
            return self._http_context(factory, url, headers)
        except LocalMCPError:
            raise
        except Exception:
            raise LocalMCPError(f"无法连接 MCP HTTP 服务：{server}") from None

    def _session(self, runtime: Any, read_stream: Any, write_stream: Any) -> Any:
        session_class = self._runtime_member(runtime, "ClientSession")
        try:
            return session_class(read_stream, write_stream)
        except Exception:
            raise LocalMCPError("无法创建 MCP 客户端会话") from None

    @staticmethod
    def _stdio_context(factory: Any, params: Any) -> Any:
        """把 MCP 子进程 stderr 丢弃，避免 SDK 默认 stderr 泄露服务输出。"""

        kwargs: dict[str, Any] = {}
        try:
            signature = inspect.signature(factory)
            parameters = signature.parameters
            accepts_kwargs = any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            )
            if accepts_kwargs or "errlog" in parameters:
                kwargs["errlog"] = None
        except (TypeError, ValueError):
            # 官方 SDK 的 stdio_client 支持 errlog；无法反射时仍使用安全捕获。
            kwargs["errlog"] = None
        if "errlog" not in kwargs:
            return factory(params, **kwargs)

        @asynccontextmanager
        async def quiet_context():
            # Windows subprocess creation requires a real file descriptor; DEVNULL
            # is closed together with the MCP context.
            with open(os.devnull, "w", encoding="utf-8") as errlog:
                async with factory(params, **{**kwargs, "errlog": errlog}) as streams:
                    yield streams

        return quiet_context()

    @staticmethod
    def _stream_pair(streams: Any) -> tuple[Any, Any]:
        if isinstance(streams, (tuple, list)) and len(streams) >= 2:
            return streams[0], streams[1]
        if hasattr(streams, "read_stream") and hasattr(streams, "write_stream"):
            return streams.read_stream, streams.write_stream
        raise LocalMCPError("MCP transport 未返回读写流")

    @staticmethod
    def _runtime_member(runtime: Any, name: str, *, required: bool = True) -> Any:
        value = runtime.get(name) if isinstance(runtime, Mapping) else getattr(runtime, name, None)
        if required and value is None:
            raise LocalMCPError(f"MCP SDK 缺少 {name} 接口")
        return value

    def _http_context(self, factory: Any, url: str, headers: dict[str, str]) -> Any:
        kwargs: dict[str, Any] = {}
        try:
            signature = inspect.signature(factory)
            params = signature.parameters
            accepts_kwargs = any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in params.values()
            )
            if accepts_kwargs or "headers" in params:
                kwargs["headers"] = headers
            if accepts_kwargs or "timeout" in params:
                kwargs["timeout"] = self.timeout_seconds
            elif accepts_kwargs or "sse_read_timeout" in params:
                kwargs["sse_read_timeout"] = self.timeout_seconds
        except (TypeError, ValueError):
            # 官方 SDK 接口支持 headers/timeout；无法反射时按该接口传递。
            kwargs = {"headers": headers, "timeout": self.timeout_seconds}
        return factory(url, **kwargs)

    async def _list_all_tools(self, session: Any) -> list[dict]:
        tools: list[dict] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        for _ in range(self.max_pages):
            page = await self._list_tools_page(session, cursor)
            page_tools, next_cursor = self._page_parts(page)
            tools.extend(self._as_dict(item, "MCP 工具 schema") for item in page_tools)
            if not next_cursor:
                return tools
            if next_cursor in seen_cursors:
                raise LocalMCPError("MCP 工具分页游标重复")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        raise LocalMCPError("MCP 工具分页超过安全上限")

    @staticmethod
    async def _list_tools_page(session: Any, cursor: str | None) -> Any:
        if cursor is None:
            return await session.list_tools()
        try:
            return await session.list_tools(cursor=cursor)
        except TypeError:
            return await session.list_tools(cursor)

    @staticmethod
    def _page_parts(page: Any) -> tuple[list[Any], str | None]:
        if isinstance(page, Mapping):
            page_tools = page.get("tools", [])
            cursor = page.get("nextCursor", page.get("next_cursor"))
        else:
            page_tools = getattr(page, "tools", [])
            cursor = getattr(page, "nextCursor", None)
            if cursor is None:
                cursor = getattr(page, "next_cursor", None)
        if not isinstance(page_tools, list):
            raise LocalMCPError("MCP 工具发现响应格式无效")
        if cursor is not None and not isinstance(cursor, str):
            raise LocalMCPError("MCP 工具分页游标格式无效")
        return page_tools, cursor

    @staticmethod
    def _as_dict(value: Any, label: str) -> dict:
        if isinstance(value, dict):
            return dict(value)
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            try:
                dumped = model_dump(mode="json", by_alias=True, exclude_none=False)
            except TypeError:
                dumped = model_dump()
            if isinstance(dumped, dict):
                return dumped
        dict_method = getattr(value, "dict", None)
        if callable(dict_method):
            try:
                dumped = dict_method()
            except Exception:
                dumped = None
            if isinstance(dumped, dict):
                return dumped
        if hasattr(value, "__dict__"):
            dumped = dict(vars(value))
            if dumped:
                return dumped
        raise LocalMCPError(f"{label}不是对象")


__all__ = ["LocalMCPClient", "LocalMCPError"]
