"""SearchSource 字段完整性测试 —— 与 接口规范 §2 字面量一致。"""

from __future__ import annotations

import unittest

from 工作台.接入.search.schemas import SearchSource


REQUIRED_FIELDS = (
    "id",
    "url",
    "title",
    "publisher",
    "published_at",
    "accessed_at",
    "excerpt",
    "locator",
    "body_path",
    "status",
    "channel",
)

STATUS_VALUES = {"ok", "paywall", "captcha", "fetch_failed", "pdf_unparsed"}
CHANNEL_VALUES = {"tavily", "brave", "bing"}


class SearchSourceSchemaTests(unittest.TestCase):
    def test_required_fields_exist(self) -> None:
        s = SearchSource(
            id="tav-1",
            url="https://example.com/a",
            title="示例",
            publisher="示例发布方",
            published_at="2026-01-01",
            accessed_at="2026-09-10",
            excerpt="正文片段",
            locator="§1",
            body_path=None,
            status="ok",
            channel="tavily",
        )
        for name in REQUIRED_FIELDS:
            self.assertTrue(hasattr(s, name), f"缺少字段 {name}")

    def test_status_literal_values(self) -> None:
        for v in STATUS_VALUES:
            s = SearchSource(
                id=f"x-{v}",
                url="https://example.com",
                title="t",
                publisher=None,
                published_at=None,
                accessed_at="2026-09-10",
                excerpt="",
                locator=None,
                body_path=None,
                status=v,  # type: ignore[arg-type]
                channel="bing",
            )
            self.assertEqual(s.status, v)

    def test_channel_literal_values(self) -> None:
        for v in CHANNEL_VALUES:
            s = SearchSource(
                id=f"x-{v}",
                url="https://example.com",
                title="t",
                publisher=None,
                published_at=None,
                accessed_at="2026-09-10",
                excerpt="",
                locator=None,
                body_path=None,
                status="ok",
                channel=v,  # type: ignore[arg-type]
            )
            self.assertEqual(s.channel, v)

    def test_frozen_dataclass_rejects_mutation(self) -> None:
        s = SearchSource(
            id="x",
            url="u",
            title="t",
            publisher=None,
            published_at=None,
            accessed_at="2026-09-10",
            excerpt="",
            locator=None,
            body_path=None,
            status="ok",
            channel="brave",
        )
        with self.assertRaises(Exception):
            s.id = "y"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
