"""工作台 / 接入 / search / brave_mcp —— http MCP 握手占位。

设计原则：

- 接口规范 §2 要求 http 必须先 ping ``/mcp`` 握手。
- 本模块 **占位实现不真正握手**，仅描述将要请求的 URL 与凭据引用。
"""

from __future__ import annotations

from typing import Any

from 工作台.接入.config import MCPHttpConfig, resolve_api_key


class BraveMCPClient:
    """Brave MCP 客户端（http 占位）。"""

    def __init__(self, config: MCPHttpConfig) -> None:
        if config.transport != "http":
            raise ValueError("BraveMCPClient 仅接受 http transport")
        self._config = config

    @property
    def config(self) -> MCPHttpConfig:
        return self._config

    def handshake_url(self) -> str:
        return self._config.url.rstrip("/") + "/"

    def handshake(self) -> dict[str, Any]:
        """描述将要请求的握手 URL，不真正发出请求。"""

        url = self.handshake_url()
        api_key = (
            resolve_api_key(self._config.api_key_env)
            if self._config.api_key_env
            else None
        )
        print(
            f"[调试] Brave MCP 握手占位：{url} "
            f"api_key_env={self._config.api_key_env} "
            f"has_key={api_key is not None}"
        )
        return {
            "status": "not_run_in_dev",
            "url": url,
            "api_key_env": self._config.api_key_env,
        }

    def discover_tools(self) -> list[str]:
        """工具发现占位：返回空列表。真实握手后由 MCP 协议列出工具名。"""

        return []

    def search(self, query: str, *, round_idx: int = 0) -> list:
        from 工作台.接入.search.schemas import SearchSource

        print(f"[调试] Brave 搜索占位：query={query!r} round_idx={round_idx}")
        return [
            SearchSource(
                id=f"brave-unavail-r{round_idx}",
                url=self._config.url,
                title="Brave MCP 未启用（占位，未握手）",
                publisher=None,
                published_at=None,
                accessed_at="",
                excerpt=query,
                locator=None,
                body_path=None,
                status="fetch_failed",
                channel="brave",
            )
        ]

    def fetch(self, source):
        return source
