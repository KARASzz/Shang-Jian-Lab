# 内容流水线（工作台/流水线）

实现 PLAN §3「三模型流水线」步骤 1–8 的骨架 + 提示词三件套。**只写代码占位 + 提示词骨架**，不发起任何真实模型调用、不读真实证据。所有外部依赖（`ModelClient` / `SearchClient` / `UserInput`）以 Protocol 形式注入；测试用 stub 替换。

## 模块结构

| 文件 | 职责 |
|---|---|
| `state.py` | `TaskState` dataclass + 阶段推进纯函数（与接口规范 §4 字面量一致） |
| `checkpoint.py` | checkpoint.json 原子写（`.tmp` + `os.replace`，失败清理）、版本一致性校验 |
| `topic_selection.py` | 选题：调 planner 拿 5 候选 → 用户选/自选 |
| `evidence.py` | 检索：调 search 拿证据 → `资料/证据清单.json` |
| `planning.py` | 策划：调 planner 出三角度策划.md |
| `drafts.py` | 三稿：调 writer 依次生成 3 篇独立初稿 |
| `review.py` | 审稿：调 reviewer；4 类必阻断不能被 score 救活 |
| `revise.py` | 返修：qwen 返修 + GLM 复审；最多 2 轮；超限进入 await_human |
| `finalizing.py` | 待定稿：输出推荐稿 + 备选标题 + 摘要 + 资料口径 |
| `orchestrator.py` | 一句话编排：阶段顺序 + checkpoint 调度 |
| `tests/` | 见 `测试/流水线/`（由主线程/C 同步放置） |

## 阶段顺序

`topic_selection → evidence_collection → planning → draft_1 → draft_2 → draft_3 → review_1 → revise_1 → review_2 → revise_2 → awaiting_human | finalizing`，其中 `finalizing` 仅在审稿通过且 ≤ 2 轮返修时由流水线写入；`archived` 由用户在 6 号菜单触发，本流水线不实现。

## 依赖

- 标准库：`dataclasses` / `datetime` / `hashlib` / `json` / `os` / `pathlib` / `typing`。
- 跨模块：仅引用 `工作台.接入.types` 的数据类（`ModelRequest / ModelResponse / SearchSource`）与 `配置/默认.toml` 字段名。**不** import `工作台.接入.client` / `工作台.接入.search` 等具体实现。
- 可选：`pytest`（仅在运行 `测试/流水线/` 时需要，由主线程按需安装）。

## 不变量（接口规范对齐）

- 阶段字面量与接口规范 §4 完全一致；新加状态必须先打回主线程补规范。
- `pass_` 与 4 类 `block` 的关系：`block` 出现即 `pass_=False`，**`score` 不得救活**。
- `revision_rounds_max` 默认 2；超限直接 `awaiting_human`，**不再调用模型**。
- checkpoint 写失败时清理 `.tmp`，不得留下半文件。
- 上游重跑 → `rerun_invalidated` 含当前及之后所有阶段；恢复时若产物哈希与 `versions` 不一致 → `VersionMixingError`。
