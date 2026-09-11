"""选题贯穿、系统提示词从文件加载、检查点 stage 落盘。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from 工作台.接口 import TaskState
from 工作台.流水线.checkpoint import load_checkpoint
from 工作台.流水线.topic_selection import TopicSelectionStage
from 测试.流水线._stubs import StubModel, StubUser


class TopicSelectionPersistTests(unittest.TestCase):
    def test_writes_selected_topic_and_advances_checkpoint(self) -> None:
        planner = StubModel(planner_text="\n".join(f"{i}. 候选 {i}" for i in range(1, 6)))
        user = StubUser(choice=2)
        stage = TopicSelectionStage(planner=planner, user=user, snapshot_id="s")
        state = TaskState(issue_id="x", stage="topic_selection", snapshot_id="s")
        with tempfile.TemporaryDirectory() as td:
            new_state, _md = stage.run(
                state, issue_dir=td, column="大模型二三事", recent_issues=[]
            )
            self.assertEqual(new_state.stage, "evidence_collection")
            ck = load_checkpoint(Path(td) / "运行记录")
            self.assertIsNotNone(ck)
            self.assertEqual(ck.stage, "evidence_collection")
            chosen = json.loads((Path(td) / "选题" / "选定.json").read_text(encoding="utf-8"))
            self.assertEqual(chosen["topic"], "2. 候选 2")

    def test_planner_system_prompt_comes_from_file(self) -> None:
        stage = TopicSelectionStage(
            planner=StubModel(planner_text="x"),
            user=StubUser(choice=1),
            snapshot_id="s",
        )
        req = stage.build_request(column="大模型二三事", recent_issues=[])
        self.assertNotEqual(req.messages[0]["content"], "planner-system")
        self.assertIn("策划岗", req.messages[0]["content"])
