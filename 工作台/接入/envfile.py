"""读写 gitignore 的 ``.env`` / ``配置/凭据/.env``，不把密钥打进日志。"""

from __future__ import annotations

import os
from pathlib import Path


def parse_env_text(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            out[key] = value
    return out


def load_env_files(repo_root: str | Path) -> None:
    root = Path(repo_root)
    for path in (root / ".env", root / "配置" / "凭据" / ".env"):
        if not path.is_file():
            continue
        for key, value in parse_env_text(path.read_text(encoding="utf-8")).items():
            if key not in os.environ or os.environ.get(key, "").strip() == "":
                os.environ[key] = value


def upsert_env_file(path: str | Path, values: dict[str, str]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    current: dict[str, str] = {}
    if target.exists():
        current = parse_env_text(target.read_text(encoding="utf-8"))
    current.update({k: v for k, v in values.items() if v})
    lines = ["# 本地凭据，禁止提交", ""]
    for key in sorted(current):
        lines.append(f"{key}={current[key]}")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for key, value in values.items():
        if value:
            os.environ[key] = value
    return target
