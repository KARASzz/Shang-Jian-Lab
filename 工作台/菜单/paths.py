"""中文与空格路径处理。

仓库根与各期目录都包含中文，且部分用户会在空格目录下工作；所有
I/O 必须显式 UTF-8，避免 Windows 默认 GBK 解码炸出
``UnicodeDecodeError``。

约束：

- 仅使用标准库 ``pathlib.Path``，禁止 ``os.system("cd " + path)``。
- ``read_text`` / ``write_text`` 必须显式 ``encoding="utf-8"``。
- ``open`` 调用统一通过 :func:`open_text` / :func:`open_bytes`。
- 所有目录/文件名比较前调用 :func:`resolve_under` 取得绝对路径。
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Iterable, Iterator

UTF8 = "utf-8"

# 仓库根目录解析：``__file__`` 是 ``工作台/菜单/paths.py``，上溯两级。
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def repo_root() -> Path:
    """返回仓库根目录的绝对路径。

    使用 :meth:`Path.resolve` 以保证在符号链接与 ``/private/var`` 形
    况下也能锁定唯一路径，便于哈希校验与日志去重。
    """

    return REPO_ROOT


def in_progress_dir() -> Path:
    """``进行中/`` 目录的绝对路径。"""

    return REPO_ROOT / "进行中"


def archive_dir() -> Path:
    """``存档/`` 目录的绝对路径。"""

    return REPO_ROOT / "存档"


def config_dir() -> Path:
    """``配置/`` 目录的绝对路径。"""

    return REPO_ROOT / "配置"


def prompt_dir() -> Path:
    """``提示词/`` 目录的绝对路径。"""

    return REPO_ROOT / "提示词"


def issue_dir(issue_id: str) -> Path:
    """``进行中/<issue_id>/`` 绝对路径。

    ``issue_id`` 不允许包含路径分隔符；含分隔符直接抛错以避免越权。
    """

    _validate_issue_id(issue_id)
    return in_progress_dir() / issue_id


def archived_issue_dir(issue_id: str) -> Path:
    """``存档/<issue_id>/`` 绝对路径。"""

    _validate_issue_id(issue_id)
    return archive_dir() / issue_id


def open_text(path: Path, mode: str = "r", newline: str = "") -> "io.TextIOWrapper":  # type: ignore[name-defined]
    """以 UTF-8 打开文本文件。

    包装 :func:`open` 以保证所有读 / 写都显式编码；菜单中禁止出现
    裸 ``open`` 调用，便于静态检查追溯编码。
    """

    import io  # 局部导入仅为类型标注，避免模块加载期开销。

    if "b" in mode:
        raise ValueError("open_text 不接受二进制模式；请改用 open_bytes")
    # ``newline`` 在二进制模式外才有意义；这里只透传给文本模式。
    return open(path, mode, encoding=UTF8, newline=newline)


def open_bytes(path: Path, mode: str = "rb"):
    """以二进制模式打开文件，常用于哈希计算。"""

    return open(path, mode)


def read_text(path: Path) -> str:
    """UTF-8 读取文本，并去除末尾 BOM（若存在）。"""

    with open_bytes(path, "rb") as f:
        data = f.read()
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.decode(UTF8)


def write_text(path: Path, content: str, *, newline: str = "\n") -> None:
    """UTF-8 写入文本；自动创建父目录。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding=UTF8, newline=newline) as f:
        f.write(content)


def write_bytes(path: Path, content: bytes) -> None:
    """写入二进制内容；自动创建父目录。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)


def sha256_file(path: Path) -> str:
    """计算文件 SHA-256（十六进制小写）。

    使用 ``iter_bytes`` 统一处理中文 / 空格路径下的二进制读取。
    """

    h = hashlib.sha256()
    for chunk in iter_bytes(path):
        h.update(chunk)
    return h.hexdigest()


def iter_bytes(path: Path, chunk_size: int = 65536) -> Iterator[bytes]:
    """以 64KB 块读取文件二进制内容，避免大配图一次性载入内存。"""

    with open_bytes(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            yield chunk


def ensure_dir(path: Path) -> Path:
    """``mkdir -p``，并返回绝对路径。"""

    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def resolve_under(parent: Path, child: Path) -> Path:
    """解析 ``child`` 为相对 ``parent`` 的路径，禁止越过 ``parent``。

    用于读取 ``配置/本期.toml`` 等用户可控字段，防止 ``issue_lockfile``
    被恶意指到 ``../`` 之外读取密钥。
    """

    parent_abs = parent.resolve()
    child_abs = (parent / child).resolve() if not child.is_absolute() else child.resolve()
    try:
        child_abs.relative_to(parent_abs)
    except ValueError as exc:  # pragma: no cover - 防御分支
        raise ValueError(f"路径越界：{child} 不在 {parent} 之下") from exc
    return child_abs


def list_issue_dirs(parent: Path) -> list[Path]:
    """列出 ``进行中/`` 或 ``存档/`` 下所有形如 ``YYYY-MM-DD-HH-MM-SS-专栏`` 的子目录，按名称倒序（最新在前）。"""

    if not parent.exists():
        return []
    out: list[Path] = []
    for entry in parent.iterdir():
        if not entry.is_dir():
            continue
        if entry.name.startswith("."):
            continue
        out.append(entry)
    out.sort(key=lambda p: p.name, reverse=True)
    return out


def _validate_issue_id(issue_id: str) -> None:
    if not issue_id:
        raise ValueError("issue_id 不能为空")
    if os.sep in issue_id or (os.altsep and os.altsep in issue_id):
        raise ValueError(f"issue_id 禁止包含路径分隔符：{issue_id!r}")
    if issue_id.startswith("."):
        raise ValueError(f"issue_id 禁止以点开头：{issue_id!r}")


def is_within(path: Path, ancestor: Path) -> bool:
    """判断 ``path`` 是否在 ``ancestor`` 子树内。"""

    try:
        path.resolve().relative_to(ancestor.resolve())
    except ValueError:
        return False
    return True


__all__ = [
    "UTF8",
    "REPO_ROOT",
    "repo_root",
    "in_progress_dir",
    "archive_dir",
    "config_dir",
    "prompt_dir",
    "issue_dir",
    "archived_issue_dir",
    "open_text",
    "open_bytes",
    "read_text",
    "write_text",
    "write_bytes",
    "sha256_file",
    "iter_bytes",
    "ensure_dir",
    "resolve_under",
    "list_issue_dirs",
    "is_within",
]