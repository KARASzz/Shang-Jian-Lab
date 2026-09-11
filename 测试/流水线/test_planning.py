"""策划角度标题解析。"""

from __future__ import annotations

import unittest

from 工作台.流水线.planning import extract_angles


class PlanningAngleTests(unittest.TestCase):
    def test_accepts_common_heading_levels_and_ignores_other_sections(self) -> None:
        text = """# 三角度策划

# 角度 A：污染
## 角度 B：覆盖度
### 角度 C：治理
## 三个角度的互斥性自检
"""
        self.assertEqual(
            extract_angles(text),
            ["角度 A：污染", "角度 B：覆盖度", "角度 C：治理"],
        )

    def test_accepts_plain_angle_lines_and_numbered_headings(self) -> None:
        text = """角度一：数据污染
角度二：任务覆盖
角度三：评测治理
"""
        self.assertEqual(
            extract_angles(text),
            ["角度一：数据污染", "角度二：任务覆盖", "角度三：评测治理"],
        )

    def test_rejects_fewer_than_three_angles(self) -> None:
        with self.assertRaisesRegex(ValueError, "解析到 2 个"):
            extract_angles("## 角度 A：污染\n## 角度 B：覆盖度\n")


if __name__ == "__main__":
    unittest.main()
