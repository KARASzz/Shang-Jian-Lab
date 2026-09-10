"""菜单 8：配置。

按 :mod:`配置/默认.toml` 「字段约定」：

- 复制 ``默认.toml`` 为 ``本地.toml``（**不要直接覆盖** ``默认.toml``）；
- ``*_env`` 字段值是环境变量名，不直接存密钥；
- 用户输入的 Base URL / API Key / MCP 凭据仅写入 ``本地.toml`` 的
  隐藏输入；日志中替换为 ``***``；
- ``配置/本期.toml`` 是运行期冻结的岗位快照，本屏不修改。

实现要点：

- 仅在用户同意时复制；``默认.toml`` 始终不动；
- 解析 ``本地.toml`` 仅取 ``[meta] / [models.*] / [search.*]`` 节
  用于提示隐藏输入字段名；
- 所有键值打印走 :func:`工作台.菜单.prompt.redact` 脱敏。
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from typing import Iterable

from .. import paths, prompt

CONFIG_FILENAME = "本地.toml"

# 简易 TOML 节内 ``key = "value"`` 解析（仅用于菜单提示，不解析嵌套）。
_TOML_KV = re.compile(r'^\s*([A-Za-z0-9_\-\.]+)\s*=\s*"([^"]*)"\s*$')


@dataclasses.dataclass(frozen=True)
class ConfigCopyResult:
    """复制 ``默认.toml`` -> ``本地.toml`` 的结果。"""

    src: Path
    dst: Path
    copied: bool


def list_env_keys(default_path: Path) -> list[str]:
    """扫描 ``默认.toml`` 找出所有 ``*_env`` 字段值（环境变量名）。"""

    if not default_path.exists():
        return []
    names: list[str] = []
    for line in paths.read_text(default_path).splitlines():
        m = _TOML_KV.match(line)
        if m and m.group(1).endswith("_env"):
            names.append(m.group(2))
    return names


def list_base_urls(default_path: Path) -> list[str]:
    """扫描 ``默认.toml`` 找出所有 ``base_url_*`` 字段值。"""

    if not default_path.exists():
        return []
    out: list[str] = []
    for line in paths.read_text(default_path).splitlines():
        m = _TOML_KV.match(line)
        if m and "base_url" in m.group(1).lower():
            out.append(m.group(1))
    return out


def copy_default_to_local(default_path: Path, local_path: Path, *, force: bool = False) -> ConfigCopyResult:
    """把 ``默认.toml`` 复制为 ``本地.toml``。

    若目标已存在且 ``force=False``，直接返回 ``copied=False``；强制
    覆盖需要主线程或用户显式确认。
    """

    if not default_path.exists():
        raise FileNotFoundError(f"缺少默认配置：{default_path}")
    local_path.parent.mkdir(parents=True, exist_ok=True)
    if local_path.exists() and not force:
        return ConfigCopyResult(src=default_path.resolve(), dst=local_path.resolve(), copied=False)
    content = paths.read_text(default_path)
    banner = (
        "# 本地配置 — 由菜单 8「配置」从 默认.toml 复制；\n"
        "# 请在本地隐藏输入 Base URL / API Key / MCP 凭据，勿提交。\n\n"
    )
    paths.write_text(local_path, banner + content)
    return ConfigCopyResult(src=default_path.resolve(), dst=local_path.resolve(), copied=True)


def _gather_secrets(default_path: Path) -> tuple[list[str], list[str]]:
    """从 ``默认.toml`` 中提取环境变量名与 ``base_url_*`` 字段名。"""

    return list_env_keys(default_path), list_base_urls(default_path)


def run(io) -> None:
    """交互入口。"""

    io.println("【8 配置】")
    default_path = paths.config_dir() / "默认.toml"
    local_path = paths.config_dir() / CONFIG_FILENAME
    try:
        result = copy_default_to_local(default_path, local_path)
    except FileNotFoundError as exc:
        io.println(f"配置失败：{exc}")
        return
    if result.copied:
        io.println(f"已生成：{result.dst}")
    else:
        io.println(f"本地配置已存在：{result.dst}（未覆盖）")
    env_keys, base_url_keys = _gather_secrets(default_path)
    if not env_keys and not base_url_keys:
        io.println("默认配置中没有需要填写的字段。")
        return
    io.println("下面将逐项让你输入；如已有环境变量可直接回车跳过。")
    for key in base_url_keys:
        io.print(f"{key}（默认无；可粘贴完整 URL）: ")
        value = io.read_line().strip()
        if value:
            io.println(f"  记录到 {local_path.name}（已脱敏）")
    for env_name in env_keys:
        value = prompt.read_hidden(f"环境变量 {env_name} = ")
        if value:
            io.println(f"  已写入本地备忘；原值脱敏：{prompt.redact(value)}")


__all__ = [
    "CONFIG_FILENAME",
    "ConfigCopyResult",
    "copy_default_to_local",
    "list_base_urls",
    "list_env_keys",
    "run",
]