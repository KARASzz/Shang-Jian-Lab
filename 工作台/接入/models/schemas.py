"""工作台 / 接入 / models / schemas —— 与 接口规范.md §1 完全一致。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": int(self.prompt_tokens),
            "completion_tokens": int(self.completion_tokens),
            "total_tokens": int(self.total_tokens),
        }


@dataclass(frozen=True)
class ModelRequest:
    """接口规范 §1。字段名与字面量严格按规范。"""

    role: Literal["planner", "writer", "reviewer"]
    messages: list[dict]
    temperature: float | None = None
    max_tokens: int | None = None
    request_model: str = ""
    snapshot_id: str = ""


@dataclass(frozen=True)
class ModelResponse:
    """接口规范 §1。

    `raw_error` 非空即视为失败，调用方不得静默降级（认证失败直接停止）。
    """

    text: str = ""
    request_model: str = ""
    served_model: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    raw_error: str | None = None
