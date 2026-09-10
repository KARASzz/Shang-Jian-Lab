"""工作台共享数据类型（接口规范 v1.0）。

本文件由接口规范派生，**只**复刻四类接口规范的 dataclass 与 Literal，
不绑定任何具体实现。Agent A（接入）会在 ``工作台/接入/__init__.py``
中 ``from .types import *`` 复用；Agent B（流水线）也直接 import 本模块，
避免引用 ``工作台.接入.client`` / ``search`` 等具体实现路径。

修改需经主线程批准。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol


# ===== §1 模型接口 =====

Role = Literal["planner", "writer", "reviewer"]


@dataclass
class ModelRequest:
    role: Role
    messages: list[dict]
    temperature: float | None = None
    max_tokens: int | None = None
    request_model: str = ""                # 配置中固定，不允许运行时替换
    snapshot_id: str = ""                  # 引用 [task.snapshot_id]，禁止跨期串用


@dataclass
class ModelResponse:
    text: str
    request_model: str = ""                # 发出请求时声明的模型
    served_model: str = ""                 # 服务端实际返回的模型别名
    usage: dict[str, int] = field(default_factory=dict)
    raw_error: str | None = None           # 非空时表示失败，text 不可信


# ===== §2 搜索接口 =====

SearchStatus = Literal["ok", "paywall", "captcha", "fetch_failed", "pdf_unparsed"]
SearchChannel = Literal["tavily", "brave", "bing"]


@dataclass
class SearchSource:
    id: str
    url: str
    title: str
    publisher: str | None = None
    published_at: str | None = None        # ISO 8601
    accessed_at: str = ""                  # ISO 8601
    excerpt: str = ""
    locator: str | None = None
    body_path: str | None = None
    status: SearchStatus = "ok"
    channel: SearchChannel = "tavily"


# ===== §3 审稿接口 =====

Severity = Literal["block", "major", "minor"]
ReviewCategory = Literal[
    "fabricated_citation",
    "unsupported_key_fact",
    "out_of_scope_sample",
    "fake_personal_experience",
    "stale_version",
    "tone",
    "structure",
    "fact",
    "other",
]
Recommendation = Literal["draft_1", "draft_2", "draft_3"]


@dataclass
class ReviewIssue:
    severity: Severity
    category: ReviewCategory
    location: str = ""
    description: str = ""
    evidence_source_ids: list[str] = field(default_factory=list)
    suggestion: str | None = None


@dataclass
class ReviewVerdict:
    draft_version: str = ""
    issues: list[ReviewIssue] = field(default_factory=list)
    score: float = 0.0
    recommendation: Recommendation = "draft_1"
    pass_: bool = False


# ===== §4 任务状态 =====

Stage = Literal[
    "topic_selection",
    "evidence_collection",
    "planning",
    "draft_1",
    "draft_2",
    "draft_3",
    "review_1",
    "revise_1",
    "review_2",
    "revise_2",
    "awaiting_human",
    "finalizing",
    "archived",
]


@dataclass
class TaskState:
    issue_id: str
    stage: Stage
    versions: dict[str, str] = field(default_factory=dict)  # stage -> hash
    snapshot_id: str = ""
    last_checkpoint_at: str = ""
    rerun_invalidated: list[str] = field(default_factory=list)


# ===== 注入接口（Protocol） =====

class ModelClient(Protocol):
    """模型调用抽象；Agent A 提供具体实现，流水线只引用此接口。"""

    def chat(self, req: ModelRequest) -> ModelResponse: ...


class SearchClient(Protocol):
    """搜索调用抽象。"""

    def search(self, query: str, *, round_idx: int) -> list[SearchSource]: ...
    def fetch(self, source: SearchSource) -> SearchSource: ...


class UserInput(Protocol):
    """用户交互抽象（数字菜单 / 输入框 / 提示）。"""

    def choose_topic(self, candidates: list[str]) -> int | str: ...
    def confirm(self, prompt: str) -> bool: ...


__all__ = [
    "Role",
    "ModelRequest",
    "ModelResponse",
    "SearchStatus",
    "SearchChannel",
    "SearchSource",
    "Severity",
    "ReviewCategory",
    "Recommendation",
    "ReviewIssue",
    "ReviewVerdict",
    "Stage",
    "TaskState",
    "ModelClient",
    "SearchClient",
    "UserInput",
]
