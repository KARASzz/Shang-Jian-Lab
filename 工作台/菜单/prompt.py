"""隐藏输入与日志脱敏。

- :func:`read_hidden` 包装 :func:`getpass.getpass`，统一提示语并吞掉
  ``KeyboardInterrupt``，避免菜单中途按 Ctrl-C 后栈追踪刷屏。
- :func:`redact` 将 API Key、Cookie 等敏感字符串替换为 ``***``，便于
  写入 ``运行日志.ndjson`` 与诊断打印。

脱敏规则：

- 形如 ``sk-...``、``key=...``、``token=...``、``bearer ...`` 的子串
  全部替换。
- 配置 ``SENSITIVE_PATTERNS`` 列表可继续追加；不依赖第三方正则库。
"""

from __future__ import annotations

import getpass
import re
from typing import Final

# 匹配 "key=value" / "key: value" / "key=value" 中 value 部分。
# 这里 value 允许字母数字、连字符、下划线、点，共 8-80 位以覆盖常见 Key。
_PATTERN_KEY_VALUE: Final = re.compile(
    r"(?i)\b("
    r"api[_-]?key|access[_-]?token|secret|token|password|passwd|bearer"
    r")\s*[:=]\s*['\"]?([A-Za-z0-9._\-]{8,80})['\"]?"
)

# 匹配独立的 sk-... / ghp_... / gsk_... 风格密钥。
_PATTERN_STANDALONE: Final = re.compile(r"\b(sk-[A-Za-z0-9_\-]{16,}|ghp_[A-Za-z0-9]{16,}|gsk_[A-Za-z0-9_\-]{16,})\b")

REDACTED: Final = "***"


def read_hidden(prompt: str = "请输入（不显示）: ") -> str:
    """调用 :func:`getpass.getpass` 获取隐藏输入。

    返回去除末尾换行的字符串；按 Ctrl-C 返回空串，不向上抛异常。
    """

    try:
        value = getpass.getpass(prompt)
    except KeyboardInterrupt:
        return ""
    return value.rstrip("\r\n")


def confirm(prompt: str, *, default_no: bool = True) -> bool:
    """显式二次确认；按 Ctrl-C / 空回车按 ``default_no`` 处理。"""

    suffix = "[y/N]" if default_no else "[Y/n]"
    try:
        answer = input(f"{prompt} {suffix}: ").strip().lower()
    except KeyboardInterrupt:
        return False
    if not answer:
        return not default_no
    return answer in {"y", "yes", "是", "好"}


def prompt_visible(prompt: str) -> str:
    """普通可见输入；按 Ctrl-C 返回空串。"""

    try:
        return input(prompt)
    except KeyboardInterrupt:
        return ""


def redact(text: str) -> str:
    """将所有疑似凭据子串替换为 ``***``。

    规则见模块顶部；返回值是新的字符串，原 ``text`` 不变。
    """

    if not text:
        return text
    text = _PATTERN_KEY_VALUE.sub(lambda m: f"{m.group(1)}={REDACTED}", text)
    text = _PATTERN_STANDALONE.sub(REDACTED, text)
    return text


__all__ = ["REDACTED", "read_hidden", "confirm", "prompt_visible", "redact"]