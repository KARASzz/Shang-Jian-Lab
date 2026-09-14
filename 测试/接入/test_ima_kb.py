"""IMA 知识库参考来源：解析知识库、搜索条目并落盘可访问正文。"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from 工作台.接入.config import IMAKnowledgeBaseConfig
from 工作台.接入.search.ima_kb import IMAKnowledgeBaseSearch


class _Response:
    def __init__(self, payload: dict, *, headers: dict[str, str] | None = None) -> None:
        self._body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.headers = headers or {}

    def read(self) -> bytes:
        return self._body

    def close(self) -> None:
        return None


class _Opener:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.responses = [
            _Response(
                {
                    "code": 0,
                    "data": {
                        "info_list": [
                            {
                                "kb_id": "kb-1",
                                "kb_name": "熵减进化室自媒体发稿参考库",
                            }
                        ],
                        "is_end": True,
                    },
                }
            ),
            _Response(
                {
                    "code": 0,
                    "data": {
                        "info_list": [
                            {
                                "media_id": "media-1",
                                "title": "判断力与生产力",
                                "highlight_content": "检索命中的参考片段",
                            }
                        ],
                        "is_end": True,
                    },
                }
            ),
            _Response(
                {
                    "code": 0,
                    "data": {
                        "media_type": 11,
                        "notebook_ext_info": {"notebook_id": "note-1"},
                    },
                }
            ),
            _Response(
                {
                    "code": 0,
                    "data": {"content": "IMA 笔记的完整参考正文。"},
                }
            ),
        ]

    def __call__(self):
        return self

    def open(self, request, *, timeout: int):
        payload = json.loads(request.data.decode("utf-8"))
        self.calls.append((request.full_url, payload))
        return self.responses.pop(0)


class IMAKnowledgeBaseSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_client = os.environ.get("TEST_IMA_CLIENT")
        self._old_key = os.environ.get("TEST_IMA_KEY")
        os.environ["TEST_IMA_CLIENT"] = "client-for-test"
        os.environ["TEST_IMA_KEY"] = "key-for-test"

    def tearDown(self) -> None:
        for key, old in (("TEST_IMA_CLIENT", self._old_client), ("TEST_IMA_KEY", self._old_key)):
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old

    def test_search_resolves_named_kb_and_fetches_note_body(self) -> None:
        config = IMAKnowledgeBaseConfig(
            base_url="https://ima.qq.com",
            client_id_env="TEST_IMA_CLIENT",
            api_key_env="TEST_IMA_KEY",
            knowledge_base_name="熵减进化室自媒体发稿参考库",
            knowledge_base_id_env="TEST_IMA_KB_ID",
            max_results=10,
            timeout_seconds=20,
        )
        opener = _Opener()
        client = IMAKnowledgeBaseSearch(config, http_opener=opener)

        with tempfile.TemporaryDirectory() as tmp:
            client.set_output_dir(tmp)
            sources = client.search("判断力", round_idx=0)
            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0].channel, "ima")
            self.assertEqual(sources[0].url, "")
            self.assertIn("IMA 知识库", sources[0].publisher or "")

            fetched = client.fetch(sources[0])
            self.assertEqual(fetched.status, "ok")
            self.assertTrue(fetched.body_path)
            self.assertEqual(Path(fetched.body_path).read_text(encoding="utf-8"), "IMA 笔记的完整参考正文。")

        self.assertEqual(len(opener.calls), 4)
        self.assertTrue(opener.calls[0][0].endswith("search_knowledge_base"))
        self.assertTrue(opener.calls[1][0].endswith("search_knowledge"))
        self.assertEqual(opener.calls[1][1]["knowledge_base_id"], "kb-1")
        self.assertEqual(opener.calls[0][1]["query"], "熵减进化室自媒体发稿参考库")


class MultiKBSearchTests(unittest.TestCase):
    """多检索库轮转合并：各库来源均匀进入候选，publisher 标明来源库。"""

    def setUp(self) -> None:
        self._old = {k: os.environ.get(k) for k in ("TEST_IMA_CLIENT", "TEST_IMA_KEY")}
        os.environ["TEST_IMA_CLIENT"] = "client-for-test"
        os.environ["TEST_IMA_KEY"] = "key-for-test"

    def tearDown(self) -> None:
        for key, old in self._old.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old

    def test_search_merges_multiple_knowledge_bases(self) -> None:
        config = IMAKnowledgeBaseConfig(
            base_url="https://ima.qq.com",
            client_id_env="TEST_IMA_CLIENT",
            api_key_env="TEST_IMA_KEY",
            knowledge_base_name="库A",
            knowledge_base_id_env="TEST_IMA_KB_ID",
            max_results=4,
            timeout_seconds=20,
            knowledge_base_names=("库A", "库B"),
        )

        class _MultiOpener:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict]] = []
                self.responses = [
                    _Response({"code": 0, "data": {"info_list": [
                        {"kb_id": "kb-a", "kb_name": "库A"}], "is_end": True}}),
                    _Response({"code": 0, "data": {"info_list": [
                        {"kb_id": "kb-b", "kb_name": "库B"}], "is_end": True}}),
                    _Response({"code": 0, "data": {"info_list": [
                        {"media_id": "m-a1", "title": "A库文章1"},
                        {"media_id": "m-a2", "title": "A库文章2"},
                    ], "is_end": True}}),
                    _Response({"code": 0, "data": {"info_list": [
                        {"media_id": "m-b1", "title": "B库文章1"},
                    ], "is_end": True}}),
                ]

            def __call__(self):
                return self

            def open(self, request, *, timeout: int):
                payload = json.loads(request.data.decode("utf-8"))
                self.calls.append((request.full_url, payload))
                return self.responses.pop(0)

        opener = _MultiOpener()
        client = IMAKnowledgeBaseSearch(config, http_opener=opener)
        sources = client.search("关键词", round_idx=0, max_results=3)
        self.assertEqual(len(sources), 3)
        publishers = [s.publisher or "" for s in sources]
        self.assertIn("库A", publishers[0])
        self.assertIn("库B", publishers[1])
        self.assertIn("库A", publishers[2])
        # 每个库单独调用一次 search_knowledge
        kb_calls = [c for c in opener.calls if c[0].endswith("search_knowledge")]
        self.assertEqual(len(kb_calls), 2)
        self.assertEqual(kb_calls[0][1]["knowledge_base_id"], "kb-a")
        self.assertEqual(kb_calls[1][1]["knowledge_base_id"], "kb-b")

    def test_missing_kb_warns_but_others_still_work(self) -> None:
        import io
        import contextlib

        config = IMAKnowledgeBaseConfig(
            base_url="https://ima.qq.com",
            client_id_env="TEST_IMA_CLIENT",
            api_key_env="TEST_IMA_KEY",
            knowledge_base_name="库A",
            knowledge_base_id_env="TEST_IMA_KB_ID",
            max_results=2,
            timeout_seconds=20,
            knowledge_base_names=("库A", "不存在的库"),
        )

        class _MissingOpener:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict]] = []
                self.responses = [
                    _Response({"code": 0, "data": {"info_list": [
                        {"kb_id": "kb-a", "kb_name": "库A"}], "is_end": True}}),
                    _Response({"code": 0, "data": {"info_list": [], "is_end": True}}),
                    _Response({"code": 0, "data": {"info_list": [
                        {"media_id": "m-a1", "title": "A库文章1"},
                    ], "is_end": True}}),
                ]

            def __call__(self):
                return self

            def open(self, request, *, timeout: int):
                payload = json.loads(request.data.decode("utf-8"))
                self.calls.append((request.full_url, payload))
                return self.responses.pop(0)

        opener = _MissingOpener()
        client = IMAKnowledgeBaseSearch(config, http_opener=opener)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            sources = client.search("关键词", round_idx=0)
        self.assertEqual(len(sources), 1)
        self.assertIn("IMA 检索库「不存在的库」不可用", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
