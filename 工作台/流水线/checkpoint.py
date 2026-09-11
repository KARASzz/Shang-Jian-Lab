"""checkpoint.json 原子写与恢复校验（接口规范 §4 + 配置 ``[task]``）。

行为：
- 原子写：先写 ``checkpoint.json.tmp`` → ``os.fsync`` → ``os.replace`` 成
  ``checkpoint.json``；失败时清理 ``.tmp``，不得留下半文件。
- 校验：恢复推进时若发现产物哈希与 ``versions`` 不一致 → 抛出
  ``VersionMixingError``，调用方必须停止流水线（接口规范 §4）。
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path

from 工作台.接口 import TaskState


class CheckpointError(RuntimeError):
    """checkpoint 写入/恢复过程中的错误基类。"""


class VersionMixingError(CheckpointError):
    """恢复时检测到产物哈希与 checkpoint.versions 不一致（接口规范 §4）。"""


CHECKPOINT_NAME = "checkpoint.json"
CHECKPOINT_TMP = "checkpoint.json.tmp"


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_hash(path: str | os.PathLike[str]) -> str:
    """计算文件内容的 SHA-256。"""
    p = Path(path)
    return _hash_text(p.read_text(encoding="utf-8"))


def atomic_write_checkpoint(
    state: TaskState,
    log_dir: str | os.PathLike[str],
) -> TaskState:
    """把 ``state`` 原子写入 ``<log_dir>/checkpoint.json``。

    失败（包括 JSON 序列化、临时写入、rename）必须清理 ``.tmp``，
    不留半文件。返回 ``state``，便于流水线原地更新绑定。
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    target = log_path / CHECKPOINT_NAME
    tmp = log_path / CHECKPOINT_TMP

    # 先清掉可能残留的 .tmp（健壮性，不影响原子性）
    if tmp.exists():
        try:
            tmp.unlink()
        except OSError:
            pass

    try:
        payload = json.dumps(asdict(state), ensure_ascii=False, indent=2)
        with tmp.open("w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except Exception as exc:  # noqa: BLE001 - 必须清理半文件
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise CheckpointError(f"checkpoint 写入失败：{exc}") from exc
    return state


def load_checkpoint(
    log_dir: str | os.PathLike[str],
) -> TaskState | None:
    """读取 ``checkpoint.json``；不存在则返回 ``None``。"""
    path = Path(log_dir) / CHECKPOINT_NAME
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return TaskState(
        issue_id=raw.get("issue_id", ""),
        stage=raw.get("stage", "topic_research"),
        versions=dict(raw.get("versions", {})),
        snapshot_id=raw.get("snapshot_id", ""),
        last_checkpoint_at=raw.get("last_checkpoint_at", ""),
        rerun_invalidated=list(raw.get("rerun_invalidated", [])),
    )


def verify_versions(
    state: TaskState,
    artifacts: dict[str, str],
) -> None:
    """根据 ``artifacts[stage] -> 文本`` 计算哈希，与 ``state.versions`` 对比。

    任一不一致抛 ``VersionMixingError``；缺失则视为未变更，跳过。
    """
    mismatches: list[str] = []
    for stage, text in artifacts.items():
        expected = state.versions.get(stage)
        if expected is None:
            continue
        if _hash_text(text) != expected:
            mismatches.append(stage)
    if mismatches:
        raise VersionMixingError(
            f"版本不一致，禁止恢复：{', '.join(mismatches)}"
        )


def record_version(state: TaskState, stage: str, text: str) -> TaskState:
    """把阶段产物的哈希写入 ``state.versions``，方便下次校验。"""
    from dataclasses import replace as _replace

    versions = dict(state.versions)
    versions[stage] = _hash_text(text)
    # 阶段产物已经用新内容写入后，该阶段不再是过期状态；其下游仍保留
    # 在清单中，直到各自生成新版本。
    invalidated = [item for item in state.rerun_invalidated if item != stage]
    return _replace(state, versions=versions, rerun_invalidated=invalidated)


def commit_stage(
    state: TaskState,
    log_dir: str | os.PathLike[str],
    *,
    version_key: str,
    text: str,
    event: str = "ok",
) -> TaskState:
    """记录产物哈希 → 推进阶段 → 原子写入 checkpoint（磁盘 stage 与内存一致）。"""
    from 工作台.流水线.state import advance

    state = record_version(state, version_key, text)
    state = advance(state, event=event)
    return atomic_write_checkpoint(state, log_dir)


__all__ = [
    "CheckpointError",
    "VersionMixingError",
    "CHECKPOINT_NAME",
    "CHECKPOINT_TMP",
    "atomic_write_checkpoint",
    "load_checkpoint",
    "verify_versions",
    "record_version",
    "commit_stage",
    "file_hash",
]
