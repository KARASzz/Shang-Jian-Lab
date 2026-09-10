"""内容流水线（三模型流水线）。

仅依赖共享数据类型（``工作台.接入.types``）和 ``配置`` 读取，**不引用**
``工作台.接入`` 的具体实现；外部依赖通过 Protocol 注入，便于测试时替换 stub。
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
