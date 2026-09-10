"""stubs 共用：所有外部依赖在这里注入，不依赖任何真实模型/搜索。"""

from __future__ import annotations

from dataclasses import dataclass, field

from 工作台.接口 import (
    ModelRequest,
    ModelResponse,
    SearchClient,
    SearchSource,
    UserInput,
)


@dataclass
class StubModel:
    """按 ``role`` 返回预设文本；可注入异常验证失败路径。"""

    planner_text: str = ""
    writer_text: str = ""
    reviewer_text: str = ""
    raise_on: str | None = None  # role name that should raise

    def chat(self, req: ModelRequest) -> ModelResponse:
        if self.raise_on and req.role == self.raise_on:
            return ModelResponse(
                text="", request_model=req.request_model,
                served_model=req.request_model, raw_error="simulated failure",
            )
        if req.role == "planner":
            user_content = ""
            if req.messages:
                user_content = str(req.messages[-1].get("content", ""))
            if "三个不同角度" in user_content or "三角度" in user_content:
                text = "## 角度甲\n中心判断甲\n## 角度乙\n中心判断乙\n## 角度丙\n中心判断丙"
            else:
                text = self.planner_text
        else:
            text = {
                "writer": self.writer_text,
                "reviewer": self.reviewer_text,
            }[req.role]
        return ModelResponse(
            text=text,
            request_model=req.request_model,
            served_model=req.request_model,
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        )


@dataclass
class StubSearch:
    sources: list[SearchSource] = field(default_factory=list)

    def search(self, query: str, *, round_idx: int) -> list[SearchSource]:
        return list(self.sources)

    def fetch(self, source: SearchSource) -> SearchSource:
        return source


@dataclass
class StubUser:
    choice: int | str = 1
    confirm_yes: bool = True

    def choose_topic(self, candidates: list[str]) -> int | str:
        return self.choice

    def confirm(self, prompt: str) -> bool:
        return self.confirm_yes


def make_search_source(i: int) -> SearchSource:
    return SearchSource(
        id=f"src-{i}",
        url=f"https://example.test/{i}",
        title=f"Source {i}",
        publisher="example",
        published_at="2026-06-01",
        accessed_at="2026-09-10",
        excerpt="excerpt",
        locator=None,
        body_path=None,
        status="ok",
        channel="tavily",
    )
