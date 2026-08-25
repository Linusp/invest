# Invest Service

独立的投资数据服务，提供 FastAPI REST API 与 MCP Streamable HTTP/stdio
两种接口。服务负责：

- 个股、ETF、指数的本地模糊搜索、注册、标签分组、日线同步和历史行情查询。
- 由 Celery 定时聚合 AkShare/Tushare 标的目录，维护名称、别名、曾用名及拼音索引。
- 从欧洲央行同步每日汇率，将多币种资产统一折算到系统报告币种。
- 通过 Celery Beat 定时更新已注册标的和 ECB 汇率，由 Celery Worker 执行任务。
- 策略创建、列表、详情与元数据修改。
- 以现金、持仓成本和历史盈亏导入策略期初状态，无需补齐全部历史交易。
- 买入、卖出、入金、出金流水的追加和查询。
- 从交易流水实时推导持仓、移动平均成本、现金、已实现及浮动盈亏。
- 按交易日收盘状态划分持仓周期，并统计已清仓周期的胜率和盈亏比。
- 通过同一领域服务暴露 11 个 MCP 工具。

## 本地运行

要求 Python 3.12。

```bash
cd invest
python -m venv .venv
.venv/bin/pip install -e '.[test]'
cp .env.example .env
# 编辑 .env，填写 INVEST_TUSHARE_TOKEN；另外启动一个本地 Redis
# 终端 1
.venv/bin/celery -A invest_service.celery_app:celery_app worker --loglevel=INFO
# 终端 2
.venv/bin/celery -A invest_service.celery_app:celery_app beat --loglevel=INFO
# 终端 3
.venv/bin/uvicorn invest_service.main:app --reload
```

Worker 和 Beat 需要 Redis；本地 Redis 地址通过
`INVEST_CELERY_BROKER_URL` 配置。若只调试查询 API，可以暂不启动二者。
搜索请求只读取本地索引，不会调用远端行情源。Celery Beat 默认每天构建一次
目录索引；已有数据库中的标的会在 API 启动时自动写入索引。搜索结果不会自动
加入自选，进入标的页后可按需加入。未配置 Tushare token 时本地搜索和免费目录
仍可使用，页面会提示缺少付费补全源。

默认 API 地址是 `http://127.0.0.1:8000`，OpenAPI 文档位于
`/docs`，MCP Streamable HTTP 端点是 `/mcp/`。Web 页面位于：

- `/market`：按标签分组的自选列表，可置顶、排序标签和表格字段。
- `/market/{category}/{symbol}`：单个标的的 K 线、历史明细和快捷日期范围。
  旧的 `/market/{symbol}` 会在 symbol 唯一时自动跳转；跨分类重码时必须明确分类。
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

## Docker Compose 部署

复制配置并至少填写行情源凭据：

```bash
cp .env.example .env
# 编辑 .env
```

默认方案使用 SQLite，API、Worker、Beat 和 Redis 会一起启动：

```bash
docker compose up --build -d
docker compose ps
curl http://127.0.0.1:8001/health
```

生产环境推荐 PostgreSQL：

```bash
docker compose -f docker-compose.yml -f docker-compose.postgres.yml up --build -d
```

也可以使用 MySQL 8.4：

```bash
docker compose -f docker-compose.yml -f docker-compose.mysql.yml up --build -d
```

默认映射宿主机 `8001` 端口。三种方案分别使用命名卷持久化 SQLite、
PostgreSQL 或 MySQL 数据；Redis 和 Beat 调度状态也会持久化。升级时可执行相同
命令重新构建，停止服务使用对应命令加 `down`。不要加 `-v`，除非确认需要删除
全部数据库和队列数据。用于生产时务必修改默认数据库密码。PostgreSQL/MySQL
密码会拼入 URL，建议只使用 URL 安全字符，或在 `.env` 中设置完整的
`COMPOSE_DATABASE_URL`。它与供本地进程使用的 `INVEST_DATABASE_URL` 分开，
避免把宿主机 SQLite 路径错误地注入容器。

Web 页面所需的 ECharts 和 Lucide 已随镜像提供并启用 gzip，不依赖公共 CDN。

## 主要 REST API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/assets/search?q=...` | 从本地索引模糊搜索标的，可按 `category` 分类 |
| `POST` | `/api/v1/assets` | 手动注册标的 |
| `GET` | `/api/v1/assets/{category}/{symbol}` | 查询分类明确的标的 |
| `GET` | `/api/v1/assets/{category}/{symbol}/tags` | 查询各分组及其加入日期、加入价格 |
| `POST` | `/api/v1/assets/{category}/{symbol}/tags` | 加入一个已有或新建分组 |
| `DELETE` | `/api/v1/assets/{category}/{symbol}/tags/{name}` | 从一个分组移除 |
| `PUT` | `/api/v1/assets/{category}/{symbol}/tags` | 兼容接口：批量覆盖分组列表 |
| `PUT` | `/api/v1/assets/{category}/{symbol}/favorite` | 加入或移出自选（保留资产与行情数据） |
| `GET` | `/api/v1/assets/{category}/{symbol}/history` | 查询历史行情 |
| `POST` | `/api/v1/tags` | 创建空的自定义分组 |
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

标的身份由 `category + symbol` 共同确定。行情、标签自选日期、策略期初持仓与
交易都会保存这个分类明确的身份，因此不同分类即使使用完全相同的 symbol 也
不会覆盖。交易及期初持仓请求可传 `asset_category`；旧请求在 symbol 全局唯一
时继续兼容，出现重码时必须补充该字段。

首次加入自选会自动归入“个股”“ETF”或“指数”类型分组。每个分组成员关系
独立记录加入日期和加入价格；从单个分组移除不会影响其他分组，移出自选则会
清除该标的的全部分组关系，但保留标的和历史行情。

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

