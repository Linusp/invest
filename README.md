# Invest Service

独立的投资数据服务，提供 FastAPI REST API、Web 页面和 MCP 接口，支持个股、ETF、指数的本地搜索、行情、标签自选和组合交易分析。

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
- `/strategy`：管理组合属性和核心指标；持仓、交易、点评、交易计划以四个可筛选、分页、表头三态排序的列表呈现。
- `/analysis`：管理市场、行业、主题和商品层级，并查看市场点评。
- `/information`：提交、筛选和阅读外部资讯。

## 文档

- [开发与部署指南](docs/guide.md)
- [REST API 参考](docs/api.md)
- [行情源、搜索索引与定时任务](docs/market-data.md)
- [OpenCLI / Agent 外部资讯接入](docs/information.md)
- [组合、点评与交易计划需求文档（已 Review）](docs/portfolio-commentary-trade-plan-prd.md)

## 常用命令

```bash
make deps
make lint
make test
docker compose logs -f app worker beat
```

生产环境可使用 PostgreSQL 或 MySQL Compose 覆盖配置，详见[开发与部署指南](docs/guide.md)。
