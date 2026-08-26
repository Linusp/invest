# 开发与部署指南

## 本地运行

Worker 和 Beat 需要 Redis；地址由 `INVEST_CELERY_BROKER_URL` 配置。只调试查询 API 时可以暂不启动它们。

```bash
.venv/bin/celery -A invest_service.celery_app:celery_app worker --loglevel=INFO
.venv/bin/celery -A invest_service.celery_app:celery_app beat --loglevel=INFO
.venv/bin/uvicorn invest_service.main:app --reload
```

也可以启动 stdio MCP：`invest-mcp`。

## Docker Compose

默认使用 SQLite，并一起启动 API、Worker、Beat 和 Redis：

```bash
docker compose up --build -d
docker compose ps
```

PostgreSQL：

```bash
docker compose -f docker-compose.yml -f docker-compose.postgres.yml up --build -d
```

MySQL 8.4：

```bash
docker compose -f docker-compose.yml -f docker-compose.mysql.yml up --build -d
```

默认映射宿主机 `8001` 端口。停止服务使用对应命令加 `down`；不要加 `-v`，除非确认需要删除数据库和队列数据。生产环境务必修改数据库密码。`COMPOSE_DATABASE_URL` 是 Compose 专用变量，与应用使用的 `INVEST_DATABASE_URL` 分开。

## MCP 接入

服务提供两种 MCP transport：Streamable HTTP 和 stdio。两种方式暴露同一组工具，包括本地标的模糊搜索、行情历史、组合、交易和持仓查询。

### Streamable HTTP

服务启动后，MCP endpoint 是 `/mcp/`。端口取决于部署方式：本地 uvicorn 使用 `8000`，默认 Docker Compose 从宿主机 `8001` 转发到容器 `8000`。

```text
本地：  http://127.0.0.1:8000/mcp/
Docker：http://127.0.0.1:8001/mcp/
```

以支持 Streamable HTTP 的 MCP 客户端为例，配置如下：

```json
{
  "mcpServers": {
    "invest": {
      "type": "streamable-http",
      "url": "http://127.0.0.1:8001/mcp/"
    }
  }
}
```

如果客户端运行在另一台机器或通过反向代理访问，需要在 `.env` 中设置允许的 Host；浏览器型 MCP 客户端还需要设置允许的 Origin：

```dotenv
INVEST_MCP_ALLOWED_HOSTS=["invest.example.com","invest.example.com:443"]
INVEST_MCP_ALLOWED_ORIGINS=["https://chat.example.com"]
```

配置修改后重启 app。MCP 使用的 Host/Origin 校验不是用户认证；生产环境应在反向代理或网关层增加身份认证，并使用 HTTPS。

最小验证方式是先打开 `http://127.0.0.1:8001/health`，再在 MCP 客户端中连接 endpoint，确认能看到 `search_assets`、`get_market_history`、`list_strategies` 等工具。

### stdio

stdio 适合桌面客户端或本机代理。客户端每次连接时启动一个进程，工作目录应为项目目录，且该进程能读取 `.env`：

```bash
invest-mcp
```

例如支持 stdio 的客户端可以配置：

```json
{
  "mcpServers": {
    "invest-local": {
      "command": "/absolute/path/to/invest/.venv/bin/invest-mcp",
      "args": [],
      "cwd": "/absolute/path/to/invest",
      "env": {
        "INVEST_DATABASE_URL": "sqlite:///./invest.db"
      }
    }
  }
}
```

如果没有安装 entrypoint，也可以使用：

```bash
.venv/bin/python -c 'from invest_service.mcp_server import run_stdio; run_stdio()'
```

## 各 coding agent 的接入示例

以下示例都假定服务已启动。远程 HTTP 示例使用 Docker 地址 `http://127.0.0.1:8001/mcp/`；如果 agent 与服务不在同一台机器，请替换为可访问的 HTTPS 地址。仅在 agent 与 Invest 同机时使用 stdio。

### Claude Code

Claude Code 支持命令行添加 HTTP 或 stdio MCP。HTTP：

```bash
claude mcp add --transport http invest http://127.0.0.1:8001/mcp/
claude mcp list
```

stdio：

