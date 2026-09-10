"""内容流水线（三模型流水线）。

阶段模块只依赖 ``工作台.接口`` 的 Protocol；``orchestrator.build_orchestrator``
在续跑时才组装 ``工作台.接入`` 的真实客户端。测试用 stub 替换。
"""

from .state import (
    TaskState,
    STAGE_ORDER,
    RERUN_DOWNSTREAM,
    advance,
    is_terminal,
    rerun,
    resume_after_rerun,
)
from .checkpoint import (
    CheckpointError,
    atomic_write_checkpoint,
    load_checkpoint,
    VersionMixingError,
)
from .topic_selection import TopicSelectionStage
from .evidence import EvidenceCollectionStage
from .planning import PlanningStage
from .drafts import DraftsStage
from .review import ReviewStage, BLOCK_CATEGORIES
from .revise import ReviseStage, MaxRevisionsExceeded
from .finalizing import FinalizingStage
from .orchestrator import Orchestrator

__all__ = [
    "TaskState",
    "STAGE_ORDER",
    "RERUN_DOWNSTREAM",
    "advance",
    "is_terminal",
    "rerun",
    "resume_after_rerun",
    "CheckpointError",
    "atomic_write_checkpoint",
    "load_checkpoint",
    "VersionMixingError",
    "TopicSelectionStage",
    "EvidenceCollectionStage",
    "PlanningStage",
    "DraftsStage",
    "ReviewStage",
    "BLOCK_CATEGORIES",
    "ReviseStage",
    "MaxRevisionsExceeded",
    "FinalizingStage",
    "Orchestrator",
]
