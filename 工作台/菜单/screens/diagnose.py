"""菜单 9：诊断。

按 PLAN.md §4 与 :mod:`工作台/接口规范.md`：

- 输出当前 ``[meta].issue_lockfile`` 对应的本期快照路径与岗位固定情况；
- MCP 启动参数（命令 / URL 形式，不含 key）；
- 最近 5 条 checkpoint 阶段；
- 最近错误（脱敏）。

实现要点：

- 自实现极简 TOML ``[section] key = value`` 解析，足以取出
  ``meta.issue_lockfile``、``search.mcp.*`` 节；
- 不打印 ``*_env`` 字段的真实值；只显示环境变量名与 MCP 启动命令。
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path
from typing import Iterable

from .. import paths, prompt

# 简易 TOML 行级解析：``[section.sub]`` 与 ``key = "value"``。
_TOML_SECTION = re.compile(r"^\s*\[([^\]]+)\]\s*$")
_TOML_KV = re.compile(r'^\s*([A-Za-z0-9_\-\.]+)\s*=\s*"([^"]*)"\s*$')


@dataclasses.dataclass(frozen=True)
class SnapshotInfo:
    """本期快照诊断信息。"""

    lockfile: str
    exists: bool
    schema_version: str
    models: tuple[str, ...]
    mcp_endpoints: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class CheckpointTrace:
    """单条 checkpoint 摘要。"""

    stage: str
    last_checkpoint_at: str
    rerun_invalidated: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class DiagnoseReport:
    """完整诊断报告。"""

    snapshot: SnapshotInfo
    history: tuple[CheckpointTrace, ...]
    latest_errors: tuple[str, ...]


def _parse_simple_toml(text: str) -> dict[str, dict[str, str]]:
    """极简 TOML 解析：返回 ``{节名: {key: value}}``。

    仅支持 ``[section]``、``[section.sub]``、``key = "value"``。
    """

    out: dict[str, dict[str, str]] = {}
    current: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _TOML_SECTION.match(line)
        if m:
            current = m.group(1)
            out.setdefault(current, {})
            continue
        m = _TOML_KV.match(line)
        if m and current is not None:
            out[current][m.group(1)] = m.group(2)
    return out


def _load_snapshot(lockfile: str) -> SnapshotInfo:
    lock_path = paths.resolve_under(paths.repo_root(), Path(lockfile))
    if not lock_path.exists():
        return SnapshotInfo(lockfile=lockfile, exists=False, schema_version="", models=(), mcp_endpoints=())
    parsed = _parse_simple_toml(paths.read_text(lock_path))
    schema = parsed.get("meta", {}).get("schema_version", "")
    models: list[str] = []
    for section, body in parsed.items():
        if section.startswith("models."):
            req = body.get("request_model", "")
            if req:
                models.append(f"{section}={req}")
    endpoints: list[str] = []
    for section, body in parsed.items():
        if section.startswith("search.mcp."):
            transport = body.get("transport", "")
            if transport == "stdio":
                cmd = body.get("command", "")
                args = body.get("args", "")
                endpoints.append(f"{section}  stdio  {cmd} {args}")
            elif transport == "http":
                endpoints.append(f"{section}  http  {body.get('url', '')}")
    return SnapshotInfo(
        lockfile=lockfile,
        exists=True,
        schema_version=schema,
        models=tuple(models),
        mcp_endpoints=tuple(endpoints),
    )


def _recent_checkpoints(n: int = 5) -> tuple[CheckpointTrace, ...]:
    out: list[CheckpointTrace] = []
    for issue in paths.list_issue_dirs(paths.in_progress_dir())[:n]:
        ck = issue / "运行记录" / "checkpoint.json"
        if not ck.exists():
            continue
        try:
            state = json.loads(paths.read_text(ck))
        except json.JSONDecodeError:
            continue
        out.append(
            CheckpointTrace(
                stage=state.get("stage", ""),
                last_checkpoint_at=state.get("last_checkpoint_at", ""),
                rerun_invalidated=tuple(state.get("rerun_invalidated", [])),
            )
        )
    return tuple(out)


def _recent_errors(n: int = 5) -> tuple[str, ...]:
    """从 ``运行记录/运行日志.ndjson`` 取最近 ``n`` 行错误。"""

    out: list[str] = []
    for issue in paths.list_issue_dirs(paths.in_progress_dir()):
        log = issue / "运行记录" / "运行日志.ndjson"
        if not log.exists():
            continue
        try:
            text = paths.read_text(log)
        except OSError:
            continue
        lines = text.splitlines()[-n:]
        for line in lines:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            level = (entry.get("level") or "").lower()
            if level in {"error", "warning"}:
                msg = entry.get("message") or entry.get("text") or ""
                out.append(prompt.redact(msg))
    return tuple(out[-n:])


def build_report(default_path: Path | None = None) -> DiagnoseReport:
    """组装诊断报告，便于测试断言。"""

    base = default_path or paths.config_dir() / "默认.toml"
    parsed = _parse_simple_toml(paths.read_text(base))
    lockfile = parsed.get("meta", {}).get("issue_lockfile", "")
    snapshot = _load_snapshot(lockfile) if lockfile else SnapshotInfo(
        lockfile="", exists=False, schema_version="", models=(), mcp_endpoints=()
    )
    return DiagnoseReport(
        snapshot=snapshot,
        history=_recent_checkpoints(),
        latest_errors=_recent_errors(),
    )


def run(io) -> None:
    """交互入口。"""

    io.println("【9 诊断】")
    report = build_report()
    io.println(f"本期快照：{report.snapshot.lockfile or '未配置'}")
    if report.snapshot.exists:
        io.println(f"  schema_version = {report.snapshot.schema_version}")
        io.println("  模型岗位：")
        for m in report.snapshot.models:
            io.println(f"    - {m}")
        io.println("  MCP 端点：")
        for ep in report.snapshot.mcp_endpoints:
            io.println(f"    - {ep}")
    else:
        io.println("  （本期快照未生成；先用 8 号菜单复制默认配置，再用 1 号菜单建期。）")
    io.println("最近检查点：")
    if not report.history:
        io.println("  （无）")
    for trace in report.history:
        io.println(
            f"  - {trace.stage} @ {trace.last_checkpoint_at}  标过期 "
            f"{', '.join(trace.rerun_invalidated) or '无'}"
        )
    io.println("最近错误：")
    if not report.latest_errors:
        io.println("  （无）")
    for msg in report.latest_errors:
        io.println(f"  - {msg}")


__all__ = ["DiagnoseReport", "SnapshotInfo", "CheckpointTrace", "build_report", "run"]