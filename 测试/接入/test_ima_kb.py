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


if __name__ == "__main__":
    unittest.main()
