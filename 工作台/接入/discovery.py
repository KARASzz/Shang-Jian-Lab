"""工作台 / 接入 / discovery —— 发现本地 MCP 工具。

``discover_all`` 只发现已配置且获准使用的检索能力；
旧的 Tavily / Brave / Bing 配置发现保留在 ``discover_legacy_all``，仅供迁移兼容。
连接失败时返回 ``status="failed"`` 与空工具列表，避免把失败当成成功。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from 工作台.接入.config import WorkbenchConfig
from 工作台.接入.search.brave_mcp import BraveMCPClient
from 工作台.接入.search.tavily_mcp import TavilyMCPClient


@dataclass(frozen=True)
class MCPDiscoveryResult:
    channel: str                       # brave | tavily | firecrawl | playwright | context7
    status: str                        # ok | failed
    tools: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)


def discover_legacy_all(config: WorkbenchConfig) -> dict[str, MCPDiscoveryResult]:
    """发现旧版 Tavily / Brave / Bing 配置，供迁移兼容测试使用。"""

    results: dict[str, MCPDiscoveryResult] = {}

    if config.tavily is not None:
        try:
            client = TavilyMCPClient(config.tavily)
            plan = client.start()
            tools = client.discover_tools()
            results["tavily"] = MCPDiscoveryResult(
                channel="tavily",
                status="ok",
                tools=tools,
                detail=plan,
            )
        except Exception as e:  # noqa: BLE001
            results["tavily"] = MCPDiscoveryResult(
                channel="tavily",
                status="failed",
                tools=[],
                detail={"error": type(e).__name__, "message": str(e)},
            )

    if config.brave is not None:
        try:
            client = BraveMCPClient(config.brave)
            handshake = client.handshake()
            tools = client.discover_tools()
            results["brave"] = MCPDiscoveryResult(
                channel="brave",
                status="ok",
                tools=tools,
                detail=handshake,
            )
        except Exception as e:  # noqa: BLE001
            results["brave"] = MCPDiscoveryResult(
                channel="brave",
                status="failed",
                tools=[],
                detail={"error": type(e).__name__, "message": str(e)},
            )

    if config.bing is not None:
        # Bing 公开搜索不需要握手，但纳入统一发现结果。
        results["bing"] = MCPDiscoveryResult(
            channel="bing",
            status="ok",
            tools=["web_search"],
            detail={
                "endpoint": config.bing.endpoint,
                "rate_limit_per_minute": config.bing.rate_limit_per_minute,
            },
        )

    return results


def discover_all(config: WorkbenchConfig) -> dict[str, MCPDiscoveryResult]:
    """按允许能力发现服务；Omnisearch 与其他无关服务不进入发现列表。"""
    from 工作台.接入.search.capability_registry import ALIASES, CapabilityRegistry
    from 工作台.接入.search.local_mcp import LocalMCPClient

    client = LocalMCPClient(config_path=config.local_mcp_config_path)
    registry = CapabilityRegistry(client, overrides=config.local_mcp_servers)
    results: dict[str, MCPDiscoveryResult] = {}
    for channel in ALIASES:
        try:
            server = registry.server(channel)
            tools = registry.tools(channel)
            results[channel] = MCPDiscoveryResult(
                channel=channel,
                status="ok",
                tools=[str(item["name"]) for item in tools],
                detail={"server": server},
            )
        except Exception as exc:  # noqa: BLE001 - 仅输出安全类别，不暴露服务响应
            results[channel] = MCPDiscoveryResult(
                channel=channel,
                status="failed",
                tools=[],
                detail={"error": type(exc).__name__, "category": getattr(exc, "category", "protocol")},
            )
    return results
