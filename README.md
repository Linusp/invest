# Invest Service

从 Oreo 拆出的独立投资数据服务，提供 FastAPI REST API 与 MCP
Streamable HTTP/stdio 两种接口。服务负责：

- 带原始计价币种的个股、ETF、指数搜索、注册、日线同步和历史行情查询。
- 从欧洲央行同步每日汇率，将多币种资产统一折算到系统报告币种。
- 按固定周期自动更新所有已注册标的，启动后立即执行第一次更新。
- 策略创建、列表、详情与元数据修改。
- 以现金、持仓成本和历史盈亏导入策略期初状态，无需补齐全部历史交易。
- 买入、卖出、入金、出金流水的追加和查询。
- 从交易流水实时推导持仓、移动平均成本、现金、已实现及浮动盈亏。
- 按交易日收盘状态划分持仓周期，并统计已清仓周期的胜率和盈亏比。
- 通过同一领域服务暴露 12 个 MCP 工具。

## 本地运行

要求 Python 3.11+。

```bash
cd invest
python -m venv .venv
.venv/bin/pip install -e '.[test]'
cp .env.example .env
# 编辑 .env，填写 INVEST_TUSHARE_TOKEN
.venv/bin/uvicorn invest_service.main:app --reload
```

默认 API 地址是 `http://127.0.0.1:8000`，OpenAPI 文档位于
`/docs`，MCP Streamable HTTP 端点是 `/mcp/`。Web 页面位于：

- `/market`：标的搜索、行情更新、K 线和历史明细。
- `/strategy`：策略、交易、持仓和盈亏管理。

也可以使用 stdio：

```bash
invest-mcp
```

MCP 客户端的 HTTP 配置示例：

```json
{
  "mcpServers": {
    "invest": {
      "type": "streamable-http",
      "url": "http://127.0.0.1:8000/mcp/"
    }
  }
}
```

## Docker

```bash
cd invest
docker compose up --build -d
```

默认映射到宿主机 `8001` 端口。PostgreSQL 数据保存在
`invest-db` volume 中。

## 主要 REST API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/assets/search?q=...` | 搜索并自动注册标的 |
| `POST` | `/api/v1/assets` | 手动注册标的 |
| `POST` | `/api/v1/assets/{symbol}/sync` | 更新单个标的行情 |
| `POST` | `/api/v1/assets/sync` | 更新全部标的行情 |
| `GET` | `/api/v1/assets/{symbol}/history` | 查询历史行情 |
| `POST` | `/api/v1/exchange-rates/sync` | 同步 ECB 每日或完整历史汇率 |
| `GET` | `/api/v1/exchange-rates/{currency}` | 查询指定日期前最近汇率 |
| `POST` | `/api/v1/strategies` | 创建策略 |
| `GET` | `/api/v1/strategies/{id}` | 查询策略详情 |
| `PATCH` | `/api/v1/strategies/{id}` | 修改策略 |
| `GET` | `/api/v1/strategies/{id}/opening-snapshot` | 查询期初状态 |
| `PUT` | `/api/v1/strategies/{id}/opening-snapshot` | 新增或替换期初状态 |
| `DELETE` | `/api/v1/strategies/{id}/opening-snapshot` | 删除无后续交易的期初状态 |
| `POST` | `/api/v1/strategies/{id}/trades` | 增加交易 |
| `GET` | `/api/v1/strategies/{id}/trades` | 查询交易 |
| `GET` | `/api/v1/strategies/{id}/positions` | 查询持仓 |

证券交易的 `price` 表示标的原币种成交单价，`quantity` 表示数量，币种由
标的自动确定；入金和出金的 `price` 表示现金金额，必须明确币种，且不能携带
标的或数量。客户端可传
`idempotency_key` 安全重试新增交易。

每笔买卖交易都会返回 `position_id`，入金和出金的该字段为空。同一标的只在某个
交易日结束后持仓为零时结束当前持仓周期；因此同日先清仓再买回仍使用原
`position_id`，之后的交易日再次建仓才会获得新 ID。旧交易会在服务启动时自动
回填该字段。

