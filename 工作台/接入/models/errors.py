"""工作台 / 接入 / models / errors —— 按 接口规范 §5 的错误分类。

所有错误必须保留原始 `raw_error` 字符串便于诊断。
"""

from __future__ import annotations


class ModelCallError(RuntimeError):
    """所有模型调用错误的基类。"""

    def __init__(self, raw_error: str, *, status_code: int | None = None) -> None:
        super().__init__(raw_error)
        self.raw_error = raw_error
        self.status_code = status_code


class AuthError(ModelCallError):
    """HTTP 401/403：认证失败。规范 §5 要求直接停止并提示用户，禁止重试。"""


class RateLimitError(ModelCallError):
    """HTTP 429：限流。规范 §5 允许最多 2 次重试，含 Retry-After 时遵守。"""


class TimeoutError(ModelCallError):
    """超时：默认 180 秒。规范 §5 计入重试。"""


class NetworkError(ModelCallError):
    """其它网络错误。规范 §5 计入重试。"""
