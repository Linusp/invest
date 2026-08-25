# Invest Service

独立的投资数据服务，提供 FastAPI REST API、Web 页面和 MCP 接口，支持个股、ETF、指数的本地搜索、行情、标签自选和策略交易分析。

## 快速开始

要求 Python 3.12。使用 Docker Compose：

```bash
cp .env.example .env
# 按需编辑 .env
docker compose up --build -d
docker compose ps
curl http://127.0.0.1:8001/health
```

本地开发环境：

```bash
python -m venv .venv
.venv/bin/pip install -e '.[test]'
cp .env.example .env
make test
```

默认 Web 地址为 `http://127.0.0.1:8001`，本地进程默认使用 `8000` 端口。OpenAPI 文档位于 `/docs`，MCP Streamable HTTP 端点为 `/mcp/`。

## 页面入口

- `/market`：按标签浏览和管理自选标的。
- `/market/{category}/{symbol}`：查看单个标的行情、历史数据和日期快捷范围。
- `/strategy`：管理策略、交易、持仓和盈亏。

## 文档

- [开发与部署指南](docs/guide.md)
- [REST API 参考](docs/api.md)
- [行情源、搜索索引与定时任务](docs/market-data.md)

## 常用命令

```bash
make deps
make lint
make test
docker compose logs -f app worker beat
```

生产环境可使用 PostgreSQL 或 MySQL Compose 覆盖配置，详见[开发与部署指南](docs/guide.md)。
