# 内容流水线（工作台/流水线）

实现 PLAN §3「三模型流水线」步骤 1–8。阶段模块通过 Protocol 注入
`ModelClient` / `SearchClient` / `UserInput`；测试用 stub，续跑时由
`build_orchestrator` 组装真实接入层。

## 模块结构

| 文件 | 职责 |
|---|---|
| `state.py` | `TaskState` dataclass + 阶段推进纯函数（与接口规范 §4 字面量一致） |
| `checkpoint.py` | checkpoint.json 原子写（`.tmp` + `os.replace`，失败清理）、版本一致性校验 |
| `research.py` | 选题前研究：两轮各调用 Tavily / Brave / Bing，再由 Scrapy 抓取正文 |
| `topic_selection.py` | 选题：仅基于两轮研究资料调 planner 拿 5 候选 → 用户选/自选 |
| `evidence.py` | 两轮检索并由 Scrapy 抓正文：调 search + crawler → `资料/证据清单.json` |
| `planning.py` | 策划：调 planner 出三角度策划.md |
| `drafts.py` | 三稿：调 writer 依次生成 3 篇独立初稿 |
| `review.py` | 审稿：调 reviewer；4 类必阻断不能被 score 救活 |
| `revise.py` | 返修：qwen 返修 + GLM 复审；最多 2 轮；超限进入 await_human |
| `finalizing.py` | 待定稿：输出推荐稿 + 备选标题 + 摘要 + 资料口径 |
| `orchestrator.py` | 编排、checkpoint、模块级 `resume` / `rerun` |
| `prompts.py` | 从 `提示词/` 加载岗位系统提示词 |
| `tests/` | 见 `测试/流水线/` |

## 阶段顺序

`topic_research → topic_selection → evidence_collection → planning → draft_1 → draft_2 → draft_3 → review_1 → revise_1 → review_2 → revise_2 → awaiting_human | finalizing`，其中 `topic_research` 和 `evidence_collection` 都必须完成搜索后的网页抓取；`finalizing` 仅在审稿通过且 ≤ 2 轮返修时由流水线写入；`archived` 由用户在 6 号菜单触发，本流水线不实现。

## 依赖

- 标准库：`dataclasses` / `datetime` / `hashlib` / `json` / `os` / `pathlib` / `typing`。
- 跨模块：阶段代码只引用 `工作台.接口` 的数据类与 Protocol。真实客户端由 `orchestrator.build_orchestrator` 在续跑时组装。
- 运行依赖：Scrapy（选题研究和证据阶段必须安装；缺失时明确停步，不回退成假成功）。
- 可选：`pytest`（仅在运行 `测试/流水线/` 时需要，由主线程按需安装）。

## 不变量（接口规范对齐）

- 阶段字面量与接口规范 §4 完全一致；新加状态必须先打回主线程补规范。
- `pass_` 与 4 类 `block` 的关系：`block` 出现即 `pass_=False`，**`score` 不得救活**。
- `revision_rounds_max` 默认 2；超限直接 `awaiting_human`，**不再调用模型**。
- checkpoint 写失败时清理 `.tmp`，不得留下半文件。
- 上游重跑 → `rerun_invalidated` 含当前及之后所有阶段；阶段生成新产物后立即移出清单；恢复时若产物哈希与 `versions` 不一致 → `VersionMixingError`。
