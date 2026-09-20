"""去 AI 味润色（替代原返修循环）。

按用户改造要求：

- 审稿后从三篇中选优（review_1.recommendation），不再有返修轮次；
- 整篇一次性改写，温度 0.85；
- 硬约束保留标题、所有事实与证据编号、"你"语气；
- 不再抛 ``MaxRevisionsExceeded``；不切换 ``awaiting_human``。
"""

from __future__ import annotations

from pathlib import Path

from 工作台.接口 import ModelClient, ModelRequest
from 工作台.流水线.checkpoint import commit_stage
from 工作台.流水线.prompts import request_model_of, system_prompt


# 写在 writer 系统提示词之后；model 必须遵守这些硬约束再开始改写。
_DEAI_SYSTEM_SUFFIX = """
【本次任务：去 AI 味润色】
你的目标：把下面这篇稿件改写得更像真人写的公众号文章。整篇一次性改写，不要分段重排。

硬约束（不可违反）：
1. **第一行 Markdown 标题必须与原稿完全一致**（字符级相同），禁止添加「返修稿 N：」「修订版」「AI 改写版」等任何前缀或变体。
2. **保留所有事实陈述与证据编号**（如 [S12]、#E5、https://... 链接、ISO/IEC 42001 这类法条名称）。可以重新组织，但不能凭空添加新事实，也不能删除原文中的事实。
3. **保留「你」语气**，全文以「你」为主语；不要换成「我」「我们」「读者」。
4. **去除 AI 痕迹**：
   - 删除套话：「在这个时代」「值得注意的是」「综上所述」「总而言之」「让我们一起」「相信在不远的将来」「未来已来」「大有可为」「值得关注」
   - 删除反复总结、口号式结尾、明显排比堆叠
   - 删除清单里凑数的部分；清单若有事实价值可保留并改写句式
5. **只输出润色后的稿件正文**，不要写「以下是润色版」之类的额外说明。

执行：
- 一次整篇改写；不要分段落改写再拼接。
- 表达更口语化、有节奏；句式多样；长短句交错。
- 删除冗余与废话，但事实点必须保留。
""".strip()


class DeaiStage:
    """对优选稿做一次性去 AI 味润色，写入 ``待定稿/推荐稿.md``。"""

    def __init__(
        self,
        *,
        writer: ModelClient,
        snapshot_id: str,
        temperature: float = 0.85,
    ) -> None:
        if not 0.0 <= temperature <= 2.0:
            raise ValueError("deai temperature 必须在 0–2 之间")
        self.writer = writer
        self.snapshot_id = snapshot_id
        self.temperature = temperature

    def build_request(
        self,
        *,
        draft_text: str,
        source_titles: list[str] | None = None,
    ) -> ModelRequest:
        system = system_prompt("writer") + "\n\n" + _DEAI_SYSTEM_SUFFIX
        context_lines: list[str] = []
        if source_titles:
            context_lines.append(
                "可用资料标题（仅供改写时保持口径一致，不要替换原文证据编号）：\n"
                + "\n".join(f"- {t}" for t in source_titles)
            )
        context_lines.append("原稿：\n" + draft_text)
        return ModelRequest(
            role="writer",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": "\n\n".join(context_lines)},
            ],
            temperature=self.temperature,
            request_model=request_model_of(self.writer, "qwen3.7-plus"),
            snapshot_id=self.snapshot_id,
        )

    def run(
        self,
        state,
        *,
        issue_dir: str,
        draft_text: str,
        source_titles: list[str] | None = None,
    ):
        req = self.build_request(draft_text=draft_text, source_titles=source_titles)
        resp = self.writer.chat(req)
        if resp.raw_error:
            raise RuntimeError(f"deai 改写失败：{resp.raw_error}")
        new_text = resp.text

        # 写 待定稿/推荐稿.md —— finalizing 之前唯一对外可见的待定稿。
        pending_dir = Path(issue_dir) / "待定稿"
        pending_dir.mkdir(parents=True, exist_ok=True)
        (pending_dir / "推荐稿.md").write_text(new_text, encoding="utf-8")

        # 推进到 finalizing（备选标题 + 摘要 + 资料口径由 finalizing 阶段产出）。
        state = commit_stage(
            state,
            Path(issue_dir) / "运行记录",
            version_key="deai",
            text=new_text,
            event="finalizing",
        )
        return state, new_text


__all__ = ["DeaiStage"]