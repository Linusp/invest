# 行情源、搜索索引与定时任务

## 行情源 fallback

`INVEST_MARKET_PROVIDER_ORDER=free_first`（默认）时先使用免费源，取不到或返回空数据后再使用 Tushare：

- 个股：AkShare 腾讯 → AkShare 新浪 → 东方财富 → Tushare
- 指数：AkShare 腾讯 → AkShare 新浪 → Tushare
- ETF：东方财富 → AkShare 新浪 → Tushare

`configured_first` 保留 Tushare 主源、AkShare 兜底的旧顺序。`TUSHARE_TOKEN` 未配置时免费源仍可用。`INDEX_FALLBACK_PROVIDER` 和 `ETF_FALLBACK_PROVIDER` 可设为 `none` 关闭对应兜底。

成交量统一为股/基金份额，成交额统一为元；Tushare 和东方财富返回的“手/千元”会在写入前换算。首次同步默认回填十年，后续按 `AUTO_UPDATE_LOOKBACK_DAYS` 回溯，并覆盖最近三天数据。

## 本地搜索索引

搜索只读取数据库中的轻量索引，不请求远端行情源，也不需要 Elasticsearch。索引包含类型、code、名称、别名/曾用名、拼音全拼和首字母，由 RapidFuzz 排序。

Celery Beat 每天在 `SEARCH_INDEX_UPDATE_HOUR`（默认北京时间 3 点）发布构建任务。目录任务合并 AkShare 和 Tushare 来源；单个来源失败不会阻断其他来源。

## 定时任务

- Beat 默认每 60 分钟发布自选及持仓行情更新任务。
- 每天构建一次标的搜索索引。
- 按 `EXCHANGE_RATE_UPDATE_HOUR`（默认 23 点）发布 ECB 汇率更新任务。
- Worker 执行实际同步任务，部署时保持一个 Beat 实例，Worker 可按负载扩容。

## 关键配置

- `DATABASE_URL`：SQLite、PostgreSQL 或 MySQL SQLAlchemy URL。
- `CELERY_BROKER_URL`：Redis broker URL。
- `AUTO_UPDATE_ENABLED`、`AUTO_UPDATE_INTERVAL_MINUTES`、`AUTO_UPDATE_LOOKBACK_DAYS`：行情更新调度。
- `SEARCH_INDEX_UPDATE_HOUR`：搜索索引更新时间。
- `MARKET_PROVIDER`、`MARKET_PROVIDER_ORDER`、`TUSHARE_TOKEN`、`EASTMONEY_TOKEN`：行情源选择。
- `REPORTING_CURRENCY`、`EXCHANGE_RATE_UPDATE_HOUR`：策略汇总币种和汇率任务。
- `MCP_ALLOWED_HOSTS`、`MCP_ALLOWED_ORIGINS`：MCP 反向代理和浏览器访问控制。

配置统一使用 `INVEST_` 前缀，修改 `.env` 后需重启 API、Worker 和 Beat。
