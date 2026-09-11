"""Brave 搜索接入：优先 MCP，端点不可用时调用官方 Search API。"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable

from 工作台.接入.config import MCPHttpConfig, resolve_api_key
from 工作台.接入.search.schemas import SearchSource


def _secure_opener() -> Any:
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))


class BraveMCPError(RuntimeError):
    """Brave 搜索调用失败。"""


class BraveMCPClient:
    _DIRECT_API_URL = "https://api.search.brave.com/res/v1/web/search"
    _PROTOCOL_VERSION = "2025-03-26"

    def __init__(
        self,
        config: MCPHttpConfig,
        *,
        http_opener: Callable[..., Any] | None = None,
        timeout_seconds: float = 20.0,
        enable_direct_fallback: bool = True,
    ) -> None:
        if config.transport != "http":
            raise ValueError("BraveMCPClient 仅接受 http 配置")
        self._config = config
        self._http_opener = http_opener or _secure_opener
        self._timeout_seconds = timeout_seconds
        self._enable_direct_fallback = enable_direct_fallback
        self._session_id: str | None = None
        self._tools: list[str] | None = None
        self._mcp_failed = False
        self._initialized = False

    @property
    def config(self) -> MCPHttpConfig:
        return self._config

    def handshake_url(self) -> str:
        return self._config.url.rstrip("/")

    def handshake(self) -> dict[str, Any]:
        if self._initialized:
            return {"status": "ok", "transport": "mcp", "url": self.handshake_url(), "session": bool(self._session_id)}
        try:
            result = self._rpc(
                "initialize",
                {
                    "protocolVersion": self._PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "shang-jian-workbench", "version": "1.0"},
                },
                request_id=1,
            )
            self._notify("notifications/initialized")
            self._initialized = True
            return {"status": "ok", "transport": "mcp", "url": self.handshake_url(), "server_info": result.get("serverInfo", {})}
        except BraveMCPError:
            self._mcp_failed = True
            if self._enable_direct_fallback:
                self._key()
                return {"status": "ok", "transport": "brave-search-api", "endpoint": self._DIRECT_API_URL}
            raise

    def discover_tools(self) -> list[str]:
        if self._mcp_failed:
            return ["web_search"] if self._enable_direct_fallback else []
        if self._tools is None:
            try:
                self.handshake()
                if self._mcp_failed:
                    return ["web_search"] if self._enable_direct_fallback else []
                result = self._rpc("tools/list", {}, request_id=2)
                tools = result.get("tools", [])
                self._tools = [str(tool["name"]) for tool in tools if isinstance(tool, dict) and tool.get("name")]
            except BraveMCPError:
                self._mcp_failed = True
                if self._enable_direct_fallback:
                    return ["web_search"]
                raise
        return list(self._tools)

    def search(self, query: str, *, round_idx: int = 0, max_results: int = 10) -> list[SearchSource]:
        if self._mcp_failed and self._enable_direct_fallback:
            return self._direct_search(query, round_idx=round_idx, max_results=max_results)
        try:
            tools = self.discover_tools()
            if self._mcp_failed and self._enable_direct_fallback:
                return self._direct_search(query, round_idx=round_idx, max_results=max_results)
            tool_name = next((name for name in ("brave_web_search", "brave_search", "web_search") if name in tools), None)
            if tool_name is None:
                tool_name = next((name for name in tools if "search" in name.lower()), None)
            if tool_name is None:
                raise BraveMCPError("Brave MCP 未发现搜索工具")
            result = self._rpc("tools/call", {"name": tool_name, "arguments": {"query": query, "count": max_results}}, request_id=3)
            return self._sources_from_data(result, round_idx=round_idx)
        except BraveMCPError:
            self._mcp_failed = True
            if self._enable_direct_fallback:
                return self._direct_search(query, round_idx=round_idx, max_results=max_results)
            raise

    def fetch(self, source: SearchSource) -> SearchSource:
        return source

    def _key(self) -> str:
        key = resolve_api_key(self._config.api_key_env or "")
        if not key:
            raise BraveMCPError("未配置 Brave 搜索凭据")
        return key

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self._key()}",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _rpc(self, method: str, params: dict[str, Any], *, request_id: int) -> dict[str, Any]:
        body, headers = self._post(
            self.handshake_url(),
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
            self._headers(),
        )
        session = self._header(headers, "Mcp-Session-Id")
        if session:
            self._session_id = session
        message = self._decode(body, headers)
        if "error" in message:
            error = message.get("error") or {}
            raise BraveMCPError(str(error.get("message") or "Brave MCP 返回错误"))
        result = message.get("result")
        if not isinstance(result, dict):
            raise BraveMCPError("Brave MCP 响应缺少 result")
        return result

    def _notify(self, method: str) -> None:
        self._post(self.handshake_url(), {"jsonrpc": "2.0", "method": method}, self._headers())

    def _post(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> tuple[bytes, Any]:
        request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST", headers=headers)
        try:
            response = self._http_opener().open(request, timeout=self._timeout_seconds)
            try:
                body = response.read()
                response_headers = getattr(response, "headers", {})
            finally:
                close = getattr(response, "close", None)
                if close:
                    close()
            return body, response_headers
        except urllib.error.HTTPError as exc:
            raise BraveMCPError(f"Brave 搜索服务返回 HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise BraveMCPError("Brave 搜索服务暂时无法连接") from exc

    def _direct_search(self, query: str, *, round_idx: int, max_results: int) -> list[SearchSource]:
        url = self._DIRECT_API_URL + "?" + urllib.parse.urlencode({"q": query, "count": max_results})
        request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json", "X-Subscription-Token": self._key()})
        try:
            response = self._http_opener().open(request, timeout=self._timeout_seconds)
            try:
                data = json.loads(response.read())
            finally:
                close = getattr(response, "close", None)
                if close:
                    close()
        except urllib.error.HTTPError as exc:
            raise BraveMCPError(f"Brave 搜索服务返回 HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise BraveMCPError("Brave 搜索服务暂时无法连接") from exc
        return self._sources_from_data(data, round_idx=round_idx)

    @staticmethod
    def _header(headers: Any, name: str) -> str | None:
        if hasattr(headers, "get"):
            value = headers.get(name) or headers.get(name.lower())
            return str(value) if value else None
        return None

    @classmethod
    def _decode(cls, body: bytes, headers: Any) -> dict[str, Any]:
        text = body.decode("utf-8", errors="replace").strip()
        content_type = cls._header(headers, "Content-Type") or ""
        if "event-stream" in content_type or text.startswith("event:") or "\ndata:" in text:
            data_lines = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
            text = data_lines[-1] if data_lines else text
        try:
            message = json.loads(text)
        except json.JSONDecodeError as exc:
            raise BraveMCPError("Brave MCP 返回了无法解析的响应") from exc
        if not isinstance(message, dict):
            raise BraveMCPError("Brave MCP 响应格式不正确")
        return message

    @classmethod
    def _sources_from_data(cls, data: Any, *, round_idx: int) -> list[SearchSource]:
        candidates: Any = data
        if isinstance(data, dict):
            result = data.get("result") if isinstance(data.get("result"), dict) else data
            structured = result.get("structuredContent") if isinstance(result, dict) else None
            content = result.get("content") if isinstance(result, dict) else None
            candidates = structured or content or result
            if isinstance(candidates, list):
                texts = [item.get("text", "") for item in candidates if isinstance(item, dict)]
                for text in texts:
                    try:
                        candidates = json.loads(text)
                        break
                    except (TypeError, json.JSONDecodeError):
                        continue
        if isinstance(candidates, dict):
            candidates = candidates.get("web", {}).get("results") or candidates.get("results") or candidates.get("items") or []
        if not isinstance(candidates, list):
            return []
        accessed = datetime.now(timezone.utc).isoformat(timespec="seconds")
        out: list[SearchSource] = []
        for index, item in enumerate(candidates):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or item.get("link") or "").strip()
            title = str(item.get("title") or "").strip()
            if not url or not title:
                continue
            out.append(SearchSource(
                id=f"brave-{round_idx}-{index}", url=url, title=title,
                publisher=item.get("publisher"), published_at=item.get("published") or item.get("date"),
                accessed_at=accessed, excerpt=str(item.get("description") or item.get("snippet") or item.get("text") or "").strip(),
                locator=None, body_path=None, status="ok", channel="brave",
            ))
        return out


__all__ = ["BraveMCPClient", "BraveMCPError"]
