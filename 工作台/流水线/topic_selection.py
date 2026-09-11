"""选题（PLAN §3 步骤 1）。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from 工作台.接口 import ModelClient, ModelRequest, UserInput
from 工作台.流水线.checkpoint import commit_stage
from 工作台.流水线.prompts import request_model_of, system_prompt

# 仅挑以编号开头的行（"1. ..." / "1、..." / "1) ..."），剔除标题、立意、
# 空行、Markdown 围栏。planner 必须给齐恰好 5 个编号行，少于 5 抛错。
_CANDIDATE_LINE = re.compile(r"^\s*\d+\s*[\.、)]\s*\S")


class TopicSelectionStage:
    """调 planner 拿 5 候选 → 用户选/自选。"""

    def __init__(
        self,
        *,
        planner: ModelClient,
        user: UserInput,
        snapshot_id: str,
    ) -> None:
        self.planner = planner
        self.user = user
        self.snapshot_id = snapshot_id

    def build_request(self, *, column: str, recent_issues: list[str]) -> ModelRequest:
        messages = [
            {"role": "system", "content": system_prompt("planner")},
            {
                "role": "user",
                "content": (
                    f"专栏：{column}\n"
                    f"近期选题：{', '.join(recent_issues) or '（无）'}\n\n"
                    "请给出**恰好 5 个**候选选题，每个 1 句立意。\n"
                    "输出格式必须严格遵守（编号 + 标题 + 立意各占 1 行；不要标题层级、不要围栏）：\n"
                    "1. **标题 A**\n"
                    "   立意：...\n"
                    "2. **标题 B**\n"
                    "   立意：...\n"
                    "3. **标题 C**\n"
                    "   立意：...\n"
                    "4. **标题 D**\n"
                    "   立意：...\n"
                    "5. **标题 E**\n"
                    "   立意：...\n"
                ),
            },
        ]
        return ModelRequest(
            role="planner",
            messages=messages,
            temperature=0.4,
            request_model=request_model_of(self.planner, "MiniMax-M3"),
            snapshot_id=self.snapshot_id,
        )

    def parse_candidates(self, text: str) -> list[str]:
        """只挑以编号开头的行；剔除标题、立意、空行。

        返回 ``["1. **标题**\\n   立意：...", ...]``，每条把"标题 + 立意"两行
        拼成一段文本，便于 render 时直接呈现。
        """

        lines = text.splitlines()
        numbered_indexes: list[int] = [
            i for i, ln in enumerate(lines) if _CANDIDATE_LINE.match(ln)
        ]
        if len(numbered_indexes) < 5:
            raise ValueError(
                f"planner 未给出 5 个编号选题（实际 {len(numbered_indexes)} 个）"
            )

        # 把每个编号行连同紧跟的非编号行（通常是"立意：..."缩进行）合并成一段
        chunks: list[str] = []
        for idx, start in enumerate(numbered_indexes[:5]):
            end = numbered_indexes[idx + 1] if idx + 1 < len(numbered_indexes) else len(lines)
            block_lines: list[str] = [lines[start].rstrip()]
            for j in range(start + 1, end):
                cont = lines[j]
                if not cont.strip():
                    continue
                # 立意行通常是缩进 3 空格的 "立意：..."；其它非空非编号行也带上
                block_lines.append(cont.rstrip())
            chunks.append("\n".join(block_lines))
        return chunks

    def render_markdown(self, column: str, candidates: list[str], choice: str) -> str:
        body = [f"# {column} · 选题候选", ""]
        for i, c in enumerate(candidates, 1):
            body.append(f"{i}. {c}")
        body += ["", f"用户最终选择：{choice}"]
        return "\n".join(body) + "\n"

    def run(
        self,
        state,
        *,
        issue_dir: str,
        column: str,
        recent_issues: list[str],
    ):
        """返回 ``(new_state, markdown)``。"""
        topic_dir = Path(issue_dir) / "选题"
        topic_dir.mkdir(parents=True, exist_ok=True)
        cache = topic_dir / "候选.json"
        if cache.exists():
            candidates = json.loads(cache.read_text(encoding="utf-8"))
            if (not isinstance(candidates, list) or len(candidates) != 5
                    or any(not isinstance(c, str) or not c.strip() for c in candidates)):
                raise ValueError("选题候选记录无效，请重新生成候选")
        else:
            req = self.build_request(column=column, recent_issues=recent_issues)
            resp = self.planner.chat(req)
            if resp.raw_error:
                raise RuntimeError(f"生成选题失败：{resp.raw_error}")
            candidates = self.parse_candidates(resp.text)
            cache.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
        choice_raw = self.user.choose_topic(candidates, issue_dir=issue_dir)
        if type(choice_raw) is int:
            if not (1 <= choice_raw <= len(candidates)):
                raise ValueError("用户选择超出候选范围")
            choice = candidates[choice_raw - 1]
        elif isinstance(choice_raw, str) and choice_raw.strip():
            choice = choice_raw.strip()
        else:
            raise ValueError("尚未选择选题，不能开始下一步")
        md = self.render_markdown(column, candidates, choice)

        topic_dir = Path(issue_dir) / "选题"
        topic_dir.mkdir(parents=True, exist_ok=True)
        (topic_dir / "选题-候选.md").write_text(md, encoding="utf-8")
        (topic_dir / "选定.json").write_text(
            json.dumps({"topic": choice, "column": column}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        state = commit_stage(
            state,
            Path(issue_dir) / "运行记录",
            version_key="topic_selection",
            text=md,
        )
        return state, md


__all__ = ["TopicSelectionStage"]
