"""工作台 / 接入层 —— 模型与搜索接入占位（A 子智能体范围）。"""

from 工作台.接入.config import load_default_config, load_local_config
from 工作台.接入.discovery import discover_all, MCPDiscoveryResult
from 工作台.接入.models.client import ModelClient
from 工作台.接入.models.errors import (
    AuthError,
    ModelCallError,
    NetworkError,
    RateLimitError,
    RoleMismatchError,
    TimeoutError,
)
from 工作台.接入.models.schemas import ModelRequest, ModelResponse, TokenUsage
from 工作台.接入.search.bing_public import BingPublicSearch
from 工作台.接入.search.brave_mcp import BraveMCPClient
from 工作台.接入.search.composite import CompositeSearch
from 工作台.接入.search.schemas import SearchSource
from 工作台.接入.search.tavily_mcp import TavilyMCPClient

__all__ = [
    "load_default_config",
    "load_local_config",
    "discover_all",
    "MCPDiscoveryResult",
    "ModelClient",
    "AuthError",
    "ModelCallError",
    "NetworkError",
    "RateLimitError",
    "RoleMismatchError",
    "TimeoutError",
    "ModelRequest",
    "ModelResponse",
    "TokenUsage",
    "BingPublicSearch",
    "BraveMCPClient",
    "CompositeSearch",
    "SearchSource",
    "TavilyMCPClient",
]
