#!/usr/bin/env bash
# ============================================================
# 熵减进化室 · 内容工坊 — macOS / Linux 启动脚本（C：数字工作台）
#
# 入口：python3 -m 工作台.菜单.app
# 编码：UTF-8 (en_US.UTF-8)；中文与空格路径必须 UTF-8。
#
# 注意：
# - 不要写死绝对路径或用户目录；保持脚本可移植。
# - 不要在这里执行任何密钥写入或网络调用。
# ============================================================

set -e

# 把当前工作目录切到脚本所在位置（即仓库根），便于 ``python -m``
# 在 Finder 双击与终端两种入口下都能解析到正确包。
cd "$(dirname "$0")"

# 强制 UTF-8，避免 macOS 默认 zh_CN.UTF-8 / Linux 无 locale 下中文乱码。
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1
ROOT="$(pwd)"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"

# 清掉 shell 里残留的工作台专有 key，让 配置/凭据/.env 成为 source of truth。
# envfile.load_env_files 的约定是 shell 环境优先；桌面场景下 launcher
# 继承 launchd 容易带进失效的旧 export，先 unset 再让 .env 接管。
for _wb_k in \
    MINIMAX_BASE_URL MINIMAX_API_KEY \
    QWEN_BASE_URL    QWEN_API_KEY \
    GLM_BASE_URL     GLM_API_KEY \
    TAVILY_API_KEY   BRAVE_API_KEY
do
    unset "$_wb_k"
done
unset _wb_k

# 让 Python 找到 CA bundle。pyenv 装的 Python 在 macOS / 多数 Linux
# 发行版上找不到 OpenSSL 默认证书目录，会导致所有 HTTPS 验证失败
# （CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate）。
# 按优先级回退到 macOS / Debian / certifi，确保 urllib / httpx / requests
# 都能正确校验证书链。
for _wb_ca in \
    /etc/ssl/cert.pem \
    /etc/ssl/certs/ca-certificates.crt \
    "$(python3 -c 'import certifi; print(certifi.where())' 2>/dev/null)"
do
    if [ -r "$_wb_ca" ]; then
        export SSL_CERT_FILE="$_wb_ca"
        export REQUESTS_CA_BUNDLE="$_wb_ca"
        export CURL_CA_BUNDLE="$_wb_ca"
        break
    fi
done
unset _wb_ca

# 透传所有参数；菜单当前未读取，但保留扩展空间。
exec python3 -m 工作台.菜单.app "$@"