策略详情的 `summary` 包含 `completed_position_count`、
`winning_position_count`、`win_rate` 和 `profit_loss_ratio`。未清仓周期不参与
统计；胜率是盈利周期数除以全部已清仓周期数。每个周期以持仓过程中最大的成本
金额为分母、最终已实现盈亏为分子计算收益率，盈亏比是盈利周期平均收益率除以
亏损周期平均收益率的绝对值；缺少盈利或亏损样本时盈亏比为空。

期初状态包含状态日期、多币种现金余额、持仓数量与原币种平均成本，以及各币种
的历史已清仓总盈亏。历史净投入可留空；任一币种留空时仍会按已实现盈亏加
浮动盈亏计算总收益，但净投入和收益率保持未知。期初状态之后的交易日期必须
晚于状态日期。

## 自动更新

以下配置均使用 `INVEST_` 前缀：

- `DATABASE_URL`：SQLite 或 PostgreSQL SQLAlchemy URL。
- `AUTO_UPDATE_ENABLED`：是否启用更新任务，默认 `true`。
- `AUTO_UPDATE_INTERVAL_MINUTES`：更新周期，默认 60 分钟。
- `AUTO_UPDATE_LOOKBACK_DAYS`：每次回溯天数，默认 10 天。
- `REPORTING_CURRENCY`：策略汇总的统一报告币种，默认 `CNY`。
- `EXCHANGE_RATE_UPDATE_HOUR`：每日汇率更新时间（Asia/Shanghai），默认 23 点。
- `MARKET_PROVIDER`：行情源，默认 `tushare`；可显式设为 `eastmoney`。
- `TUSHARE_TOKEN`：Tushare Pro token，使用默认行情源时必填。
- `EASTMONEY_TOKEN`：仅在 `MARKET_PROVIDER=eastmoney` 时使用。
- `INDEX_FALLBACK_PROVIDER`：指数日线兜底，默认 `akshare`，设为 `none`
  可关闭。AkShare 内部先请求腾讯，失败或无数据时再请求新浪。
- `ETF_FALLBACK_PROVIDER`：ETF 搜索与日线兜底，默认 `akshare`，设为
  `none` 可关闭。搜索先使用 AkShare 新浪列表、再以东方财富列表兜底；
  日线先复用无代理的东方财富 provider，失败后再使用新浪历史行情。
- `MCP_ALLOWED_HOSTS`：MCP 允许的 Host 列表；经反向代理发布时必须加入域名。
- `MCP_ALLOWED_ORIGINS`：浏览器 MCP 客户端允许的 Origin 列表。

Tushare 分别通过 `daily`、`fund_daily`、`index_daily` 获取个股、ETF
和指数日线，返回的成交额会从千元换算为元。指数的 Tushare 请求失败或
返回空数据时，会自动使用 AkShare 的腾讯/新浪数据源；ETF 的 Tushare
目录不可用时，会使用 AkShare 的新浪/东方财富列表，日线不可用时使用
东方财富/新浪接口。单个标的第一次同步默认回填
十年，后续更新仅回溯配置的天数。最近三天的
行情会覆盖更新；更早的数据仅在显式传入 `overwrite=true` 时更新。

汇率使用欧洲中央银行公布的欧元参考汇率。首次同步会回填 CNY、HKD、USD、EUR
及所有已使用币种的完整历史，之后每天 23:30 更新；周末和休市日估值使用目标
日期之前最近一个可用汇率。ECB 说明该参考汇率仅供信息用途，不适合作为实际
成交汇率。

## 迁移 Oreo 行情

迁移脚本从旧 Oreo 数据库复制标的和历史行情，不修改源数据库：

```bash
PYTHONPATH=src .venv/bin/python scripts/migrate_oreo.py \
  --source 'postgresql+psycopg://oreo:password@host/oreo' \
  --target 'postgresql+psycopg://invest:password@host/invest'
```

旧页面的策略数据存放在浏览器 `localStorage`，不在 Oreo 数据库中，无法由
数据库迁移脚本自动读取。迁移后应通过策略和交易 API 导入这些流水。

## 测试

```bash
PYTHONPATH=src .venv/bin/pytest
.venv/bin/ruff check .
```
