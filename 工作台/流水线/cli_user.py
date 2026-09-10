"""默认终端 UserInput，供菜单续跑时注入。"""

from __future__ import annotations


class CliUser:
    def choose_topic(self, candidates: list[str]) -> int | str:
        for i, item in enumerate(candidates, 1):
            print(f"{i}. {item}")
        raw = input("选题编号或自拟：").strip()
        if raw.isdigit():
            return int(raw)
        return raw

    def confirm(self, prompt: str) -> bool:
        raw = input(f"{prompt} [y/N]: ").strip().lower()
        return raw in {"y", "yes", "是", "好"}
