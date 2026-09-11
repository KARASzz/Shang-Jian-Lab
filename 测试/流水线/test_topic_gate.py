"""选题输入与恢复必须先通过用户选择关口。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from 工作台.接口 import TaskState
from 工作台.流水线.cli_user import CliUser
from 工作台.流水线.topic_selection import TopicSelectionStage
from 工作台.流水线.orchestrator import Orchestrator
from 测试.流水线._stubs import StubModel, StubSearch

CANDIDATES = '\n'.join(f'{i}. 候选 {i}' for i in range(1, 6))

class TopicGateTests(unittest.TestCase):
    def test_cli_reprompts_empty_and_invalid_number(self):
        with patch('builtins.input', side_effect=['', ' ', '0', '6', '2']) as inp:
            self.assertEqual(CliUser().choose_topic(['A', 'B', 'C', 'D', 'E']), 2)
            self.assertEqual(inp.call_count, 5)

    def test_empty_selection_never_commits_and_candidates_survive(self):
        for choice in ['', '  ', None, False]:
            with self.subTest(choice=choice), tempfile.TemporaryDirectory() as td:
                stage = TopicSelectionStage(planner=StubModel(planner_text=CANDIDATES),
                    user=Mock(choose_topic=Mock(return_value=choice)), snapshot_id='s')
                with self.assertRaises(ValueError):
                    stage.run(TaskState(issue_id='x', stage='topic_selection'),
                        issue_dir=td, column='栏目', recent_issues=[])
                self.assertFalse((Path(td)/'选题/选定.json').exists())
                self.assertFalse((Path(td)/'运行记录/checkpoint.json').exists())
                self.assertTrue((Path(td)/'选题/候选.json').exists())

    def test_resume_candidates_without_requesting_model_again(self):
        with tempfile.TemporaryDirectory() as td:
            stage = TopicSelectionStage(planner=Mock(), user=Mock(), snapshot_id='s')
            topic = Path(td)/'选题'; topic.mkdir()
            (topic/'候选.json').write_text(json.dumps(['A','B','C','D','E']))
            stage.user.choose_topic.return_value = 2
            state, _ = stage.run(TaskState(issue_id='x', stage='topic_selection'),
                issue_dir=td, column='栏目', recent_issues=[])
            stage.planner.chat.assert_not_called()
            self.assertEqual(state.stage, 'evidence_collection')
            self.assertEqual(json.loads((topic/'选定.json').read_text())['topic'], 'B')

    def test_unselected_resume_never_calls_downstream_or_uses_column(self):
        for raw in [None, {'topic': ''}, {'topic': '  '}, {'topic': False}, {'topic': 123}]:
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as td:
                model = Mock()
                orch = Orchestrator(issue_id='x', issue_dir=td, snapshot_id='s',
                    planner=model, writer=model, reviewer=model, search=StubSearch(),
                    user=Mock(), column='栏目', topic_seed='不得兜底')
                orch.save_state(TaskState(issue_id='x', stage='draft_2'))
                if raw is not None:
                    p=Path(td)/'选题'; p.mkdir()
                    (p/'选定.json').write_text(json.dumps(raw))
                with self.assertRaisesRegex(ValueError, '选题'):
                    orch.run_issue()
                model.chat.assert_not_called()

    def test_eof_does_not_make_a_selection(self):
        with patch('builtins.input', side_effect=EOFError), self.assertRaises(EOFError):
            CliUser().choose_topic(['A'])
