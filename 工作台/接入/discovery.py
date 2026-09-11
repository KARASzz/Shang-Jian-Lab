"""工作台 / 接入 / discovery —— 初始化搜索连接并发现可用工具。

设计原则：

- 接口规范 §2：stdio 必须先做工具发现；http 必须先 ping ``/mcp`` 握手。
- 连接失败时，记录原因并返回 ``status="failed"`` 与空工具列表；
  证据阶段会据此停止，避免把失败当成成功。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from 工作台.接入.config import WorkbenchConfig
from 工作台.接入.search.brave_mcp import BraveMCPClient
from 工作台.接入.search.tavily_mcp import TavilyMCPClient


@dataclass(frozen=True)
class MCPDiscoveryResult:
    channel: str                       # tavily | brave | bing
    status: str                        # ok | failed
    tools: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)


def discover_all(config: WorkbenchConfig) -> dict[str, MCPDiscoveryResult]:
    """对所有搜索渠道执行初始化 / 握手 / 工具发现。

    返回每个渠道的发现结果；真实失败由调用方决定后续降级策略。
    """

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
