"""工作台 / 接入 / models / client —— OpenAI 兼容 Chat Completions 占位实现。

设计原则（接口规范 §5）：

- base url 来自 ``base_url_env``；key 来自 ``api_key_env``。
- 缺失 key 时 **必须** 抛 AuthError，**禁止** 自动降级为占位响应。
- HTTP 401/403 → AuthError（直接停止，不重试）。
- HTTP 429 → RateLimitError（最多重试 max_retries 次，含 Retry-After 时遵守）。
- 超时 180s → TimeoutError（计入重试）。
- 其它网络错误 → NetworkError（计入重试）。
- 不打印、不返回真实 key。
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from 工作台.接入.config import (
    ModelConfig,
    resolve_api_key,
    resolve_base_url,
)
from 工作台.接入.models.errors import (
    AuthError,
    NetworkError,
    RateLimitError,
    RoleMismatchError,
    TimeoutError,
)
from 工作台.接入.models.schemas import (
    ModelRequest,
    ModelResponse,
    TokenUsage,
)


class ModelClient:
    """OpenAI 兼容 Chat Completions 客户端。"""

    def __init__(
        self,
        config: ModelConfig,
        *,
        http_opener: Callable[..., Any] | None = None,
        sleeper: Callable[[float], None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._config = config
        self._http_opener = http_opener or urllib.request.build_opener
        self._sleeper = sleeper or time.sleep
        self._clock = clock or time.monotonic

    @property
    def config(self) -> ModelConfig:
        return self._config

    # ------------------------------------------------------------------ public

    def chat(self, request: ModelRequest) -> ModelResponse:
        """接口规范 §1：流水线通过 ``chat`` 调用；与 ``complete`` 同一实现。"""

        return self.complete(request)

    def complete(self, request: ModelRequest) -> ModelResponse:
        """发送一次 Chat Completions 请求并归一化错误。"""

        if request.role != self._config.role:
            raise RoleMismatchError(
                f"role 与 config 不一致：request.role={request.role!r}, "
                f"config.role={self._config.role!r}",
                status_code=None,
            )
        if not request.request_model:
            raise RoleMismatchError("ModelRequest.request_model 为空，岗位未冻结")
        if request.request_model != self._config.request_model:
            raise RoleMismatchError(
                f"request_model 与本期冻结不一致：request={request.request_model!r}, "
                f"config={self._config.request_model!r}",
                status_code=None,
            )

        api_key = resolve_api_key(self._config.api_key_env)
        if api_key is None:
            # 关键约束：key 缺失必须抛 AuthError，禁止静默回退
            raise AuthError(
                f"未配置 API key（环境变量 {self._config.api_key_env} 缺失或为空）",
                status_code=None,
            )
        base_url = resolve_base_url(self._config.base_url_env)
        if base_url is None:
            raise AuthError(
                f"未配置 base URL（环境变量 {self._config.base_url_env} 缺失或为空）",
                status_code=None,
            )

        endpoint = base_url.rstrip("/") + "/chat/completions"
        # 调试打印：不包含任何 key
        print(
            f"[调试] role={request.role} "
            f"将请求 {endpoint} request_model={request.request_model}"
        )

        payload = self._build_payload(request)
        # max_retries=2 → 共 3 次（1 初始 + 2 重试）；max_retries=0 → 只打 1 次。
        total_tries = max(1, int(self._config.max_retries) + 1)
        last_exc: Exception | None = None
        for attempt in range(total_tries):
            try:
                return self._do_call(endpoint, api_key, payload)
            except AuthError:
                # 认证失败直接停止，不计入重试
                raise
            except RateLimitError as e:
                last_exc = e
                if attempt >= total_tries - 1:
                    raise
                self._respect_retry_after(e)
            except (TimeoutError, NetworkError) as e:
                last_exc = e
                if attempt >= total_tries - 1:
                    raise
                # 简单退避：2^attempt 秒
                self._sleeper(min(2 ** attempt, 8))
        # 兜底：走到这里说明所有重试用尽
        assert last_exc is not None
        raise last_exc

    # ------------------------------------------------------------------ helpers

    def _build_payload(self, request: ModelRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.request_model or self._config.request_model,
            "messages": list(request.messages),
        }
        if request.temperature is not None:
            payload["temperature"] = float(request.temperature)
        else:
            payload["temperature"] = float(self._config.temperature)
        if request.max_tokens is not None:
            payload["max_tokens"] = int(request.max_tokens)
        return payload

    def _do_call(
        self, endpoint: str, api_key: str, payload: dict[str, Any]
    ) -> ModelResponse:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                # 由 request.request_model 固定岗位，禁止运行时替换
                "X-Workbench-Role": self._config.role,
            },
        )

        opener = self._http_opener()
        timeout = float(self._config.timeout_seconds)
        started = self._clock()
        try:
            resp = opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            return self._on_http_error(e, payload)
        except urllib.error.URLError as e:
            reason = str(getattr(e, "reason", e))
            # URLError 的 reason 常为超时
            if self._is_timeout_reason(reason):
                raise TimeoutError(
                    f"模型调用超时（>{timeout:.0f}s）：{reason}",
                    status_code=None,
                ) from e
            raise NetworkError(f"模型调用网络错误：{reason}", status_code=None) from e
        except TimeoutError as e:  # 兼容传入的 sleeper/clock 触发的超时
            raise TimeoutError(
                f"模型调用超时（>{timeout:.0f}s）：{e}",
                status_code=None,
            ) from e
        except OSError as e:
            raise NetworkError(
                f"模型调用网络错误：{e!s}", status_code=None
            ) from e
        _ = self._clock() - started

        raw = resp.read()
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as e:
            raise NetworkError(
                f"模型响应非 JSON：{e!s}", status_code=getattr(resp, "status", None)
            ) from e
        return self._on_success(body)

    def _on_http_error(
        self, err: urllib.error.HTTPError, payload: dict[str, Any]
    ) -> ModelResponse:
        status = int(err.code)
        body = ""
        try:
            body = err.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            body = ""

        if status in (401, 403):
            raise AuthError(
                f"HTTP {status}：认证失败（{body[:200]!s}）", status_code=status
            )
        if status == 429:
            retry_after = err.headers.get("Retry-After") if err.headers else None
            raise RateLimitError(
                f"HTTP 429：限流（{body[:200]!s}）",
                status_code=status,
            ).with_retry_after(retry_after)
        raise NetworkError(
            f"HTTP {status}：模型调用失败（{body[:200]!s}）", status_code=status
        )

    def _on_success(self, body: dict[str, Any]) -> ModelResponse:
        text = ""
        try:
            choices = body.get("choices") or []
            if choices:
                text = str(choices[0].get("message", {}).get("content", ""))
        except Exception:  # noqa: BLE001
            text = ""
        served = str(body.get("model", "")) or self._config.request_model
        usage_raw = body.get("usage") or {}
        try:
            usage = TokenUsage(
                prompt_tokens=int(usage_raw.get("prompt_tokens", 0)),
                completion_tokens=int(usage_raw.get("completion_tokens", 0)),
                total_tokens=int(usage_raw.get("total_tokens", 0)),
            ).as_dict()
        except (TypeError, ValueError):
            usage = TokenUsage().as_dict()
        return ModelResponse(
            text=text,
            request_model=self._config.request_model,
            served_model=served,
            usage=usage,
            raw_error=None,
        )

    def _respect_retry_after(self, err: RateLimitError) -> None:
        seconds = getattr(err, "retry_after_seconds", None)
        if seconds is None:
            seconds = 1.0
        self._sleeper(float(seconds))

    @staticmethod
    def _is_timeout_reason(reason: str) -> bool:
        if not reason:
            return False
        reason_l = reason.lower()
        return "timed out" in reason_l or "timeout" in reason_l


# 为 RateLimitError 增加 retry_after 字段，避免破坏既有签名
def _rl_with_retry_after(self: RateLimitError, retry_after: str | None) -> RateLimitError:
    if retry_after is None:
        self.retry_after_seconds = None  # type: ignore[attr-defined]
        return self
    try:
        seconds = float(retry_after)
    except ValueError:
        seconds = None
    self.retry_after_seconds = seconds  # type: ignore[attr-defined]
    return self


RateLimitError.with_retry_after = _rl_with_retry_after  # type: ignore[attr-defined]
