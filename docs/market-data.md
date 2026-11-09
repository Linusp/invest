# 行情源、搜索索引与定时任务

## 行情源 fallback

`INVEST_MARKET_PROVIDER_ORDER=free_first`（默认）时先使用免费源，取不到或返回空数据后再逐步 fallback。配置问财 API Key 后，问财位于免费源之后、Tushare 之前：

- 个股：AkShare 腾讯 → AkShare 新浪 → 东方财富 → 问财 → Tushare
- 指数：AkShare 腾讯 → AkShare 新浪 → 问财 → Tushare
- ETF：东方财富 → AkShare 新浪 → 问财 → Tushare

`configured_first` 保留 Tushare 主源、AkShare 兜底的旧顺序。`TUSHARE_TOKEN` 未配置时免费源仍可用。`INDEX_FALLBACK_PROVIDER` 和 `ETF_FALLBACK_PROVIDER` 可设为 `none` 关闭对应兜底。

问财使用官方 `https://openapi.iwencai.com/v1/query2data` 和 `hithink-market-query` skill。配置可使用官方名称 `IWENCAI_API_KEY`，也可使用应用名称 `INVEST_IWENCAI_API_KEY`。问财参与历史行情 fallback，并向定时搜索索引提供港股、美股普通股目录；长时间行情范围按自然年分段查询。

成交量统一为股/基金份额，成交额统一为元；Tushare 和东方财富返回的“手/千元”会在写入前换算。问财的股票和 ETF 成交量已是股/份，指数查询未返回成交量时保存为缺失值，不填充为 0。首次同步默认回填十年，后续按 `AUTO_UPDATE_LOOKBACK_DAYS` 回溯，并覆盖最近三天数据。

## 本地搜索索引

搜索只读取数据库中的轻量索引，不请求远端行情源，也不需要 Elasticsearch。索引包含类型、code、名称、别名/曾用名、拼音全拼和首字母，由 RapidFuzz 排序。

Celery Beat 每天在 `SEARCH_INDEX_UPDATE_HOUR`（默认北京时间 3 点）发布构建任务。目录任务合并 AkShare、问财和 Tushare 来源；问财港股代码统一补齐为五位并使用 `.HK`，美股代码统一使用 `.US`，原始代码作为别名保留。单个来源失败不会阻断其他来源。

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
- `MARKET_PROVIDER`、`MARKET_PROVIDER_ORDER`、`TUSHARE_TOKEN`、`EASTMONEY_TOKEN`、`IWENCAI_API_KEY`：行情源选择和认证。
- `REPORTING_CURRENCY`、`EXCHANGE_RATE_UPDATE_HOUR`：策略汇总币种和汇率任务。
- `MCP_ALLOWED_HOSTS`、`MCP_ALLOWED_ORIGINS`：MCP 反向代理和浏览器访问控制。

## 板块资金流（东方财富）

`SECTOR_FLOW_ENABLED=true` 时启用。Worker 通过东方财富 push2 接口采集行业板块（BK 板块池，
`m:90+t:2`）的日频资金流（主力/超大单/大单/中单/小单净流入），写入 `sector_capital_flows` 表。
解析逻辑移植自 MIT 许可的 [CapitalPulse](https://github.com/Dr-Liu23/CapitalPulse)。

- 数据范围：行业板块层，不含个股资金流。
- 采集规模：一次全量刷新覆盖全部 BK 板块（约 500 个），逐个请求，耗时约数分钟。
- 调度：`SECTOR_FLOW_UPDATE_HOUR/MINUTE`（默认 15:40）执行收盘后回填；
  `SECTOR_FLOW_UPDATE_MINUTES>0` 时额外按该间隔在盘中刷新当日快照。
- 查询：REST `GET /api/v1/sector-capital-flows`（板块排行）与
  `GET /api/v1/sector-capital-flows/{sector_code}/history`；MCP 工具
  `list_sector_capital_flows`、`get_sector_capital_flow`；`/analysis` 页可查看排行表与主力净流入图。

`SECTOR_FLOW_SYNC_SCOPES_ENABLED=true` 时，按总市值取前 N 个板块（`SECTOR_FLOW_SYNC_SCOPES_TOP`，
默认 30）写入 `market_scopes`，挂到 `SECTOR_FLOW_SYNC_SCOPES_PARENT`（默认 `em_industry`）之下，
使点评可以按板块对象沉淀。该同步**只新建缺失对象，不删除也不覆盖**已有 scope。

东方财富的行业口径是细粒度 BK 板块池（如「银行」「银行Ⅱ」「国有大型银行Ⅲ」并存），
并非官方标准行业分类，引用时注意区分。


配置统一使用 `INVEST_` 前缀，修改 `.env` 后需重启 API、Worker 和 Beat。
