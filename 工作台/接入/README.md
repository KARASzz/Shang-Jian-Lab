# 工作台 / 接入层（A 子智能体）

模型与搜索接入：固定岗位、字段契约、错误分类，并通过配置的真实服务获取结果。

## 目录

```
工作台/接入/
├── __init__.py
├── README.md              # 本文件
├── config.py              # 从 配置/默认.toml 读字段名；不读真实密钥
├── discovery.py           # 启动时发现五个本地 MCP 工具（旧 API 发现函数保留）
├── models/
│   ├── __init__.py
│   ├── client.py          # OpenAI 兼容 Chat Completions
│   ├── errors.py          # AuthError / TimeoutError / RateLimitError / NetworkError
│   └── schemas.py         # ModelRequest / ModelResponse / TokenUsage（接口规范 §1）
└── search/
    ├── __init__.py
    ├── local_mcp.py       # 读取 Codex config.toml，管理本地 MCP 生命周期
    ├── research_agent.py  # 五 MCP 检索、正文抓取与安全调度
    ├── ima_kb.py          # IMA 知识库定向检索与命中正文
    ├── composite.py       # 旧版三渠道兼容入口（默认不调用）
    ├── bing_public.py     # 旧版公开搜索兼容入口（默认不调用）
    ├── brave_mcp.py       # 旧版 Brave 兼容入口（默认不调用）
    ├── schemas.py         # SearchSource（接口规范 §2）
    ├── scrapy_crawler.py  # 保留的独立批量爬站工具，不在默认流水线启用
    ├── tavily_mcp.py      # 旧版 Tavily 兼容入口（默认不调用）
    └── requirements.txt   # 项目隔离环境的 MCP SDK 依赖
```

## 与接口规范对齐

| 规范节点 | 字段 | 实现 |
|---|---|---|
| §1 模型接口 | `ModelRequest` / `ModelResponse` / `TokenUsage` | `工作台/接入/models/schemas.py` |
| §1 模型约束 | 180s 超时 / 重试 2 次 / 401/403 直接停 | `工作台/接入/models/client.py` |
| §1 模型约束 | `raw_error` 非空即失败 | `工作台/接入/models/errors.py` + `client.py` |
| §2 搜索接口 | `SearchSource` 字段与字面量 | `工作台/接入/search/schemas.py` |
| §2 MCP 启动 | stdio / http 均由本地 SDK 初始化、工具发现、调用和关闭 | `工作台/接入/search/local_mcp.py` |
| §5 调用限制 | 超时 / 重试 / 限流上限 | `工作台/接入/models/client.py` |

## 搜索与抓取分工

- `ResearchDispatchAgent` 每轮调用本地 `brave-search`、`tavily`、`mcp-omnisearch`、`firecrawl-stdio` 四个搜索 MCP；不启用 Node REPL。
- 正文抓取由 Firecrawl、Tavily、Omnisearch 轮转，并用 Playwright 处理动态页面或作回退；每次调用写入当期资料目录的 `MCP调度记录.jsonl`。
- IMA 知识库按配置的知识库名称和当前选题关键词定向检索；每次最多取 `max_results` 条命中，不遍历或下载全库。
- `ScrapyCrawler` 保留给需要站内多页批量爬取的独立脚本；默认选题研究和证据阶段不再依赖 Scrapy。
- IMA 命中的可访问正文写入当期 `选题/研究/抓取/IMA正文/` 或 `资料/IMA正文/`，不交给 MCP 调度器重复抓取。
- 选题研究严格执行两轮；证据阶段也必须抓取正文。五 MCP 中任一搜索调用失败会留下 `fetch_failed` 记录，不能伪装成成功；正文提取失败不会把搜索摘要提升为正文。

## 运行

```bash
python -m unittest discover -s 测试/接入 -v
```

## 首次配置（主线程集成交付阶段执行）

1. 把 `配置/默认.toml` 复制为 `配置/本地.toml`：

   ```bash
   cp 配置/默认.toml 配置/本地.toml
   ```

2. 在终端**本地隐藏输入**以下工作台 / IMA 环境变量，不要写进任何仓库文件；Tavily / Brave 的变量只有在本机 Codex MCP 配置引用它们时才需要：

   ```text
   MINIMAX_BASE_URL / MINIMAX_API_KEY
   QWEN_BASE_URL / QWEN_API_KEY
   GLM_BASE_URL / GLM_API_KEY
   TAVILY_API_KEY
   BRAVE_API_KEY
   IMA_OPENAPI_CLIENTID / IMA_OPENAPI_APIKEY
   ```

   本地 MCP 还可能引用 `FIRECRAWL_API_KEY` 等变量；以本机 Codex `config.toml` 中对应 `mcp_servers.<name>.env` 的键名为准，只在本地环境设置值。

3. `配置/本地.toml` 中 `[search.local_mcp]` 的 `config_path` 可选；留空时读取 `CODEX_HOME/config.toml` 或用户目录下 `.codex/config.toml`。客户端固定读取 `brave-search`、`tavily`、`mcp-omnisearch`、`firecrawl-stdio`、`playwright` 五项，明确排除 `node_repl`。

4. `[search.reference.ima]` 仍可按 `knowledge_base_name` 定向检索；它是参考库，不计入五个本地 MCP。

5. 真实 base URL、key、MCP 启动参数**绝不写入仓库**；日志脱敏，不打印也不返回真实 key。

## 行为约定

- **未配置 key**：模型或搜索调用立即抛出明确错误，绝不返回假响应。
- **搜索失败或没有有效来源**：记录失败并停止证据阶段，不能继续策划和写稿。
- **HTTP 401/403**：抛 `AuthError`，不重试，立即停止。
- **HTTP 429**：抛 `RateLimitError`，按 `Retry-After` 退避，最多 `max_retries` 次。
- **超时 180s**：抛 `TimeoutError`；其它网络错误抛 `NetworkError`。两者均计入重试。

## 依赖

- 标准库：`dataclasses`、`tomllib`（Python 3.11+）、`urllib.request`、`urllib.error`、`subprocess`、`os`。
- 第三方运行依赖：`mcp>=1.26,<2`，见 `工作台/接入/requirements.txt`；使用项目隔离环境安装。Scrapy 只作为可选的独立爬站工具。

## 边界

- 本目录负责模型、搜索和配置接入；流水线状态机、菜单、CLI 位于对应目录。
- `工作台/接入/*.py` 与 `测试/接入/*.py` 是 A 子智能体的完整交付范围。
