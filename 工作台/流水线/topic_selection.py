"""选题（PLAN §3 步骤 1）。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from 工作台.接口 import ModelClient, ModelRequest, UserInput
from 工作台.流水线.checkpoint import commit_stage
from 工作台.流水线.prompts import request_model_of, system_prompt

# 仅挑以编号开头的行（"1. ..." / "1、..." / "1) ..."），剔除标题、立意、
# 空行、Markdown 围栏。planner 必须给齐恰好 5 个编号行。
_CANDIDATE_LINE = re.compile(r"^\s*\d+\s*[\.、)]\s*\S")


class TopicSelectionStage:
    """调 planner 拿 5 候选 → 用户选/自选。"""

    def __init__(
        self,
        *,
        planner: ModelClient,
        user: UserInput,
        snapshot_id: str,
        require_research: bool = False,
    ) -> None:
        self.planner = planner
        self.user = user
        self.snapshot_id = snapshot_id
        self.require_research = require_research

    def build_request(
        self,
        *,
        column: str,
        recent_issues: list[str],
        research_summary: str = "",
    ) -> ModelRequest:
        research_block = ""
        if research_summary.strip():
            research_block = (
                "\n\n两轮选题研究摘要（候选必须基于其中的来源，不得凭空补充）：\n"
                f"{research_summary.strip()}\n"
            )
        messages = [
            {"role": "system", "content": system_prompt("planner")},
            {
                "role": "user",
                "content": (
                    f"专栏：{column}\n"
                    f"近期选题：{', '.join(recent_issues) or '（无）'}\n\n"
                    f"{research_block}"
                    "请给出**恰好 5 个**候选选题，每个 1 句立意。\n"
                    "每个候选必须能回指研究摘要中的至少一个来源；优先选择有数据、争议或反常识证据支撑的方向。\n"
                    "输出格式必须严格遵守（编号 + 标题 + 立意各占 1 行；不要标题层级、不要围栏）：\n"
                    "1. **标题 A**\n"
                    "   立意：...\n"
                    "   证据：填入研究摘要中真实存在的来源 ID\n"
                    "2. **标题 B**\n"
                    "   立意：...\n"
                    "   证据：填入研究摘要中真实存在的来源 ID\n"
                    "3. **标题 C**\n"
                    "   立意：...\n"
                    "   证据：填入研究摘要中真实存在的来源 ID\n"
                    "4. **标题 D**\n"
                    "   立意：...\n"
                    "   证据：填入研究摘要中真实存在的来源 ID\n"
                    "5. **标题 E**\n"
                    "   立意：...\n"
                    "   证据：填入研究摘要中真实存在的来源 ID\n"
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

    def parse_candidates(
        self,
        text: str,
        *,
        require_evidence: bool = False,
        allowed_evidence_ids: set[str] | None = None,
    ) -> list[str]:
        """只挑以编号开头的行；剔除标题、立意、空行。

        返回 ``["1. **标题**\\n   立意：...", ...]``，每条把"标题 + 立意"两行
        拼成一段文本，便于 render 时直接呈现。
        """

        lines = text.splitlines()
        numbered_indexes: list[int] = [
            i for i, ln in enumerate(lines) if _CANDIDATE_LINE.match(ln)
        ]
        if len(numbered_indexes) != 5:
            raise ValueError(
                f"planner 必须给出恰好 5 个编号选题（实际 {len(numbered_indexes)} 个）"
            )
        numbers = [int(re.match(r"^\s*(\d+)", lines[i]).group(1)) for i in numbered_indexes]
        if numbers != [1, 2, 3, 4, 5]:
            raise ValueError(f"planner 的选题编号必须连续为 1–5（实际 {numbers}）")

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
        if require_evidence:
            missing = [
                str(index + 1)
                for index, chunk in enumerate(chunks)
                if not re.search(
                    r"(?:tavily|brave|bing)-\d+-\d+",
                    chunk,
                    re.IGNORECASE,
                )
            ]
            if missing:
                raise ValueError(
                    f"planner 的候选缺少证据指针：第 {', '.join(missing)} 条"
                )
            if allowed_evidence_ids is not None:
                invalid = []
                for index, chunk in enumerate(chunks):
                    ids = set(re.findall(r"(?:tavily|brave|bing)-\d+-\d+", chunk, re.IGNORECASE))
                    if not ids & allowed_evidence_ids:
                        invalid.append(str(index + 1))
                if invalid:
                    raise ValueError(
                        f"planner 引用了未验证的证据 ID：第 {', '.join(invalid)} 条"
                    )
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
        research_summary = ""
        allowed_evidence_ids: set[str] | None = None
        if self.require_research:
            research_path = topic_dir / "研究" / "研究摘要.md"
            if not research_path.exists():
                raise RuntimeError("缺少两轮选题研究，不能生成 5 个候选选题")
            research_summary = research_path.read_text(encoding="utf-8")
            if "## 第 1 轮" not in research_summary or "## 第 2 轮" not in research_summary:
                raise RuntimeError("选题研究不完整，必须完成两轮后才能生成候选")
            allowed_evidence_ids = set()
            for round_no in (1, 2):
                payload_path = topic_dir / "研究" / f"第{round_no}轮-搜索.json"
                if not payload_path.exists():
                    raise RuntimeError(f"缺少选题研究第 {round_no} 轮来源记录")
                payload = json.loads(payload_path.read_text(encoding="utf-8"))
                allowed_evidence_ids.update(
                    str(source["id"])
                    for source in payload.get("sources", [])
                    if source.get("status") == "ok" and source.get("url")
                )
            if not allowed_evidence_ids:
                raise RuntimeError("两轮选题研究没有可供候选引用的有效来源")
        cache = topic_dir / "候选.json"
        if cache.exists():
            candidates = json.loads(cache.read_text(encoding="utf-8"))
            if (not isinstance(candidates, list) or len(candidates) != 5
                    or any(not isinstance(c, str) or not c.strip() for c in candidates)):
                raise ValueError("选题候选记录无效，请重新生成候选")
            if self.require_research:
                self.parse_candidates(
                    "\n".join(candidates),
                    require_evidence=True,
                    allowed_evidence_ids=allowed_evidence_ids,
                )
        else:
            req = self.build_request(
                column=column,
                recent_issues=recent_issues,
                research_summary=research_summary,
            )
            resp = self.planner.chat(req)
            if resp.raw_error:
                raise RuntimeError(f"生成选题失败：{resp.raw_error}")
            candidates = self.parse_candidates(
                resp.text,
                require_evidence=self.require_research,
                allowed_evidence_ids=allowed_evidence_ids,
            )
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
