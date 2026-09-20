# 内容流水线（工作台/流水线）

研究阶段按问题类型和结果缺口调用已配置的检索 MCP；Omnisearch 暂时冻结（另一个开发环境），Node REPL 不调用，Scrapy 仅保留为独立工具。

实现 PLAN §3「三模型流水线」步骤 1–8。阶段模块通过 Protocol 注入
`ModelClient` / `SearchClient` / `UserInput`；测试用 stub，续跑时由
`build_orchestrator` 组装真实接入层。

## 模块结构

| 文件 | 职责 |
|---|---|
| `state.py` | `TaskState` dataclass + 阶段推进纯函数（与接口规范 §4 字面量一致） |
| `checkpoint.py` | checkpoint.json 原子写（`.tmp` + `os.replace`，失败清理）、版本一致性校验 |
| `research.py` | 选题前研究：最多两轮按需调用本地 Firecrawl / Brave / Tavily 等 MCP，并定向检索 IMA 参考库，再由 MCP 调度器抓取正文 |
| `topic_selection.py` | 选题：仅基于两轮研究资料调 planner 拿 5 候选 → 用户选/自选 |
| `evidence.py` | 按结果缺口检索并由 MCP 调度器抓正文：调 search + crawler → `资料/证据清单.json` |
| `planning.py` | 策划：调 planner 出三角度策划.md |
| `drafts.py` | 三稿：调 writer 依次生成 3 篇独立初稿；主模型遇 429 时依次回退 GLM-5.1、MiniMax-M3 |
| `review.py` | 审稿：调 reviewer；4 类必阻断不能被 score 救活 |
| `deai.py` | 去 AI 味润色：按 review_1.recommendation 选优 → qwen 整篇改写（温度 0.85）→ 写 `待定稿/推荐稿.md` |
| `finalizing.py` | 待定稿辅助产物：输出备选标题 + 摘要 + 资料口径 |
| `orchestrator.py` | 编排、checkpoint、模块级 `resume` / `rerun` |
| `prompts.py` | 从 `提示词/` 加载岗位系统提示词 |
| `tests/` | 见 `测试/流水线/` |

## 阶段顺序

`topic_research → topic_selection → evidence_collection → planning → draft_1 → draft_2 → draft_3 → review_1 → deai → finalizing`，其中 `topic_research` 和 `evidence_collection` 都必须完成搜索后的网页抓取；IMA 只处理关键词命中的条目，不做全库下载；`deai` 阶段一次性润色优选稿并写 `待定稿/推荐稿.md`，随后自动推进到 `finalizing`；`awaiting_human` 不再被复审失败自动触发，仅由用户/诊断主动设置；`archived` 由用户在 6 号菜单触发，本流水线不实现。

## 依赖

- 标准库：`dataclasses` / `datetime` / `hashlib` / `json` / `os` / `pathlib` / `typing`。
- 跨模块：阶段代码只引用 `工作台.接口` 的数据类与 Protocol。真实客户端由 `orchestrator.build_orchestrator` 在续跑时组装。
- 运行依赖：项目隔离环境中的 `mcp>=1.26,<2`；Scrapy 仅供独立批量爬站工具使用。
- 可选：`pytest`（仅在运行 `测试/流水线/` 时需要，由主线程按需安装）。

## 不变量（接口规范对齐）

- 阶段字面量与接口规范 §4 完全一致；新加状态必须先打回主线程补规范。
- `pass_` 与 4 类 `block` 的关系：`block` 出现即 `pass_=False`，**`score` 不得救活**；新流程下 `pass_` 仅作显示，**不再阻断 stage 跳转**。
- `deai_temperature` 默认 0.85；`deai` 阶段只调一次 writer，不循环；不在任何节点自动切 `awaiting_human`。
- checkpoint 写失败时清理 `.tmp`，不得留下半文件。
- 上游重跑 → `rerun_invalidated` 含当前及之后所有阶段；阶段生成新产物后立即移出清单；恢复时若产物哈希与 `versions` 不一致 → `VersionMixingError`。
- 初稿主写手遇 HTTP 429 且内置重试耗尽后，才按 GLM-5.1 → MiniMax-M3 顺序尝试；认证、岗位配置、网络及其他错误不触发模型切换。此策略只用于三篇初稿，不影响审稿、去 AI 味润色和定稿。
