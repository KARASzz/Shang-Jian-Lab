"""菜单 5：确认手改稿 / 定稿并归档。

按 :mod:`AGENTS.md` 「停手等用户改」与 :mod:`进行中/README.md`：

- 检测到期内推荐稿或手改稿时，先展示自动命名与归档动作；用户确认
  后按正文标题生成 ``熵减进化室-公众号成稿-《…》.md`` 并直接归档。
- ``熵减进化室-公众号成稿-《…》.md`` 是定稿，**最高优先级**。
- 若目标位置已存在带书名号的定稿，必须显式二次确认才覆盖。
- 自动流程不得触发覆盖（``auto_overwrite=False``）。

实现要点：

- 使用 :func:`shutil.copy2` 保留 mtime，便于审稿追溯。
- 手动导入外部稿件时，把定稿放到 ``进行中/<issue>/待定稿/`` 下；
  期内稿件则由一键确认流程按正文标题自动命名。
- 不读 / 不写 ``带书名号`` 以外的同名已存在文件除非用户确认。
"""

from __future__ import annotations

import dataclasses
import json
import re
import shlex
import shutil
from pathlib import Path

from .. import paths, prompt

# 仅识别 ``熵减进化室-公众号成稿-《...》.md`` 形式的文件名；定稿
# 文件名前缀源自 AGENTS.md §「仓库结构」，必须保持一致。
FINAL_NAME_RE = re.compile(r"^熵减进化室-公众号成稿-《(.+?)》\.md$")

# 目标位置。
DEST_SUBDIR = "待定稿"
RECOMMENDATION_NAME = "推荐稿.md"
SUPPORTING_NAMES = {RECOMMENDATION_NAME, "备选标题.md", "摘要与资料口径.md"}


@dataclasses.dataclass(frozen=True)
class ImportResult:
    """导入结果，便于测试断言。"""

    source: Path
    dest: Path
    is_final: bool
    overwrote: bool


def is_final_filename(name: str) -> bool:
    """文件名是否符合定稿 ``《…》`` 命名。"""

    return bool(FINAL_NAME_RE.match(name))


def _dest_dir(issue_root: Path) -> Path:
    return paths.ensure_dir(issue_root / DEST_SUBDIR)


def _clean_title(raw: str) -> str:
    """清理 Markdown 标题，使其可安全放入文件名。"""

    title = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", raw)
    title = re.sub(r"[*_`~]", "", title)
    title = re.sub(r"[\\/\x00-\x1f\x7f]", "-", title)
    title = re.sub(r"\s+", " ", title).strip(" .")
    return title[:80]


def extract_document_title(source: Path, issue_root: Path | None = None) -> str:
    """从稿件标题提取归档名；必要时使用该期已选题目作明确兜底。"""

    text = source.read_text(encoding="utf-8")
    for line in text.splitlines():
        match = re.match(r"^\s*#{1,6}\s+(.+?)\s*#*\s*$", line)
        if match:
            title = _clean_title(match.group(1))
            if title and title not in {"推荐稿", "手改稿"}:
                return title
        match = re.match(r"^\s*(?:标题|题目)\s*[:：]\s*(.+?)\s*$", line)
        if match:
            title = _clean_title(match.group(1))
            if title:
                return title

    filename_match = re.match(r"^《(.+?)》\.md$", source.name)
    if not filename_match:
        filename_match = FINAL_NAME_RE.match(source.name)
    if filename_match:
        title = _clean_title(filename_match.group(1))
        if title:
            return title

    if issue_root is not None:
        selected = issue_root / "选题" / "选定.json"
        if selected.exists():
            try:
                data = json.loads(selected.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
            title = _clean_title(str(data.get("topic", ""))) if isinstance(data, dict) else ""
            if title:
                return title
    raise ValueError(f"未找到稿件标题：{source.name}；请在正文中加入 Markdown 标题（# 标题）")


def final_filename(title: str) -> str:
    """根据标题生成规范定稿文件名。"""

    cleaned = _clean_title(title)
    if not cleaned:
        raise ValueError("稿件标题为空，无法生成定稿文件名")
    return f"熵减进化室-公众号成稿-《{cleaned}》.md"


def _find_auto_finalize_source(issue_root: Path) -> Path | None:
    """优先发现期目录内的定稿/手改稿，供菜单 5 一键确认。"""

    pending = issue_root / DEST_SUBDIR
    if not pending.exists():
        return None
    candidates = [p for p in pending.glob("*.md") if p.name not in SUPPORTING_NAMES]
    canonical = [p for p in candidates if is_final_filename(p.name)]
    if canonical:
        return sorted(canonical, key=lambda p: p.stat().st_mtime, reverse=True)[0]
    if candidates:
        return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0]
    recommendation = pending / RECOMMENDATION_NAME
    return recommendation if recommendation.exists() else None


