"""归档后由 MiniMax M3 生成三张配图的 ChatGPT Images 2.5 提示词。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from 工作台.接口 import ModelClient, ModelRequest
from 工作台.接入.config import ConfigError, load_default_config, load_local_config
from 工作台.接入.envfile import load_env_files
from 工作台.接入.models.client import ModelClient as RealModelClient


IMAGE_PROMPT_SYSTEM = (
    Path(__file__).resolve().parents[2] / "提示词" / "配图提示词-system.md"
).read_text(encoding="utf-8")
FORBIDDEN_STYLE_TOKENS = (
    "midjourney",
    "stable diffusion",
    "sdxl",
    "--ar",
    "--v ",
    "--stylize",
    "--seed",
    "cfg scale",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _build_minimax_planner() -> RealModelClient:
    """按本地配置构造 MiniMax M3 客户端，不读取或打印密钥值。"""

    root = _repo_root()
    load_env_files(root)
    try:
        cfg = load_local_config(root)
    except ConfigError:
        cfg = load_default_config(root)
    model_cfg = cfg.models["planner"]
    normalized = model_cfg.request_model.lower().replace("-", "")
    if normalized != "minimaxm3":
        raise RuntimeError(
            f"配图提示词要求使用 MiniMax M3，当前 planner 配置为 {model_cfg.request_model}"
        )
    return RealModelClient(model_cfg)


def _article_title(final_path: Path) -> str:
    match = re.match(r"^熵减进化室-公众号成稿-《(.+?)》\.md$", final_path.name)
    if match:
        return match.group(1)
    return final_path.stem


def _build_request(final_path: Path, article_text: str, request_model: str) -> ModelRequest:
    return ModelRequest(
        role="planner",
        messages=[
            {"role": "system", "content": IMAGE_PROMPT_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"正式文稿标题：{_article_title(final_path)}\n"
                    f"正式文稿文件名：{final_path.name}\n"
                    "请根据下面全文，写一条提交给 ChatGPT 官网图像生成界面的总提示词；"
                    "要求同一次生成请求一次性输出三张分别可用的图：一张封面图和两张文内配图。"
                    "不要写三条提示词，也不要要求分三次提交。\n\n"
                    f"正文：\n{article_text}"
                ),
            },
        ],
        temperature=0.4,
        max_tokens=5000,
        request_model=request_model,
        snapshot_id=str((_repo_root() / "配置" / "本期.toml").resolve()),
    )


def _parse_response(text: str) -> str:
    """解析并校验一条多图提示词，禁止把空响应写成成功产物。"""

    raw = text.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("配图提示词响应不是 JSON")
    try:
        data: Any = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError("配图提示词 JSON 无法解析") from exc
    if not isinstance(data, dict):
        raise ValueError("配图提示词 JSON 必须是对象")
    prompt = data.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("缺少多图配图提示词：prompt")
    lowered = prompt.lower()
    if any(token in lowered for token in FORBIDDEN_STYLE_TOKENS):
        raise ValueError("配图提示词包含旧模型参数或风格")
    return prompt.strip()


def _with_fixed_constraints(prompt: str) -> str:
    return (
        f"{prompt}\n\n"
        "请在同一次生成请求中一次性输出三张分别可用的独立图片，不要让用户分三次提交；"
        "不要拼贴、不要三联画：第 1 张为公众号首条封面图，"
        "900×383 px、2.35:1 横向窄幅，主体与视觉重心放在中央安全区，左右边缘只放可裁切装饰；"
        "第 2 张和第 3 张为两张不同叙事场景的文内配图，均为竖版 2:3，建议 1024×1536 px，"
        "保留上下留白，适合插入公众号正文。三张图统一米色纸张质感、深青、酒红、赭金点缀和纸媒插画气质。"
        "所有画面都不得出现文字、字母、数字、可读标签、水印、Logo、二维码或界面截图。"
    )


def _render(final_path: Path, prompt: str) -> str:
    return "\n".join(
        [
            f"# {final_path.stem} · 配图提示词",
            "",
            "> 目标图像模型：ChatGPT Images 2.5",
            "> 以下只有一条总提示词；在 ChatGPT 官网提交一次，要求同一次生成返回三张分别可用的图像。",
            "",
            "## 一条多图生图提示词",
            "",
            _with_fixed_constraints(prompt),
            "",
        ]
    )


def generate_image_prompt_file(
    final_path: Path,
    *,
    planner: ModelClient | None = None,
) -> Path:
    """调用 MiniMax M3，为已归档正式稿写入三图提示词文件。"""

    if not final_path.is_file():
        raise FileNotFoundError(f"正式文稿不存在：{final_path}")
    client = planner or _build_minimax_planner()
    request_model = getattr(getattr(client, "config", None), "request_model", "MiniMax-M3")
    normalized = str(request_model).lower().replace("-", "")
    if normalized != "minimaxm3":
        raise RuntimeError(f"配图提示词要求 MiniMax M3，当前请求模型为 {request_model}")
    response = client.chat(
        _build_request(
            final_path,
            final_path.read_text(encoding="utf-8"),
            str(request_model),
        )
    )
    if response.raw_error:
        raise RuntimeError(f"MiniMax M3 生成配图提示词失败：{response.raw_error}")
    prompt = _parse_response(response.text)
    output = final_path.with_name(f"{final_path.stem}-配图提示词.md")
    tmp = output.with_suffix(output.suffix + ".tmp")
    tmp.write_text(_render(final_path, prompt), encoding="utf-8")
    tmp.replace(output)
    return output


__all__ = ["generate_image_prompt_file"]
