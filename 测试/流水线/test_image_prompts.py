"""归档后配图提示词生成：一次请求输出一条三图总提示词。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from 工作台.接口 import ModelResponse
from 工作台.流水线 import image_prompts


class _FakePlanner:
    config = type("Config", (), {"request_model": "MiniMax-M3"})()

    def __init__(self, text: str) -> None:
        self.text = text
        self.requests = []

    def chat(self, request):
        self.requests.append(request)
        return ModelResponse(
            text=self.text,
            request_model=request.request_model,
            served_model="MiniMax-M3",
        )


class ImagePromptTests(unittest.TestCase):
    def test_one_prompt_requests_three_images_in_one_submission(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            final = Path(tmp) / "熵减进化室-公众号成稿-《评测榜第一为何无法复现》.md"
            final.write_text("# 评测榜第一为何无法复现\n\n正文", encoding="utf-8")
            planner = _FakePlanner(
                json.dumps(
                    {
                        "prompt": (
                            "请在同一次生成请求中一次性输出三张分别可用的图片，"
                            "第一张是中央安全区的公众号封面，另外两张是不同叙事场景的文内图。"
                        )
                    },
                    ensure_ascii=False,
                )
            )

            output = image_prompts.generate_image_prompt_file(final, planner=planner)

            self.assertEqual(
                output.name,
                "熵减进化室-公众号成稿-《评测榜第一为何无法复现》-配图提示词.md",
            )
            rendered = output.read_text(encoding="utf-8")
            self.assertIn("## 一条多图生图提示词", rendered)
            self.assertIn("同一次生成请求", rendered)
            self.assertIn("900×383", rendered)
            self.assertIn("2:3", rendered)
            self.assertEqual(len(planner.requests), 1)
            self.assertEqual(planner.requests[0].request_model, "MiniMax-M3")
            self.assertIn("ChatGPT 官网", planner.requests[0].messages[1]["content"])

    def test_old_image_model_syntax_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            final = Path(tmp) / "熵减进化室-公众号成稿-《测试》.md"
            final.write_text("# 测试\n\n正文", encoding="utf-8")
            planner = _FakePlanner(json.dumps({"prompt": "生成三张图 --ar 2:3"}))

            with self.assertRaisesRegex(ValueError, "旧模型参数"):
                image_prompts.generate_image_prompt_file(final, planner=planner)


if __name__ == "__main__":
    unittest.main()
