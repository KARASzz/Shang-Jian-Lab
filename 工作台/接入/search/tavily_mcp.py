"""工作台 / 接入 / search / tavily_mcp —— stdio MCP 启动占位。

设计原则：

- 接口规范 §2 要求 stdio 必须先做工具发现；本模块 **占位实现不真正启动子进程**。
- ``start()`` 描述将要执行的命令与参数，不读取真实 key，仅写入子进程环境变量名映射。
- 真实启动由主线程集成交付阶段接入。
"""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from typing import Any

from 工作台.接入.config import MCPStdioConfig, resolve_api_key


@dataclass(frozen=True)
class MCPStdioPlan:
    command: str
    args: tuple[str, ...]
    env_keys: dict[str, str]    # 仅含环境变量名映射，不含真实 key


class TavilyMCPClient:
    """Tavily MCP 客户端（stdio 占位）。"""

    def __init__(self, config: MCPStdioConfig) -> None:
        if config.transport != "stdio":
            raise ValueError("TavilyMCPClient 仅接受 stdio transport")
        self._config = config

    @property
    def config(self) -> MCPStdioConfig:
        return self._config

    def build_plan(self) -> MCPStdioPlan:
        """返回将要执行的子进程信息，不真正启动。"""

        return MCPStdioPlan(
            command=self._config.command,
            args=self._config.args,
            env_keys=dict(self._config.env_keys),
        )

    def start(self) -> dict[str, Any]:
        """描述将要执行的命令。占位实现不真正启动。"""

        plan = self.build_plan()
        cmdline = " ".join(shlex.quote(p) for p in [plan.command, *plan.args])
        env_names = ", ".join(
            f"{subprocess_name}={env_var}"
            for subprocess_name, env_var in plan.env_keys.items()
        )
        print(
            f"[调试] Tavily MCP 启动占位：{cmdline}（环境：{env_names}）"
        )
        # 占位：返回未运行状态；不返回任何 key
        return {
            "status": "not_run_in_dev",
            "command": plan.command,
            "args": list(plan.args),
            "env_var_names": list(plan.env_keys.keys()),
        }

    def discover_tools(self) -> list[str]:
        """工具发现占位：返回空列表。真实启动后由 MCP 协议列出工具名。"""

        return []

    @staticmethod
    def build_child_env(plan: MCPStdioPlan) -> dict[str, str]:
        """按 env_keys 把父进程环境变量名映射到子进程环境变量名。

        不取真实 key；返回的字典只含变量名引用，调用方按需实际取值。
        """

        child_env = dict(os.environ)
        for child_var, parent_var in plan.env_keys.items():
            value = resolve_api_key(parent_var)
            if value is None:
                # 不在父进程暴露 key；保留 None 标记
                child_env[child_var] = ""
            else:
                child_env[child_var] = value
        return child_env
