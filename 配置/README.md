# 配置

- `默认.toml`：可入库的样例，**不含密钥**。
- `本地.toml`：首次运行由菜单从默认复制；gitignore。
- `本期.toml`：新建一期时冻结的岗位快照；gitignore。
- `凭据/.env`：Base URL 与 API Key；gitignore。8 号菜单隐藏输入后写入。

## 字段约定

- `*_env` 字段值是环境变量名，不是真实密钥；运行时从环境或 `凭据/.env` 读取。
- 模型岗位在本期开始时冻结到 `本期.toml`；本期运行期间不得换模型。
- `transport = "stdio"` 必须配套 `command` + `args`；`transport = "http"` 必须配套 `url`，可选 `api_key_env`。
- `[review]` / `[task]` / `[pipeline].auth_failure_abort` 禁止项必须保持 `true`。
