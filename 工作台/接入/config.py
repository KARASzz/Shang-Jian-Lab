"""从 配置/默认.toml 读取字段；禁止读取真实密钥。"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = "配置/默认.toml"
LOCAL_CONFIG_PATH = "配置/本地.toml"


@dataclass(frozen=True)
class ModelConfig:
    """单个模型岗位的配置快照。"""

    role: str                       # planner | writer | reviewer
    provider: str                   # openai-compatible
    base_url_env: str               # 仅记录环境变量名，不取真实值
    api_key_env: str
    request_model: str
    temperature: float
    timeout_seconds: int
    max_retries: int


@dataclass(frozen=True)
class MCPStdioConfig:
    transport: str                   # "stdio"
    command: str
    args: tuple[str, ...]
    env_keys: dict[str, str]         # 子进程环境变量名映射，不取真实值


@dataclass(frozen=True)
class MCPHttpConfig:
    transport: str                   # "http"
    url: str
    api_key_env: str | None = None


@dataclass(frozen=True)
class PublicSearchConfig:
    endpoint: str
    user_agent: str
    rate_limit_per_minute: int


@dataclass(frozen=True)
class PipelineConfig:
    deep_search_rounds_max: int
    deep_search_unique_sources_max: int
    site_depth_max: int
    revision_rounds_max: int
    network_retry_max: int
    auth_failure_abort: bool
    topic_research_rounds_max: int = 2
    topic_research_sources_max_per_round: int = 6
    topic_research_min_valid_channels: int = 2
    scrapy_max_pages: int = 36


@dataclass(frozen=True)
class ReviewConfig:
    block_fabricated_citation: bool
    block_unsupported_key_fact: bool
    block_out_of_scope_sample: bool
    block_fake_personal_experience: bool
    score_cannot_override_block: bool


@dataclass(frozen=True)
class TaskConfig:
    checkpoint_atomic_write: bool
    rerun_upstream_invalidates_downstream: bool
    forbid_version_mixing: bool
    manual_required_after_max_revisions: bool


@dataclass(frozen=True)
class WorkbenchConfig:
    meta: dict[str, Any]
    models: dict[str, ModelConfig] = field(default_factory=dict)
    tavily: MCPStdioConfig | None = None
    brave: MCPHttpConfig | None = None
    bing: PublicSearchConfig | None = None
    pipeline: PipelineConfig | None = None
    review: ReviewConfig | None = None
    task: TaskConfig | None = None


def _require(d: dict[str, Any], dotted: str, path: Path) -> Any:
    """按点路径取字典字段；缺失则抛 ConfigError，附带文件路径。"""

    cur: Any = d
    for seg in dotted.split("."):
        if not isinstance(cur, dict) or seg not in cur:
            raise ConfigError(f"{path}：缺少必需字段 `{dotted}`")
        cur = cur[seg]
    return cur


class ConfigError(RuntimeError):
    """配置读取或字段缺失错误。"""


def _parse_models(raw: dict[str, Any]) -> dict[str, ModelConfig]:
    if not raw:
        raise ConfigError("[models] 节点缺失")
    out: dict[str, ModelConfig] = {}
    for role in ("planner", "writer", "reviewer"):
        if role not in raw:
            raise ConfigError(f"[models.{role}] 节点缺失")
        m = raw[role]
        out[role] = ModelConfig(
            role=role,
            provider=m["provider"],
            base_url_env=m["base_url_env"],
            api_key_env=m["api_key_env"],
            request_model=m["request_model"],
            temperature=float(m.get("temperature", 0.0)),
            timeout_seconds=int(m.get("timeout_seconds", 180)),
            max_retries=int(m.get("max_retries", 2)),
        )
    return out


def _parse_tavily(raw: dict[str, Any]) -> MCPStdioConfig:
    if raw.get("transport") != "stdio":
        raise ConfigError("[search.mcp.tavily] transport 必须为 stdio")
    if "command" not in raw or "args" not in raw:
        raise ConfigError("[search.mcp.tavily] stdio 必须配置 command + args")
    return MCPStdioConfig(
        transport="stdio",
        command=str(raw["command"]),
        args=tuple(str(a) for a in raw["args"]),
        env_keys={str(k): str(v) for k, v in raw.get("env", {}).items()},
    )


def _parse_brave(raw: dict[str, Any]) -> MCPHttpConfig:
    if raw.get("transport") != "http":
        raise ConfigError("[search.mcp.brave] transport 必须为 http")
    if "url" not in raw:
        raise ConfigError("[search.mcp.brave] http 必须配置 url")
    return MCPHttpConfig(
        transport="http",
        url=str(raw["url"]),
        api_key_env=raw.get("api_key_env"),
    )


def _parse_bing(raw: dict[str, Any]) -> PublicSearchConfig:
    return PublicSearchConfig(
        endpoint=str(raw["endpoint"]),
        user_agent=str(raw["user_agent"]),
        rate_limit_per_minute=int(raw["rate_limit_per_minute"]),
    )


def _parse_pipeline(raw: dict[str, Any]) -> PipelineConfig:
    cfg = PipelineConfig(
        deep_search_rounds_max=int(raw["deep_search_rounds_max"]),
        deep_search_unique_sources_max=int(raw["deep_search_unique_sources_max"]),
        site_depth_max=int(raw["site_depth_max"]),
        revision_rounds_max=int(raw["revision_rounds_max"]),
        network_retry_max=int(raw["network_retry_max"]),
        auth_failure_abort=bool(raw["auth_failure_abort"]),
        topic_research_rounds_max=int(raw.get("topic_research_rounds_max", 2)),
        topic_research_sources_max_per_round=int(raw.get("topic_research_sources_max_per_round", 6)),
        topic_research_min_valid_channels=int(raw.get("topic_research_min_valid_channels", 2)),
        scrapy_max_pages=int(raw.get("scrapy_max_pages", 36)),
    )
    if not cfg.auth_failure_abort:
        raise ConfigError("[pipeline] auth_failure_abort 必须保持 true")
    if cfg.topic_research_rounds_max != 2:
        raise ConfigError("[pipeline] topic_research_rounds_max 必须为 2")
    if cfg.topic_research_sources_max_per_round < 1:
        raise ConfigError("[pipeline] topic_research_sources_max_per_round 必须大于 0")
    if not 1 <= cfg.topic_research_min_valid_channels <= 3:
        raise ConfigError("[pipeline] topic_research_min_valid_channels 必须在 1–3 之间")
    if cfg.scrapy_max_pages < 1:
        raise ConfigError("[pipeline] scrapy_max_pages 必须大于 0")
    return cfg


def _parse_review(raw: dict[str, Any]) -> ReviewConfig:
    rc = ReviewConfig(
        block_fabricated_citation=bool(raw["block_fabricated_citation"]),
        block_unsupported_key_fact=bool(raw["block_unsupported_key_fact"]),
        block_out_of_scope_sample=bool(raw["block_out_of_scope_sample"]),
        block_fake_personal_experience=bool(raw["block_fake_personal_experience"]),
        score_cannot_override_block=bool(raw["score_cannot_override_block"]),
    )
    for name in (
        "block_fabricated_citation",
        "block_unsupported_key_fact",
        "block_out_of_scope_sample",
        "block_fake_personal_experience",
        "score_cannot_override_block",
    ):
        if not getattr(rc, name):
            raise ConfigError(f"[review] {name} 必须保持 true")
    return rc


def _parse_task(raw: dict[str, Any]) -> TaskConfig:
    tc = TaskConfig(
        checkpoint_atomic_write=bool(raw["checkpoint_atomic_write"]),
        rerun_upstream_invalidates_downstream=bool(
            raw["rerun_upstream_invalidates_downstream"]
        ),
        forbid_version_mixing=bool(raw["forbid_version_mixing"]),
        manual_required_after_max_revisions=bool(
            raw["manual_required_after_max_revisions"]
        ),
    )
    for name in (
        "checkpoint_atomic_write",
        "rerun_upstream_invalidates_downstream",
        "forbid_version_mixing",
        "manual_required_after_max_revisions",
    ):
        if not getattr(tc, name):
            raise ConfigError(f"[task] {name} 必须保持 true")
    return tc


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"配置文件不存在：{path}")
    text = path.read_text(encoding="utf-8")
    # 默认.toml 样例外层包了一层 Markdown ```toml ... ``` 围栏；
    # 真实本地.toml 不会带围栏。这里做一次宽松剥离，兼容两种形态。
    stripped = _strip_markdown_fence(text)
    try:
        return tomllib.loads(stripped)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"配置 TOML 解析失败：{path}：{e}") from e


_MARKDOWN_FENCE = "```"


def _strip_markdown_fence(text: str) -> str:
    """剥离 Markdown ```toml ... ``` 围栏；找不到时返回原文。

    默认.toml 样例被 markdown 包裹；本地.toml 不带围栏。
    围栏可能在文件首行，也可能在注释段之后：扫描首个以 ``` 开头的行作为起点，
    闭合围栏之后的任何 markdown 描述文字一并丢弃。
    """

    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith(_MARKDOWN_FENCE):
            start = i
            break
    if start is None:
        return text
    body = lines[start + 1 :]
    for i, ln in enumerate(body):
        if ln.lstrip().startswith(_MARKDOWN_FENCE):
            return "\n".join(body[:i])
    return "\n".join(body)


def load_default_config(
    repo_root: str | Path = ".", path: str = DEFAULT_CONFIG_PATH
) -> WorkbenchConfig:
    """从 `配置/默认.toml` 加载样例；不读取真实密钥。

    真实密钥环境变量由运行时从 `base_url_env` / `api_key_env` 字段名间接读取。
    """

    repo_root = Path(repo_root).resolve()
    target = (repo_root / path).resolve()
    if not target.exists():
        # 允许直接传入绝对路径
        target = Path(path).resolve()
    raw = _load_toml(target)
    return _parse_workbench(raw, target)


def load_local_config(
    repo_root: str | Path = ".", path: str = LOCAL_CONFIG_PATH
) -> WorkbenchConfig:
    """从 `配置/本地.toml` 加载真实运行配置（仍只读取字段名，不取密钥值）。"""

    repo_root = Path(repo_root).resolve()
    target = (repo_root / path).resolve()
    if not target.exists():
        raise ConfigError(
            f"本地配置不存在：{target}；请先从 默认.toml 复制并填写凭据"
        )
    raw = _load_toml(target)
    return _parse_workbench(raw, target)


def _parse_workbench(raw: dict[str, Any], path: Path) -> WorkbenchConfig:
    meta = raw.get("meta", {})
    models = _parse_models(raw.get("models", {}))

    tavily_raw = raw.get("search", {}).get("mcp", {}).get("tavily")
    brave_raw = raw.get("search", {}).get("mcp", {}).get("brave")
    bing_raw = raw.get("search", {}).get("public", {}).get("bing")

    tavily = _parse_tavily(tavily_raw) if tavily_raw else None
    brave = _parse_brave(brave_raw) if brave_raw else None
    bing = _parse_bing(bing_raw) if bing_raw else None

    pipeline = _parse_pipeline(raw["pipeline"]) if "pipeline" in raw else None
    review = _parse_review(raw["review"]) if "review" in raw else None
    task = _parse_task(raw["task"]) if "task" in raw else None

    # 兜底字段缺失检查
    _require({"meta": meta}, "meta.schema_version", path)

    return WorkbenchConfig(
        meta=meta,
        models=models,
        tavily=tavily,
        brave=brave,
        bing=bing,
        pipeline=pipeline,
        review=review,
        task=task,
    )


def resolve_api_key(env_name: str) -> str | None:
    """按环境变量名取 key；返回 None 表示未配置。

    集中此函数便于日志脱敏点统一。
    """

    val = os.environ.get(env_name)
    if val is None or val.strip() == "":
        return None
    return val


def resolve_base_url(env_name: str) -> str | None:
    val = os.environ.get(env_name)
    if val is None or val.strip() == "":
        return None
    return val.strip()
