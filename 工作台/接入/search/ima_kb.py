"""IMA 知识库参考资料接入。

该模块只把 IMA 知识库作为一个额外的参考来源，不替代 Tavily、Brave、Bing
的公开检索。凭据只通过请求头发送到 IMA 官方 API；知识库原文若可访问，写入
当期资料目录供后续证据阶段使用。
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from 工作台.接入.config import IMAKnowledgeBaseConfig, resolve_api_key
from 工作台.接入.search.schemas import SearchSource


def _secure_opener() -> Any:
    try:
        import certifi

        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))


class IMAKnowledgeBaseError(RuntimeError):
    """IMA 知识库请求失败。"""


class IMAKnowledgeBaseSearch:
    """按配置的知识库名称检索 IMA，并实现统一 SearchClient 形状。"""

    _WIKI_PATH = "/openapi/wiki/v1"
    _NOTE_PATH = "/openapi/note/v1"
    _SKILL_VERSION = "1.1.9"

    def __init__(
        self,
        config: IMAKnowledgeBaseConfig,
        *,
        http_opener: Callable[..., Any] | None = None,
    ) -> None:
        self._config = config
        self._http_opener = http_opener or _secure_opener
        self._knowledge_base_id: str | None = None
        self._kb_ids: dict[str, str] = {}                 # 库名 → 库ID 缓存
        self._kb_targets: list[tuple[str, str]] | None = None
        self._output_dir: Path | None = None
        self._media_by_source_id: dict[str, str] = {}

    @property
    def config(self) -> IMAKnowledgeBaseConfig:
        return self._config

    def set_output_dir(self, output_dir: str) -> None:
        """设置当期原文落盘目录；不设置时仍可返回搜索摘要。"""

        self._output_dir = Path(output_dir)

    def _credentials(self) -> tuple[str, str]:
        client_id = resolve_api_key(self._config.client_id_env)
        api_key = resolve_api_key(self._config.api_key_env)
        if not client_id or not api_key:
            raise IMAKnowledgeBaseError("未配置 IMA 知识库凭据")
        return client_id, api_key

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        client_id, api_key = self._credentials()
        request = urllib.request.Request(
            self._config.base_url.rstrip("/") + path,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "ima-openapi-clientid": client_id,
                "ima-openapi-apikey": api_key,
                "ima-openapi-ctx": f"skill_version={self._SKILL_VERSION}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            response = self._http_opener().open(
                request, timeout=self._config.timeout_seconds
            )
            try:
                raw = response.read()
            finally:
                close = getattr(response, "close", None)
                if close:
                    close()
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise IMAKnowledgeBaseError("IMA 凭据验证失败") from exc
            if exc.code == 429:
                raise IMAKnowledgeBaseError("IMA 请求频率受限，请稍后重试") from exc
            raise IMAKnowledgeBaseError("IMA 知识库暂时无法连接") from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise IMAKnowledgeBaseError("IMA 知识库暂时无法连接") from exc

        try:
            payload = json.loads(raw.decode("utf-8", errors="replace"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise IMAKnowledgeBaseError("IMA 返回内容无法解析") from exc
        if not isinstance(payload, dict):
            raise IMAKnowledgeBaseError("IMA 返回格式不正确")
        code = payload.get("code", 0)
        if code != 0:
            message = str(payload.get("msg") or "IMA 请求失败")
            raise IMAKnowledgeBaseError(message)
        data = payload.get("data", {})
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _items(data: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    def _resolve_knowledge_base_id(self, name: str | None = None) -> str:
        target = (name or self._config.knowledge_base_name).strip()
        if target in self._kb_ids:
            return self._kb_ids[target]
        # 主库允许用环境变量直接指定 ID；其余检索库按名称解析。
        if target == self._config.knowledge_base_name:
            configured_id = resolve_api_key(self._config.knowledge_base_id_env)
            if configured_id:
                self._knowledge_base_id = configured_id
                self._kb_ids[target] = configured_id
                return configured_id

        cursor = ""
        while True:
            data = self._post(
                f"{self._WIKI_PATH}/search_knowledge_base",
                {
                    "query": target,
                    "cursor": cursor,
                    "limit": 20,
                },
            )
            for item in self._items(data, "info_list", "knowledge_base_list"):
                found_name = str(item.get("name") or item.get("kb_name") or "").strip()
                if found_name == target:
                    found = str(item.get("id") or item.get("kb_id") or "").strip()
                    if found:
                        self._kb_ids[target] = found
                        return found
            if data.get("is_end", True):
                break
            next_cursor = str(data.get("next_cursor") or "")
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
        raise IMAKnowledgeBaseError(f"找不到 IMA 知识库：{target}")

    def _knowledge_base_targets(self) -> list[tuple[str, str]]:
        """解析全部配置的检索目标库，返回 [(库名, 库ID)]。

        单个库缺失只告警并跳过（简报类库可能改名/删除），全部缺失才报错。
        """
        if self._kb_targets is not None:
            return self._kb_targets
        names = self._config.knowledge_base_names or (self._config.knowledge_base_name,)
        resolved: list[tuple[str, str]] = []
        for name in names:
            try:
                resolved.append((name, self._resolve_knowledge_base_id(name)))
            except IMAKnowledgeBaseError as exc:
                print(f"提示：IMA 检索库「{name}」不可用（{exc}）", flush=True)
        if not resolved:
            raise IMAKnowledgeBaseError("没有任何可用的 IMA 检索库：" + "、".join(names))
        self._kb_targets = resolved
        return resolved

    @staticmethod
    def _source_id(knowledge_base_id: str, media_id: str) -> str:
        digest = hashlib.sha256(
            f"{knowledge_base_id}:{media_id}".encode("utf-8")
        ).hexdigest()[:16]
        return f"ima-{digest}"

    def search(
        self,
        query: str,
        *,
        round_idx: int = 0,
        max_results: int | None = None,
    ) -> list[SearchSource]:
        del round_idx  # IMA 媒体 ID 本身稳定，跨轮重复结果由 CompositeSearch 去重。
        query = query.strip()
        if not query:
            return []
        limit = max(1, min(max_results or self._config.max_results, 50))
        targets = self._knowledge_base_targets()
        # 每库配额均摊（向上取整），再轮转合并，保证各检索库均匀进入候选。
        per_kb_limit = max(1, -(-limit // len(targets)))
        out: list[SearchSource] = []
        seen_ids: set[str] = set()
        # IMA 搜索按整词/短语匹配，流水线长查询直接搜必零命中；
        # 这里抽取若干短检索键逐个尝试，凑够即停。
        for key in self._search_keys(query):
            # 长复合词（如栏目名"大模型二三事"）几乎不会整词命中，
            # 零命中时用 3 字前缀重试一次（"大模型"）。
            variants = [key]
            cjk = sum("\u4e00" <= ch <= "\u9fff" for ch in key)
            if len(key) >= 5 and cjk * 2 >= len(key):
                variants.append(key[:3])
            for variant in variants:
                key_pool: list[SearchSource] = []
                pools = [
                    self._safe_single_kb(variant, kb_id, kb_name, per_kb_limit)
                    for kb_name, kb_id in targets
                ]
                index = 0
                while True:
                    progressed = False
                    for pool in pools:
                        if index >= len(pool):
                            continue
                        progressed = True
                        source = pool[index]
                        if source.id not in seen_ids:
                            seen_ids.add(source.id)
                            key_pool.append(source)
                    if not progressed:
                        break
                    index += 1
                # 键与键之间也轮转合并，兼顾不同关键词的多样性。
                out = self._interleave(out, key_pool)[:limit]
                if key_pool or len(out) >= limit:
                    break
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _interleave(a: list[SearchSource], b: list[SearchSource]) -> list[SearchSource]:
        merged: list[SearchSource] = []
        for i in range(max(len(a), len(b))):
            if i < len(a):
                merged.append(a[i])
            if i < len(b):
                merged.append(b[i])
        return merged

    @staticmethod
    def _search_keys(query: str) -> list[str]:
        """从流水线长查询里抽取 IMA 可命中的短检索键。

        IMA 搜索按整词/短语匹配：``大模型`` 能命中，``大模型二三事`` 或
        空格组合长句一律零命中。这里按空白和标点切词，优先 2–4 字的实义词
        （真正的"词"，命中率最高），5 字以上的长短语只留一个作补充。
        """
        pattern = (
            "[\\s，。：；、（）()【】\\[\\]「」『』·～~\\-—_/\\\\:;,."
            "\"'？?！!<>《》=+*&^%$#@|]+"
        )
        tokens = [
            t.strip()
            for t in re.split(pattern, query)
            if t.strip()
        ]
        skip = {"tavily", "brave", "bing", "ima"}
        short_band: list[str] = []
        long_band: list[str] = []
        seen: set[str] = set()
        for token in tokens:
            if token.lower() in skip or token.isdigit() or len(token) < 2:
                continue
            trimmed = token[:10]
            if trimmed in seen:
                continue
            seen.add(trimmed)
            (short_band if len(trimmed) <= 4 else long_band).append(trimmed)
        short_band.sort(key=len, reverse=True)
        long_band.sort(key=len, reverse=True)
        # 长短语（往往是最具体的主题词）排第一，短词补足。
        keys: list[str] = []
        if long_band:
            keys.append(long_band[0])
        keys.extend(short_band[: 3 - len(keys)])
        if not keys and query.strip():
            keys = [query.strip()[:10]]
        return keys

    def _safe_single_kb(
        self,
        query: str,
        knowledge_base_id: str,
        kb_name: str,
        limit: int,
    ) -> list[SearchSource]:
        """单库检索失败（限流/网络）只告警跳过，不拖垮其余检索库。"""
        try:
            return self._search_single_kb(query, knowledge_base_id, kb_name, limit)
        except IMAKnowledgeBaseError as exc:
            print(f"提示：IMA 库「{kb_name}」检索失败，已跳过（{exc}）", flush=True)
            return []

    def _search_single_kb(
        self,
        query: str,
        knowledge_base_id: str,
        kb_name: str,
        limit: int,
    ) -> list[SearchSource]:
        cursor = ""
        out: list[SearchSource] = []
        while len(out) < limit:
            data = self._post(
                f"{self._WIKI_PATH}/search_knowledge",
                {
                    "query": query,
                    "cursor": cursor,
                    "knowledge_base_id": knowledge_base_id,
                },
            )
            items = self._items(data, "info_list", "knowledge_list")
            for item in items:
                media_id = str(item.get("media_id") or "").strip()
                title = str(item.get("title") or "").strip()
                if not media_id or not title:
                    continue
                source_id = self._source_id(knowledge_base_id, media_id)
                if source_id in self._media_by_source_id:
                    continue
                self._media_by_source_id[source_id] = media_id
                excerpt = str(
                    item.get("highlight_content")
                    or item.get("highlightContent")
                    or item.get("content")
                    or ""
                ).strip()
                out.append(
                    SearchSource(
                        id=source_id,
                        url="",
                        title=title,
                        publisher=f"IMA 知识库：{kb_name}",
                        published_at=None,
                        accessed_at=datetime.now(timezone.utc).isoformat(
                            timespec="seconds"
                        ),
                        excerpt=excerpt,
                        locator="IMA 知识库",
                        body_path=None,
                        status="ok",
                        channel="ima",
                    )
                )
                if len(out) >= limit:
                    break
            if len(out) >= limit or data.get("is_end", True):
                break
            next_cursor = str(data.get("next_cursor") or "")
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
        return out

    def fetch(self, source: SearchSource) -> SearchSource:
        if source.channel != "ima":
            return source
        media_id = self._media_by_source_id.get(source.id)
        if not media_id:
            return replace(source, status="fetch_failed")
        try:
            data = self._post(
                f"{self._WIKI_PATH}/get_media_info", {"media_id": media_id}
            )
            media_type = int(data.get("media_type") or 0)
            if media_type == 11:
                notebook = data.get("notebook_ext_info") or {}
                note_id = str(notebook.get("notebook_id") or "").strip()
                if note_id:
                    note_data = self._post(
                        f"{self._NOTE_PATH}/get_doc_content",
                        {"note_id": note_id, "target_content_format": 0},
                    )
                    content = self._extract_content(note_data)
                    if content:
                        return self._with_body(source, content)
            url_info = data.get("url_info") or {}
            url = str(url_info.get("url") or "").strip()
            if url:
                headers = url_info.get("headers")
                content = self._download_text(url, headers if isinstance(headers, dict) else {})
                if content:
                    return self._with_body(source, content)
        except Exception:  # noqa: BLE001 - 单条资料失败需显式记录而非中断整轮
            return replace(source, status="fetch_failed")
        return replace(source, status="fetch_failed")

    @staticmethod
    def _extract_content(data: dict[str, Any]) -> str:
        for key in ("content", "text", "doc_content", "markdown"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _download_text(self, url: str, headers: dict[str, Any]) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return ""
        request_headers = {
            str(key): str(value)
            for key, value in headers.items()
            if str(key).strip() and str(value).strip()
        }
        request = urllib.request.Request(url, method="GET", headers=request_headers)
        try:
            response = self._http_opener().open(
                request, timeout=self._config.timeout_seconds
            )
            try:
                content_type = str(
                    getattr(response, "headers", {}).get("Content-Type", "")
                ).lower()
                raw = response.read()
            finally:
                close = getattr(response, "close", None)
                if close:
                    close()
        except (urllib.error.HTTPError, urllib.error.URLError, OSError, TimeoutError):
            return ""
        if "pdf" in content_type:
            return ""
        charset = "utf-8"
        match = re.search(r"charset=([\w-]+)", content_type)
        if match:
            charset = match.group(1)
        text = raw.decode(charset, errors="replace")
        if "html" in content_type or "<html" in text.lower():
            text = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", text)
            text = re.sub(r"(?s)<[^>]+>", " ", text)
            text = html.unescape(text)
        return " ".join(text.split())[:12000]

    def _with_body(self, source: SearchSource, content: str) -> SearchSource:
        if self._output_dir is None:
            return replace(source, excerpt=content[:1800])
        body_dir = self._output_dir / "IMA正文"
        body_dir.mkdir(parents=True, exist_ok=True)
        body_path = body_dir / f"{hashlib.sha256(source.id.encode('utf-8')).hexdigest()[:16]}.txt"
        body_path.write_text(content, encoding="utf-8")
        return replace(source, excerpt=content[:1800], body_path=str(body_path), status="ok")


__all__ = ["IMAKnowledgeBaseError", "IMAKnowledgeBaseSearch"]
