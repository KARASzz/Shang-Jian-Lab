"""工作台 / 接入 / discovery —— 启动时初始化 MCP、握手、做工具发现（占位）。

设计原则：

- 接口规范 §2：stdio 必须先做工具发现；http 必须先 ping ``/mcp`` 握手。
- 本模块 **占位实现不真正启动**，仅在日志中说明将执行的命令 / 握手路径，
  并返回 ``MCPDiscoveryResult(status="not_run_in_dev", tools=[])``。
- 启动失败或工具缺失时，记录原因并返回 ``status="failed"`` 与空工具列表，
  不抛出异常以免阻塞流水线主循环（由调用方决定是否降级到公开搜索）。
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
    status: str                        # ok | not_run_in_dev | failed
    tools: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)


def discover_all(config: WorkbenchConfig) -> dict[str, MCPDiscoveryResult]:
    """对所有 MCP 与公开搜索渠道执行启动 / 握手 / 工具发现（占位）。

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
                status="not_run_in_dev",
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
                status="not_run_in_dev",
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
        # Bing 公开搜索不需要工具发现；保留位置用于上游统一收集
        results["bing"] = MCPDiscoveryResult(
            channel="bing",
            status="not_run_in_dev",
            tools=[],
            detail={
                "endpoint": config.bing.endpoint,
                "rate_limit_per_minute": config.bing.rate_limit_per_minute,
            },
        )

    return results
