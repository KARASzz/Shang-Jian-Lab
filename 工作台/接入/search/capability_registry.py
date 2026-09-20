"""只识别允许用于检索的本地 MCP，并延迟发现工具。"""
from __future__ import annotations

from collections.abc import Mapping
from threading import RLock
from typing import Any

from 工作台.接入.search.local_mcp import LocalMCPError, classify_error


ALIASES: dict[str, tuple[str, ...]] = {
    "firecrawl": ("firecrawl-mcp", "firecrawl-stdio"),
    "tavily": ("tavily-search", "tavily"),
    "brave": ("brave-search",),
    "playwright": ("playwright-MCP", "playwright"),
    "context7": ("context7",),
}


class CapabilityRegistry:
    """按照能力名称解析受信任别名；不扫描配置外服务，也不启动服务直到发现工具。"""

    def __init__(self, client: Any, overrides: Mapping[str, str] | None = None):
        self.client = client
        self.overrides = dict(overrides or {})
        invalid = set(self.overrides) - set(ALIASES)
        if invalid:
            raise LocalMCPError("MCP 服务覆盖包含不允许的能力", category="configuration")
        if not all(isinstance(name, str) and name.strip() for name in self.overrides.values()):
            raise LocalMCPError("MCP 服务覆盖值无效", category="configuration")
        self._servers: dict[str, str] = {}
        self._tool_results: dict[str, list[dict[str, Any]] | LocalMCPError] = {}
        self._lock = RLock()

    def server(self, channel: str) -> str:
        if channel == "omnisearch":
            raise LocalMCPError("Omnisearch 在另一开发环境，当前项目暂时冻结", category="configuration")
        if channel not in ALIASES:
            raise LocalMCPError("检索能力未获允许", category="configuration")
        with self._lock:
            if channel in self._servers:
                return self._servers[channel]
            candidates = (self.overrides[channel],) if channel in self.overrides else ALIASES[channel]
            configured_servers = getattr(self.client, "configured_servers", None)
            if callable(configured_servers):
                try:
                    configured = configured_servers()
                except Exception as exc:
                    raise LocalMCPError("无法读取 MCP 服务清单", category=classify_error(exc)) from None
                matches = [
                    name for name in candidates
                    if isinstance(configured, Mapping)
                    and name in configured
                    and isinstance(configured[name], Mapping)
                    and configured[name].get("enabled", True) is not False
                ]
                if not matches:
                    raise LocalMCPError("检索 MCP 服务未配置或已禁用", category="configuration")
            else:
                # 依赖注入的旧式测试替身没有配置读取方法；真实客户端始终有此接口。
                matches = list(candidates)
            self._servers[channel] = matches[0]
            return matches[0]

    def tools(self, channel: str) -> list[dict[str, Any]]:
        with self._lock:
            cached = self._tool_results.get(channel)
            if isinstance(cached, LocalMCPError):
                raise LocalMCPError(str(cached), category=cached.category) from None
            if cached is not None:
                return cached
            server = self.server(channel)
            try:
                discovered = self.client.discover(server)
                if not isinstance(discovered, list):
                    raise LocalMCPError("MCP 工具清单格式无效", category="protocol")
                tools = [item for item in discovered if isinstance(item, dict) and item.get("name")]
                self._tool_results[channel] = tools
                return tools
            except Exception as exc:
                failure = LocalMCPError("MCP 工具发现失败", category=classify_error(exc))
                self._tool_results[channel] = failure
                raise failure from None


def find_tool(registry: CapabilityRegistry, channel: str, names: tuple[str, ...]) -> dict[str, Any]:
    tools = registry.tools(channel)
    for name in names:
        found = next((item for item in tools if item.get("name") == name), None)
        if found is not None:
            return found
    raise LocalMCPError("MCP 服务未提供所需检索工具", category="tool_missing")


__all__ = ["ALIASES", "CapabilityRegistry", "find_tool"]