## 数据库与定时任务

以下配置均使用 `INVEST_` 前缀：

应用配置统一由 `pydantic-settings` 的 `Settings` 类加载，优先级为：创建
`Settings` 时显式传值、进程环境变量、当前工作目录下的 `.env`、代码默认值。
环境变量名大小写不敏感，空环境变量会被忽略；JSON 列表可直接用于 CORS、MCP
hosts/origins 等字段。配置会在进程内缓存，修改环境变量或 `.env` 后需重启
API、Worker 和 Beat。

- `DATABASE_URL`：SQLAlchemy URL，支持 SQLite、PostgreSQL 和 MySQL。
  常用形式分别为 `sqlite:///./invest.db`、
  `postgresql+psycopg://user:pass@host/db`、
  `mysql+pymysql://user:pass@host/db?charset=utf8mb4`。未指定驱动的
  `postgresql://`/`postgres://`/`mysql://` 会自动选用已安装驱动。
- `CELERY_BROKER_URL`：Celery broker URL，默认 `redis://localhost:6379/0`。
- `AUTO_UPDATE_ENABLED`：是否让 Beat 注册定时任务，默认 `true`。
- `AUTO_UPDATE_INTERVAL_MINUTES`：更新周期，默认 60 分钟。
- `AUTO_UPDATE_LOOKBACK_DAYS`：每次回溯天数，默认 10 天。
- `SEARCH_INDEX_UPDATE_HOUR`：每日目录索引更新时间（Asia/Shanghai），默认 3 点。
- `REPORTING_CURRENCY`：策略汇总的统一报告币种，默认 `CNY`。
- `EXCHANGE_RATE_UPDATE_HOUR`：每日汇率更新时间（Asia/Shanghai），默认 23 点。
- `MARKET_PROVIDER`：配置的付费/显式行情源，默认 `tushare`；设为
  `eastmoney` 时使用原有的东方财富主源模式。
- `MARKET_PROVIDER_ORDER`：`free_first`（默认）时先请求免费行情源，均失败或
  返回空数据后才请求 Tushare；`configured_first` 保留 Tushare 主源、AkShare
  兜底的旧顺序。
- `TUSHARE_TOKEN`：Tushare Pro token；在 `free_first` 模式下作为最后的付费
  兜底，未配置时免费行情源仍可使用。
- `EASTMONEY_TOKEN`：东方财富接口 token，免费优先模式也会使用。
- `INDEX_FALLBACK_PROVIDER`：指数日线兜底，默认 `akshare`，设为 `none`
  可关闭。AkShare 内部先请求腾讯，失败或无数据时再请求新浪。
- `ETF_FALLBACK_PROVIDER`：ETF 搜索与日线兜底，默认 `akshare`，设为
  `none` 可关闭。搜索先使用 AkShare 新浪列表、再以东方财富列表兜底；
  日线先复用无代理的东方财富 provider，失败后再使用新浪历史行情。
- `MCP_ALLOWED_HOSTS`：MCP 允许的 Host 列表；经反向代理发布时必须加入域名。
- `MCP_ALLOWED_ORIGINS`：浏览器 MCP 客户端允许的 Origin 列表。

`COMPOSE_DATABASE_URL`、`POSTGRES_*`、`MYSQL_*`、`INVEST_PORT` 和
`INVEST_WORKER_CONCURRENCY` 是 Compose 自身使用的部署变量，不会进入应用
`Settings`；Compose 最终会把对应的 `INVEST_*` 应用变量注入容器。

API 进程不执行调度，也不提供手动同步 REST/MCP 接口。Beat 默认每 60 分钟
发布一次自选及持仓行情更新任务，每天 3:10 构建本地标的索引，并在配置的汇率
小时 30 分发布汇率更新任务；Worker 负责执行。部署中应保持一个 Beat 实例，
Worker 可以按负载扩容。

默认免费优先的行情顺序为：个股使用 AkShare 腾讯、AkShare 新浪、东方财富后
再用 Tushare；指数使用 AkShare 腾讯、AkShare 新浪后再用 Tushare；ETF 使用
东方财富、AkShare 新浪后再用 Tushare。目录任务会合并 AkShare 的 A 股、ETF、
指数列表与 Tushare 的股票、ETF、指数及股票曾用名列表；单个目录源失败时保留
其他来源的结果。
索引仅保存在现有 SQL 数据库中，使用 RapidFuzz 排序，不需要部署 Elasticsearch。
Tushare 分别通过 `daily`、`fund_daily`、`index_daily` 获取个股、ETF
和指数日线，返回的成交量会从“手”换算为股/基金份额，成交额会从千元换算
为元；东方财富的沪深京成交量也会从“手”换算。所有写入数据库及 API 返回的
日线均统一使用“成交量=股/基金份额、成交额=元”。单个标的第一次同步默认回填
十年，后续更新仅回溯配置的天数。最近三天的行情会覆盖更新，更早的数据保持
不变。

汇率使用欧洲中央银行公布的欧元参考汇率。首次更新会回填 CNY、HKD、USD、EUR
及所有已使用币种的完整历史，之后每天 23:30 更新；周末和休市日估值使用目标
日期之前最近一个可用汇率。ECB 说明该参考汇率仅供信息用途，不适合作为实际
成交汇率。

## 测试

推荐使用根目录 Makefile 管理开发环境：

```bash
make deps                 # 创建/同步 .venv，并安装当前项目
make lint                 # Ruff + codespell
make test                 # pytest + 覆盖率报告
make lock-requirements    # 从 pyproject.toml 重新生成 requirements.txt
```

也可以直接执行底层命令：

```bash
PYTHONPATH=src .venv/bin/pytest
.venv/bin/ruff check .
```