def normalize_source_path(raw: str) -> Path:
    """把粘贴/拖拽产生的 shell 转义路径还原为本地路径。

    macOS 终端拖拽路径常把空格和 ``+`` 写成 ``\\ `` / ``\\+``；
    某些编辑器还会再加一层反斜杠。优先保留原始路径，只有原始路径
    不存在时才尝试 shell 解析和反斜杠还原。
    """

    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1]
    candidates: list[str] = [text]
    try:
        tokens = shlex.split(text, posix=True)
    except ValueError:
        tokens = []
    if len(tokens) == 1:
        candidates.append(tokens[0])

    # 兼容 UI 复制出来的双重转义，例如 ``\\\\+Python``。
    collapsed = text
    while "\\\\" in collapsed:
        collapsed = collapsed.replace("\\\\", "\\")
    collapsed = re.sub(r"\\(?=[\s+])", "", collapsed)
    candidates.append(collapsed)

    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if Path(candidate).exists():
            return Path(candidate)
    return Path(candidates[-1])


def _ensure_issue() -> Path | None:
    """返回最新进行中目录；不存在返回 ``None``。"""

    candidates = paths.list_issue_dirs(paths.in_progress_dir())
    return candidates[0] if candidates else None


def import_final(
    source: Path,
    issue_root: Path,
    *,
    confirm_callback=prompt.confirm,
) -> ImportResult:
    """把用户手改稿 / 定稿拷入 ``待定稿/``。

    约束：

    - 目标位置已存在时，**必须**通过 ``confirm_callback`` 取得用户
      显式确认；测试可通过注入回调跳过交互。
    - 自动流程（无回调授权）等价于 ``confirm_callback`` 返回
      ``False``，因此默认安全。
    """

    if not source.exists():
        raise FileNotFoundError(f"源文件不存在：{source}")
    if not source.is_file():
        raise ValueError(f"源路径不是文件：{source}")
    final = is_final_filename(source.name)
    target_dir = _dest_dir(issue_root)
    dest = target_dir / source.name
    if source.resolve() == dest.resolve():
        raise ValueError(f"源文件已经在待定稿目录，无需重复导入：{source}")
    overwrote = False
    if dest.exists():
        if not confirm_callback(f"目标已存在 {dest.name}，确认覆盖？", default_no=True):
            raise PermissionError(f"目标已存在且未获授权覆盖：{dest}")
        overwrote = True
    shutil.copy2(source, dest)
    return ImportResult(source=source.resolve(), dest=dest.resolve(), is_final=final, overwrote=overwrote)


def finalize_and_archive(issue_root: Path, source: Path):
    """把期内稿件按正文标题命名，并直接归档。"""

    title = extract_document_title(source, issue_root)
    final_path = source.parent / final_filename(title)
    if source.resolve() != final_path.resolve():
        source.replace(final_path)

    from . import archive

    result = archive.archive_issue(
        issue_root.name,
        confirm_callback=lambda *args, **kwargs: True,
    )
    return title, final_path, result


def run(io) -> None:
    """交互入口。"""

    io.println("【5 导入手改稿 / 定稿】")
    issue_root = _ensure_issue()
    if issue_root is None:
        io.println("当前没有进行中任务，请先用 1 号菜单建期。")
        return
    auto_source = _find_auto_finalize_source(issue_root)
    if auto_source is not None:
        try:
            title = extract_document_title(auto_source, issue_root)
            target_name = final_filename(title)
        except (OSError, ValueError) as exc:
            io.println(f"无法自动定稿：{exc}")
            return
        io.println(f"检测到稿件：{auto_source.name}")
        io.println(f"将自动命名为：{target_name}")
        io.println("确认后将把该稿件作为本期定稿并直接归档。")
        io.println("按 Y 确认归档；按 N 取消，不修改文件。")
        if not prompt.confirm("确认定稿并归档？", default_no=True):
            io.println("已取消，文件未修改。")
            return
        try:
            _title, final_path, result = finalize_and_archive(issue_root, auto_source)
        except (FileNotFoundError, FileExistsError, PermissionError, RuntimeError, ValueError, OSError) as exc:
            io.println(f"定稿归档失败：{exc}")
            return
        io.println(f"已自动生成定稿：{final_path.name}")
        io.println(f"已完成归档：{result.dst}")
        return
    io.print("请把手改稿 / 定稿绝对路径拖入（或粘贴）：")
    raw = io.read_line().strip()
    if not raw:
        io.println("未提供路径。")
        return
    # 处理用户用引号包裹路径或带尾部空格的情况
    source = normalize_source_path(raw)
    try:
        result = import_final(source, issue_root)
    except FileNotFoundError as exc:
        io.println(f"导入失败：{exc}")
        return
    except ValueError as exc:
        io.println(f"导入未执行：{exc}")
        return
    except PermissionError as exc:
        io.println(f"导入未执行：{exc}")
        return
    kind = "定稿" if result.is_final else "手改稿"
    io.println(f"已导入{kind}：{result.dest}")
    if result.overwrote:
        io.println("（已覆盖既有同名文件，请确认手改稿未被自动流程替换。）")


__all__ = [
    "DEST_SUBDIR",
    "RECOMMENDATION_NAME",
    "FINAL_NAME_RE",
    "ImportResult",
    "extract_document_title",
    "final_filename",
    "finalize_and_archive",
    "import_final",
    "is_final_filename",
    "normalize_source_path",
    "run",
]
