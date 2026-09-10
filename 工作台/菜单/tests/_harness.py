"""测试工具：临时仓库根。"""

from __future__ import annotations

import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterable

from 工作台.菜单 import paths as menu_paths


class TempRepo:
    """在临时目录构造一个最小化仓库根，便于菜单测试隔离。

    复制 ``默认.toml``、建立 ``进行中/`` / ``存档/`` / ``配置/`` /
    ``提示词/`` 子目录，并把 ``工作台.菜单.paths.REPO_ROOT`` 临时
    指向这里。退出 ``with`` 后恢复原值并删除临时目录。
    """

    def __init__(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup = self._tmp.cleanup
        for sub in ("进行中", "存档", "配置", "提示词", "工作台", "提示词"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        # 把 ``默认.toml`` 从真实仓库拷一份，保证 ``配置/默认.toml`` 存在。
        real_default = menu_paths.config_dir() / "默认.toml"
        target_default = self.root / "配置" / "默认.toml"
        if real_default.exists():
            target_default.write_bytes(real_default.read_bytes())
        self._prev_root = menu_paths.REPO_ROOT

    def __enter__(self) -> "TempRepo":
        menu_paths.REPO_ROOT = self.root
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        menu_paths.REPO_ROOT = self._prev_root
        self._tmp.cleanup()

    # 便捷方法

    def in_progress(self) -> Path:
        return self.root / "进行中"

    def archive(self) -> Path:
        return self.root / "存档"

    def config(self) -> Path:
        return self.root / "配置"

    def touch(self, relpath: str, content: str = "stub") -> Path:
        target = self.root / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target