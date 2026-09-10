# 工作台 / 接入层（A 子智能体）

模型与搜索接入的**占位实现**：固定岗位、字段契约、错误分类，但不发起真实网络请求、不读取真实密钥。

## 目录

```
工作台/接入/
├── __init__.py
├── README.md              # 本文件
├── config.py              # 从 配置/默认.toml 读字段名；不读真实密钥
├── discovery.py           # 启动时初始化 MCP、握手、做工具发现（占位）
├── models/
│   ├── __init__.py
│   ├── client.py          # OpenAI 兼容 Chat Completions 占位
│   ├── errors.py          # AuthError / TimeoutError / RateLimitError / NetworkError
│   └── schemas.py         # ModelRequest / ModelResponse / TokenUsage（接口规范 §1）
└── search/
    ├── __init__.py
    ├── bing_public.py     # Bing 公开搜索占位 + 限流
    ├── brave_mcp.py       # Brave http MCP 握手占位
    ├── schemas.py         # SearchSource（接口规范 §2）
    └── tavily_mcp.py      # Tavily stdio MCP 启动占位
```

## 与接口规范对齐

| 规范节点 | 字段 | 实现 |
|---|---|---|
| §1 模型接口 | `ModelRequest` / `ModelResponse` / `TokenUsage` | `工作台/接入/models/schemas.py` |
| §1 模型约束 | 180s 超时 / 重试 2 次 / 401/403 直接停 | `工作台/接入/models/client.py` |
| §1 模型约束 | `raw_error` 非空即失败 | `工作台/接入/models/errors.py` + `client.py` |
| §2 搜索接口 | `SearchSource` 字段与字面量 | `工作台/接入/search/schemas.py` |
| §2 MCP 启动 | stdio 先做工具发现；http 先 ping `/mcp` 握手 | `工作台/接入/search/tavily_mcp.py` / `brave_mcp.py` / `discovery.py` |
| §5 调用限制 | 超时 / 重试 / 限流上限 | `工作台/接入/models/client.py` |

## 运行

```bash
python -m unittest discover -s 测试/接入 -v
```

## 首次配置（主线程集成交付阶段执行）

1. 把 `配置/默认.toml` 复制为 `配置/本地.toml`：

   ```bash
   cp 配置/默认.toml 配置/本地.toml
   ```

2. 在终端**本地隐藏输入**以下环境变量，不要写进任何仓库文件：

   ```text
   MINIMAX_BASE_URL / MINIMAX_API_KEY
   QWEN_BASE_URL / QWEN_API_KEY
   GLM_BASE_URL / GLM_API_KEY
   TAVILY_API_KEY
   BRAVE_API_KEY
   ```

3. `配置/本地.toml` 中 MCP 启动字段：

   - `[search.mcp.tavily]`：`transport = "stdio"`，需填 `command` / `args`（默认 `npx -y @tavily/mcp-server`）。
   - `[search.mcp.brave]`：`transport = "http"`，需填 `url`（默认 `http://localhost:8080/mcp`）。

4. 真实 base URL、key、MCP 启动参数**绝不写入仓库**；日志脱敏，不打印也不返回真实 key。

## 行为约定（占位阶段）

- **未配置 key**：所有 `ModelClient.complete()` 调用立即抛 `AuthError`，**绝不静默回退到占位响应**。
- **未启动 MCP**：`discover_all()` 返回 `MCPDiscoveryResult(status="not_run_in_dev", tools=[])`，不抛异常。
- **HTTP 401/403**：抛 `AuthError`，不重试，立即停止。
- **HTTP 429**：抛 `RateLimitError`，按 `Retry-After` 退避，最多 `max_retries` 次。
- **超时 180s**：抛 `TimeoutError`；其它网络错误抛 `NetworkError`。两者均计入重试。

## 依赖

- 标准库：`dataclasses`、`tomllib`（Python 3.11+）、`urllib.request`、`urllib.error`、`subprocess`、`os`。
- 可选第三方：暂未引入。集成阶段若引入 `httpx` / `requests`，需在本节追加并标注「可选」。

## 边界

- 本目录只写代码占位 + 配置接入文档；**不实现流水线状态机、菜单、CLI**。
- `工作台/接入/*.py` 与 `测试/接入/*.py` 是 A 子智能体的完整交付范围。