```bash
claude mcp add --transport stdio invest -- \
  /absolute/path/to/invest/.venv/bin/invest-mcp
claude mcp list
```

默认写入用户级配置；如果只想当前项目可用，加 `--scope project`。也可以在项目根目录的 `.mcp.json` 中写入：

```json
{
  "mcpServers": {
    "invest": {
      "type": "http",
      "url": "http://127.0.0.1:8001/mcp/"
    }
  }
}
```

进入 Claude Code 后运行 `/mcp` 查看连接状态和工具列表。官方说明见 [Claude Code MCP 文档](https://code.claude.com/docs/en/mcp)。

### OpenCode

在项目根目录创建或编辑 `opencode.json` / `opencode.jsonc`，使用 V2 配置格式 `mcp.servers`。HTTP：

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "invest": {
        "type": "remote",
        "url": "http://127.0.0.1:8001/mcp/",
        "oauth": false
      }
    }
  }
}
```

stdio：

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "invest": {
        "type": "local",
        "command": ["/absolute/path/to/invest/.venv/bin/invest-mcp"]
      }
    }
  }
}
```

OpenCode 会自动连接未设置 `disabled: true` 的 server。运行 `opencode` 后，可在 MCP/工具列表中确认 `invest` 已加载。配置格式以 [OpenCode MCP 文档](https://opencode.ai/docs/mcp-servers/) 为准。

### Codex CLI

Codex CLI 使用 TOML，配置文件为 `~/.codex/config.toml`。HTTP：

```toml
[mcp_servers.invest]
url = "http://127.0.0.1:8001/mcp/"
enabled = true
```

stdio：

```toml
[mcp_servers.invest]
command = "/absolute/path/to/invest/.venv/bin/invest-mcp"
args = []
enabled = true

[mcp_servers.invest.env]
INVEST_DATABASE_URL = "sqlite:///./invest.db"
```

也可以使用 CLI 管理 stdio server：

```bash
codex mcp add invest -- /absolute/path/to/invest/.venv/bin/invest-mcp
codex mcp list
```

重启 Codex CLI 或重新打开会话后，使用 `/mcp`（若当前版本提供该命令）或让 agent 调用 `search_assets` 验证。Codex 的配置键是 `mcp_servers`，不是其他客户端常见的 `mcpServers`；参考 [Codex MCP 配置](https://www.mintlify.com/openai/codex/configuration/mcp-servers)。

### pi coding agent

Pi 本身通过 MCP adapter 接入 MCP。推荐安装 `pi-mcp-adapter`，它支持标准 `.mcp.json`，并可通过 `/mcp setup` 导入其他 agent 的配置：

```bash
pi install npm:pi-mcp-adapter
```

在项目根目录创建 `.mcp.json`：

```json
{
  "mcpServers": {
    "invest": {
      "type": "http",
      "url": "http://127.0.0.1:8001/mcp/"
    }
  }
}
```

stdio 配置把 server 改为：

```json
{
  "mcpServers": {
    "invest": {
      "command": "/absolute/path/to/invest/.venv/bin/invest-mcp",
      "args": []
    }
  }
}
```

启动 `pi` 后运行 `/mcp` 查看和连接 server；如果已有 Claude Code、Codex 等配置，可运行 `/mcp setup` 选择导入。Pi 的 adapter 默认按需连接，首次调用 Invest 工具时才启动连接。详情见 [pi-mcp-adapter](https://pi.dev/packages/pi-mcp-adapter)。

### 通用排障

1. 先确认 `curl http://127.0.0.1:8001/health` 返回 `{"status":"ok"}`。
2. HTTP 连接失败时检查 agent 所在环境是否能访问该地址；容器内的 `127.0.0.1` 指向容器自身，不一定是宿主机。
3. stdio 失败时使用绝对路径，并确认 `.venv`、数据库路径和 `.env` 对该进程可见。
4. 修改配置后重启 agent；Pi 需要 `/reload`，Claude Code 可重新执行 `/mcp` 查看状态。
5. 生产环境不要把数据库密码或 Tushare token 写入项目配置并提交到 Git。

## 测试与质量检查

```bash
make deps
make lint
make test
```

也可直接执行 `PYTHONPATH=src .venv/bin/pytest` 和 `.venv/bin/ruff check .`。
