"""从 ``提示词/`` 加载岗位系统提示词。"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FILES = {
    "planner": "planner-system.md",
    "writer": "writer-system.md",
    "reviewer": "reviewer-system.md",
}


def system_prompt(role: str) -> str:
    name = _FILES.get(role)
    if not name:
        raise ValueError(f"未知岗位：{role}")
    path = _REPO_ROOT / "提示词" / name
    if not path.exists():
        raise FileNotFoundError(f"缺少系统提示词：{path}")
    return path.read_text(encoding="utf-8")


def request_model_of(client, fallback: str) -> str:
    cfg = getattr(client, "config", None)
    model = getattr(cfg, "request_model", None) if cfg is not None else None
    return str(model) if model else fallback
