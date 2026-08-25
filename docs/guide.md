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

服务提供两种 MCP transport：Streamable HTTP 和 stdio。两种方式暴露同一组工具，包括本地标的模糊搜索、行情历史、策略、交易和持仓查询。

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

## 测试与质量检查

```bash
make deps
make lint
make test
```

也可直接执行 `PYTHONPATH=src .venv/bin/pytest` 和 `.venv/bin/ruff check .`。
