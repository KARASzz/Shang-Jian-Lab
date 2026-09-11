# 工作台 / 接入层（A 子智能体）

模型与搜索接入：固定岗位、字段契约、错误分类，并通过配置的真实服务获取结果。

## 目录

```
工作台/接入/
├── __init__.py
├── README.md              # 本文件
├── config.py              # 从 配置/默认.toml 读字段名；不读真实密钥
├── discovery.py           # 启动时初始化连接、握手、做工具发现
├── models/
│   ├── __init__.py
│   ├── client.py          # OpenAI 兼容 Chat Completions
│   ├── errors.py          # AuthError / TimeoutError / RateLimitError / NetworkError
│   └── schemas.py         # ModelRequest / ModelResponse / TokenUsage（接口规范 §1）
└── search/
    ├── __init__.py
    ├── bing_public.py     # Bing 公开搜索 + 限流
    ├── brave_mcp.py       # Brave MCP / Search API
    ├── schemas.py         # SearchSource（接口规范 §2）
    ├── scrapy_crawler.py  # 搜索结果 URL 的有限深度正文抓取
    └── tavily_mcp.py      # Tavily Search API
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

## 搜索与抓取分工

- Tavily、Brave、Bing 负责发现候选 URL；每轮各调用一次。
- `ScrapyCrawler` 负责下载和解析这些 URL，正文写入当期 `选题/研究/抓取/`。
- 选题研究严格执行两轮；Scrapy 未安装、三渠道调用未完成或有效渠道不足时停止，不生成 5 个候选。

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

3. `配置/本地.toml` 中搜索连接字段：

   - `[search.mcp.tavily]`：读取 `env.TAVILY_API_KEY` 指向的环境变量，直接调用 Tavily Search API。
   - `[search.mcp.brave]`：先尝试 `url` 的 MCP 端点；连接失败时用 `api_key_env` 调用 Brave Search API。

4. 真实 base URL、key、MCP 启动参数**绝不写入仓库**；日志脱敏，不打印也不返回真实 key。

## 行为约定

- **未配置 key**：模型或搜索调用立即抛出明确错误，绝不返回假响应。
- **搜索失败或没有有效来源**：记录失败并停止证据阶段，不能继续策划和写稿。
- **HTTP 401/403**：抛 `AuthError`，不重试，立即停止。
- **HTTP 429**：抛 `RateLimitError`，按 `Retry-After` 退避，最多 `max_retries` 次。
- **超时 180s**：抛 `TimeoutError`；其它网络错误抛 `NetworkError`。两者均计入重试。

## 依赖

- 标准库：`dataclasses`、`tomllib`（Python 3.11+）、`urllib.request`、`urllib.error`、`subprocess`、`os`。
- 第三方运行依赖：`Scrapy`（选题研究阶段必须安装；当前 Python 环境可用
  `python3 -m pip install 'Scrapy>=2.13' 'pyOpenSSL<26' 'cryptography<47' 'service-identity<26'`
  安装，避免覆盖已有加密依赖）。

## 边界

- 本目录负责模型、搜索和配置接入；流水线状态机、菜单、CLI 位于对应目录。
- `工作台/接入/*.py` 与 `测试/接入/*.py` 是 A 子智能体的完整交付范围。
