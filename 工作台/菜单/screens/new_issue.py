"""菜单 1：新建一期。

按 PLAN.md §2「1 新建一期」：

- 生成 ``YYYY-MM-DD-HH-MM-SS-专栏`` 目录名。
- 在 ``进行中/<issue>/`` 下创建 :mod:`进行中/README.md` 描述的子目录骨架。
- 写入本期快照 ``配置/本期.toml``：把 ``默认.toml`` 拷贝到
  ``配置/本期.toml`` 作为本期模型岗位冻结快照。
- 写 ``运行记录/checkpoint.json`` 初始态（``stage="topic_research"``）。

模型快照的字段名以 ``配置/默认.toml`` 为准；具体取值仍由 B（流水线）
在策划阶段补全，本屏只做"冻结"动作，不读取或验证凭据。
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import paths, prompt

# 三个允许的专栏后缀，与 README.md 三专栏保持一致。
COLUMN_SUFFIXES: tuple[str, ...] = ("大模型二三事", "AI风险治理与审计", "开源项目")


@dataclasses.dataclass(frozen=True)
class NewIssueResult:
    """新建一期的可观察结果，供测试断言。"""

    issue_id: str
    issue_dir: Path
    snapshot: Path
    checkpoint: Path


def list_columns() -> tuple[str, ...]:
    """返回允许的专栏后缀，供菜单展示。"""

    return COLUMN_SUFFIXES


def build_issue_id(column: str, now: datetime | None = None) -> str:
    """生成 ``YYYY-MM-DD-HH-MM-SS-<专栏>`` 形式 id。"""

    if column not in COLUMN_SUFFIXES:
        raise ValueError(f"专栏后缀必须取自 {COLUMN_SUFFIXES}，实际 {column!r}")
    ts = (now or datetime.now()).strftime("%Y-%m-%d-%H-%M-%S")
    return f"{ts}-{column}"


def _freeze_snapshot(default_path: Path, target: Path, *, now: datetime) -> None:
    """把 ``默认.toml`` 拷贝为 ``配置/本期.toml``。

    仅复制字段结构，不读 ``*_env`` 取真实值；这里只完成磁盘冻结，
    供后续诊断屏查询本期岗位快照。覆盖已有 ``本期.toml`` 前必须
    二次确认（用户重新建期 = 显式确认）。
    """

    if target.exists():
        if not prompt.confirm(f"本期快照 {target.name} 已存在，覆盖？", default_no=True):
            raise RuntimeError("用户取消覆盖本期快照")
    content = paths.read_text(default_path)
    banner = (
        f"# 本期快照 — 冻结于 {now.strftime('%Y-%m-%dT%H:%M:%S')}\n"
        "# 由菜单 1「新建一期」自动生成；本期运行期间禁止换模型。\n\n"
    )
    paths.write_text(target, banner + content)


def _create_skeleton(issue_root: Path) -> None:
    """按 :mod:`进行中/README.md` 创建子目录骨架。"""

    subdirs = [
        "选题",
        "资料",
        "策划",
        "三篇初稿",
        "审稿与返修",
        "待定稿",
        "运行记录",
    ]
    for sub in subdirs:
        paths.ensure_dir(issue_root / sub)
    # 初始化选题文件，便于用户查看本期入口。
    (issue_root / "选题" / "选题-候选.md").write_text(
        "# 选题-候选\n\n由流水线 B 在 topic_research 完成后、topic_selection 阶段写入。\n",
        encoding=paths.UTF8,
    )


def _write_initial_checkpoint(checkpoint: Path, *, issue_id: str, snapshot: Path, now: datetime) -> None:
    """写 ``运行记录/checkpoint.json`` 初始态。"""

    state: dict[str, Any] = {
        "issue_id": issue_id,
        "stage": "topic_research",
        "versions": {},
        "snapshot_id": str(snapshot.resolve()),
        "last_checkpoint_at": now.isoformat(timespec="seconds"),
        "rerun_invalidated": [],
    }
    tmp = checkpoint.with_suffix(".json.tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    paths.write_text(tmp, json.dumps(state, ensure_ascii=False, indent=2))
    tmp.replace(checkpoint)


def create_new_issue(column: str, *, now: datetime | None = None) -> NewIssueResult:
    """执行「1 新建一期」全部动作。

    ``now`` 仅用于测试注入；生产路径不传，由 :func:`datetime.now` 决定。
    返回 :class:`NewIssueResult` 以便测试断言。
    """

    moment = now or datetime.now()
    issue_id = build_issue_id(column, moment)
    issue_root = paths.issue_dir(issue_id)
    if issue_root.exists():
        raise FileExistsError(f"期目录已存在：{issue_root}")
    paths.ensure_dir(issue_root)
    _create_skeleton(issue_root)
    default_path = paths.config_dir() / "默认.toml"
    snapshot_path = paths.config_dir() / "本期.toml"
    _freeze_snapshot(default_path, snapshot_path, now=moment)
    checkpoint = issue_root / "运行记录" / "checkpoint.json"
    _write_initial_checkpoint(checkpoint, issue_id=issue_id, snapshot=snapshot_path, now=moment)
    return NewIssueResult(issue_id=issue_id, issue_dir=issue_root, snapshot=snapshot_path, checkpoint=checkpoint)


def run(io) -> None:
    """交互入口。``io`` 是 :class:`MenuIO` 协议，提供输入/输出。"""

    io.println("【1 新建一期】")
    io.print("专栏后缀（1 大模型二三事 / 2 AI风险治理与审计 / 3 开源项目 / 0 自行输入）：")
    choice = io.read_line().strip()
    mapping = {"1": COLUMN_SUFFIXES[0], "2": COLUMN_SUFFIXES[1], "3": COLUMN_SUFFIXES[2]}
    if choice in mapping:
        column = mapping[choice]
    elif choice == "0":
        column = io.read_line().strip()
    elif choice in COLUMN_SUFFIXES:
        column = choice
    else:
        io.println("未识别的专栏，放弃。")
        return
    try:
        result = create_new_issue(column)
    except (FileExistsError, RuntimeError) as exc:
        io.println(f"新建一期失败：{exc}")
        return
    io.println(f"已创建：{result.issue_id}")
    io.println(f"工作目录：{result.issue_dir}")
    io.println(f"本期快照：{result.snapshot}")
    io.println(f"初始检查点：{result.checkpoint}")


__all__ = [
    "COLUMN_SUFFIXES",
    "NewIssueResult",
    "build_issue_id",
    "create_new_issue",
    "list_columns",
    "run",
]
