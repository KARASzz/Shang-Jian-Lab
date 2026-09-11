"""默认终端 UserInput，供菜单续跑时注入。"""

from __future__ import annotations

from pathlib import Path


class CliUser:
    def choose_topic(
        self, candidates: list[str], *, issue_dir: str | None = None
    ) -> int | str:
        # 先把全部候选落盘到 issue_dir/选题/选题-候选-临时.md，避免 IDE
        # 终端 scrollback 截断后用户看不到后面的条目；之后再 print + input。
        if issue_dir:
            tmp = Path(issue_dir) / "选题" / "选题-候选-临时.md"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(
                "\n".join(f"{i}. {c}" for i, c in enumerate(candidates, 1)) + "\n",
                encoding="utf-8",
            )
            print(f"（完整 {len(candidates)} 条已存档：{tmp}）")
        for i, item in enumerate(candidates, 1):
            print(f"{i}. {item}")
        while True:
            raw = input("选题编号或自拟（必填，Ctrl-C 返回）：").strip()
            if not raw:
                print("还未选题，请输入编号或自拟选题。", flush=True)
                continue
            if raw.isdigit():
                number = int(raw)
                if not 1 <= number <= len(candidates):
                    print(f"请输入 1–{len(candidates)} 之间的编号。", flush=True)
                    continue
                return number
            return raw

    def confirm(self, prompt: str) -> bool:
        raw = input(f"{prompt} [y/N]: ").strip().lower()
        return raw in {"y", "yes", "是", "好"}
